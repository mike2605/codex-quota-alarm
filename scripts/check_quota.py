#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path


HOME = Path.home()
APP_DIR = Path(os.environ.get("CODEX_QUOTA_APP_DIR", HOME / ".codex" / "codex-quota-alert")).expanduser()
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.json"
SCHEDULE_PATH = APP_DIR / "reminder_schedule.json"
LOG_DIR = APP_DIR / "logs"
LAUNCHD_LABEL = "com.codex-quota-alarm.monitor"
PLIST_PATH = HOME / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
DEFAULT_URL = "https://chatgpt.com/codex/settings/usage"
DEFAULT_SCHEDULE_POLL_INTERVAL_SECONDS = 60
DEFAULT_POST_RESET_INTERVAL_SECONDS = 9000


def now_dt():
    return dt.datetime.now().astimezone()


def now_iso():
    return now_dt().isoformat(timespec="seconds")


def ensure_dirs():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def default_config():
    return {
        "url": DEFAULT_URL,
        "schedule_poll_interval_seconds": DEFAULT_SCHEDULE_POLL_INTERVAL_SECONDS,
        "post_reset_interval_seconds": DEFAULT_POST_RESET_INTERVAL_SECONDS,
        "low_quota_threshold_percent": 25,
        "notify_mac": True,
        "notify_imessage": True,
        "imessage_recipient": os.environ.get("CODEX_QUOTA_IMESSAGE_TO", ""),
    }


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_json(path, value):
    ensure_dirs()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_config():
    config = default_config()
    saved_config = load_json(CONFIG_PATH, {})
    config.update(saved_config)
    migrated = False
    if "schedule_poll_interval_seconds" not in saved_config:
        config["schedule_poll_interval_seconds"] = DEFAULT_SCHEDULE_POLL_INTERVAL_SECONDS
        migrated = True
    if "post_reset_interval_seconds" not in saved_config:
        config["post_reset_interval_seconds"] = DEFAULT_POST_RESET_INTERVAL_SECONDS
        migrated = True
    for deprecated_key in ("check_interval_seconds", "phone_notification_interval_seconds"):
        if deprecated_key in config:
            config.pop(deprecated_key, None)
            migrated = True
    if migrated and CONFIG_PATH.exists():
        save_json(CONFIG_PATH, config)
    return config


def applescript_string(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def run_osascript(script, timeout=30):
    return subprocess.run(
        ["osascript", "-"],
        input=script,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def read_chrome_text(url, timeout=45):
    script = f"""
tell application "Google Chrome"
    set quotaWindow to make new window
    set bounds of quotaWindow to {{80, 80, 980, 760}}
    set quotaTab to active tab of quotaWindow
    try
        set URL of quotaTab to {applescript_string(url)}
        set startedAt to current date
        repeat
            delay 1
            try
                set readyState to execute quotaTab javascript "document.readyState"
                if readyState is "complete" then exit repeat
            end try
            if ((current date) - startedAt) > {timeout} then exit repeat
        end repeat
        set dataStartedAt to current date
        repeat
            delay 1
            try
                set bodyText to execute quotaTab javascript "document.body ? document.body.innerText : ''"
                if bodyText contains "每周使用限额" or bodyText contains "Weekly usage limit" or bodyText contains "Weekly limit" then exit repeat
                if bodyText does not contain "正在加载使用数据" and bodyText does not contain "Loading usage data" then
                    if ((current date) - dataStartedAt) > 6 then exit repeat
                end if
            end try
            if ((current date) - dataStartedAt) > {timeout} then exit repeat
        end repeat
        set finalText to execute quotaTab javascript "document.body ? document.body.innerText : ''"
        close quotaWindow
        return finalText
    on error errMsg number errNum
        try
            close quotaWindow
        end try
        error errMsg number errNum
    end try
end tell
"""
    result = run_osascript(script, timeout=timeout + 15)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or "Chrome page read failed")
    text = result.stdout.strip()
    if not text:
        raise RuntimeError("Chrome returned an empty page")
    return text


def compact_space(value):
    return re.sub(r"\s+", " ", value or "").strip()


def clamp_percent(value):
    if value is None:
        return None
    return max(0, min(100, int(round(value))))


def extract_window_status(text, label_patterns, reset_label):
    normalized = compact_space(text)
    label_group = "|".join(label_patterns)
    match = re.search(rf"({label_group})(?P<section>.{{0,360}})", normalized, re.IGNORECASE)
    if not match:
        return {"remaining_percent": None, "reset_text": None}

    section = match.group("section")
    remaining = None
    percent_match = re.search(
        r"(\d{1,3})\s*%\s*(?:剩余|remaining|left|available)|(?:剩余|remaining|left|available).{0,80}?(\d{1,3})\s*%",
        section,
        re.IGNORECASE,
    )
    if percent_match:
        remaining = clamp_percent(float(percent_match.group(1) or percent_match.group(2)))

    reset_text = None
    reset_match = re.search(
        r"(重置时间|reset time|resets?|renews?)\s*[：:]?\s*(?P<value>.+?)(?=\s+(?:5 小时使用限额|5小时使用限额|五小时使用限额|每周使用限额|每周限额|剩余额度|使用积分|个人使用|使用详情|额度使用记录|5-hour usage limit|5 hour usage limit|Weekly usage limit|Weekly limit|Credits|Usage details|Personal usage|$))",
        section,
        re.IGNORECASE,
    )
    if reset_match:
        reset_value = compact_space(reset_match.group("value"))[:120]
        reset_text = f"{reset_label}：{reset_value}" if reset_value else None

    return {"remaining_percent": remaining, "reset_text": reset_text}


def extract_five_hour_status(text):
    return extract_window_status(
        text,
        [
            r"5\s*小时使用限额",
            r"5小时使用限额",
            r"五小时使用限额",
            r"5-hour usage limit",
            r"5 hour usage limit",
        ],
        "5小时重置时间",
    )


def extract_percent(text):
    weekly = extract_weekly_status(text)
    if weekly.get("remaining_percent") is not None:
        return weekly["remaining_percent"], "weekly_remaining_percent"

    patterns = [
        r"(\d{1,3})\s*%\s*(?:remaining|left|available|剩余|还剩|可用)",
        r"(?:remaining|left|available|剩余|还剩|可用)[^\n%]{0,120}?(\d{1,3})\s*%",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return clamp_percent(float(match.group(1))), "remaining_percent"

    used_patterns = [
        r"(\d{1,3})\s*%\s*(?:used|已用|已使用|使用)",
        r"(?:used|已用|已使用|使用)[^\n%]{0,120}?(\d{1,3})\s*%",
    ]
    for pattern in used_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return clamp_percent(100 - float(match.group(1))), "used_percent"

    fraction_patterns = [
        r"(?:used|usage|已用|使用)[^\n]{0,80}?([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)",
        r"([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)[^\n]{0,80}?(?:used|usage|已用|使用)",
    ]
    for pattern in fraction_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            used = float(match.group(1))
            total = float(match.group(2))
            if total > 0 and used <= total:
                return clamp_percent(100 - (used / total * 100)), "used_fraction"

    return None, "not_found"


def extract_weekly_status(text):
    return extract_window_status(
        text,
        [r"每周使用限额", r"每周限额", r"Weekly usage limit", r"Weekly limit"],
        "每周重置时间",
    )


def extract_reset_text(text):
    weekly = extract_weekly_status(text)
    if weekly.get("reset_text"):
        return weekly["reset_text"]

    lines = [compact_space(line) for line in text.splitlines()]
    candidates = [
        line for line in lines
        if line and re.search(r"reset|renews|refresh|resets|重置|刷新|恢复", line, re.IGNORECASE)
    ]
    if not candidates:
        return None

    ranked = sorted(candidates, key=lambda line: (0 if re.search(r"next|下次|将|on|at|in", line, re.I) else 1, len(line)))
    return ranked[0][:240]


def parse_quota_text(text):
    five_hour = extract_five_hour_status(text)
    weekly = extract_weekly_status(text)
    remaining, source = extract_percent(text)
    reset_text = extract_reset_text(text)
    page_excerpt = compact_space(text)[:500]
    return {
        "ok": remaining is not None,
        "checked_at": now_iso(),
        "five_hour_remaining_percent": five_hour.get("remaining_percent"),
        "five_hour_reset_text": five_hour.get("reset_text"),
        "weekly_remaining_percent": weekly.get("remaining_percent"),
        "weekly_reset_text": weekly.get("reset_text"),
        "remaining_percent": remaining,
        "remaining_source": source,
        "reset_text": reset_text,
        "page_excerpt": page_excerpt,
    }


def read_status(args, config):
    if args.mock_text_file:
        text = Path(args.mock_text_file).read_text(encoding="utf-8")
    elif os.environ.get("CODEX_QUOTA_MOCK_TEXT"):
        text = os.environ["CODEX_QUOTA_MOCK_TEXT"]
    else:
        text = read_chrome_text(config["url"], timeout=args.timeout)
    return parse_quota_text(text)


def format_status(status):
    if not status.get("ok"):
        return "没有读到 Codex 额度。"

    five_remaining = status.get("five_hour_remaining_percent")
    five_reset = status.get("five_hour_reset_text") or "页面没有显示"
    weekly_remaining = status.get("weekly_remaining_percent", status.get("remaining_percent"))
    weekly_reset = status.get("weekly_reset_text") or status.get("reset_text") or "页面没有显示"

    lines = []
    if five_remaining is not None:
        lines.append(f"5小时剩余：{five_remaining}%。")
        lines.append(f"{five_reset}。")
    else:
        lines.append("5小时剩余：页面没有显示。")
    if weekly_remaining is not None:
        lines.append(f"本周剩余：{weekly_remaining}%。")
    else:
        lines.append("本周剩余：页面没有显示。")
    lines.append(f"{weekly_reset}。")
    return "\n".join(lines)


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed


def format_reminder_time(value):
    if isinstance(value, str):
        value = parse_iso_datetime(value)
    if not value:
        return "页面没有显示"
    local = value.astimezone()
    return f"{local.month}月{local.day}日 {local.hour:02d}:{local.minute:02d}"


def format_status_with_next_reminder(status, next_reminder_at):
    return f"{format_status(status)}\n下次提醒时间：{format_reminder_time(next_reminder_at)}。"


def get_first_next_reminder_at(status):
    return parse_reset_datetime(status.get("five_hour_reset_text"), status.get("checked_at"))


def imessage_was_sent(results):
    return bool((results.get("imessage") or {}).get("ok"))


def load_schedule():
    return load_json(SCHEDULE_PATH, {})


def save_schedule(schedule):
    save_json(SCHEDULE_PATH, schedule)


def schedule_due(schedule, now=None):
    next_reminder_at = parse_iso_datetime(schedule.get("next_reminder_at"))
    if not next_reminder_at:
        return False, None
    now = now or now_dt()
    return now >= next_reminder_at, next_reminder_at


def next_interval_time(planned_at, now, interval_seconds):
    next_at = planned_at + dt.timedelta(seconds=interval_seconds)
    while next_at <= now:
        next_at += dt.timedelta(seconds=interval_seconds)
    return next_at


def save_successful_phone_reminder(status, message, results, next_reminder_at, sent_count, planned_at=None):
    save_json(STATE_PATH, status)
    save_json(APP_DIR / "last_phone_status_notification.json", {
        "sent_at": now_iso(),
        "message": message,
        "results": {"imessage": results.get("imessage")},
    })
    save_schedule({
        "next_reminder_at": next_reminder_at.isoformat(timespec="seconds"),
        "sent_count": sent_count,
        "last_sent_at": now_iso(),
        "last_planned_reminder_at": planned_at.isoformat(timespec="seconds") if planned_at else None,
        "updated_at": now_iso(),
    })


def notify_mac(title, message):
    script = f'display notification {applescript_string(message)} with title {applescript_string(title)}'
    return run_osascript(script, timeout=10)


def notify_imessage(recipient, message):
    if not recipient:
        return False, "iMessage recipient is not configured"
    script = f"""
tell application "Messages"
    set targetService to 1st service whose service type = iMessage
    set targetBuddy to buddy {applescript_string(recipient)} of targetService
    send {applescript_string(message)} to targetBuddy
end tell
"""
    result = run_osascript(script, timeout=20)
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout).strip()


def send_notifications(config, title, message, include_phone=True):
    results = {"mac": None, "imessage": None}
    if config.get("notify_mac", True):
        mac = notify_mac(title, message)
        results["mac"] = {"ok": mac.returncode == 0, "error": (mac.stderr or mac.stdout).strip()}
    if include_phone and config.get("notify_imessage", True):
        ok, error = notify_imessage(config.get("imessage_recipient", ""), f"{title}。{message}")
        results["imessage"] = {"ok": ok, "error": error}
    return results


def send_phone_notification(config, title, message):
    results = {"imessage": None}
    if config.get("notify_imessage", True):
        ok, error = notify_imessage(config.get("imessage_recipient", ""), f"{title}。{message}")
        results["imessage"] = {"ok": ok, "error": error}
    return results


def should_send_error_notification():
    last_error = load_json(APP_DIR / "last_error.json", {})
    last_sent = last_error.get("notified_at")
    if not last_sent:
        return True
    try:
        sent_at = dt.datetime.fromisoformat(last_sent)
    except ValueError:
        return True
    return dt.datetime.now().astimezone() - sent_at >= dt.timedelta(hours=6)


def save_error(error, notified):
    save_json(APP_DIR / "last_error.json", {
        "checked_at": now_iso(),
        "notified_at": now_iso() if notified else load_json(APP_DIR / "last_error.json", {}).get("notified_at"),
        "error": str(error),
    })


def reset_signal(status):
    reset = compact_space(status.get("reset_text") or "")
    remaining = status.get("remaining_percent")
    if not reset or remaining is None:
        return None
    return reset


def parse_reset_datetime(reset_text, checked_at):
    if not reset_text or not checked_at:
        return None
    try:
        base = dt.datetime.fromisoformat(checked_at)
    except ValueError:
        return None

    text = compact_space(reset_text)
    dated = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日\s*(\d{1,2})[:：](\d{2})", text)
    if dated:
        year, month, day, hour, minute = map(int, dated.groups())
        return dt.datetime(year, month, day, hour, minute, tzinfo=base.tzinfo)

    timed = re.search(r"(\d{1,2})[:：](\d{2})", text)
    if not timed:
        return None
    hour, minute = map(int, timed.groups())
    candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate < base - dt.timedelta(minutes=5):
        candidate += dt.timedelta(days=1)
    return candidate


def reset_key(reset_at):
    if not reset_at:
        return None
    return reset_at.isoformat(timespec="minutes")


def should_alert_reset(previous, current):
    signal = reset_signal(current)
    if not signal or not previous or not previous.get("ok"):
        return False, "baseline_missing"

    previous_signal = reset_signal(previous)
    previous_remaining = previous.get("remaining_percent")
    current_remaining = current.get("remaining_percent")
    if not previous_signal or previous_remaining is None or current_remaining is None:
        return False, "previous_signal_missing"

    previous_five_reset = parse_reset_datetime(previous.get("five_hour_reset_text"), previous.get("checked_at"))
    current_checked_at = parse_reset_datetime(current.get("checked_at"), current.get("checked_at"))
    previous_five_remaining = previous.get("five_hour_remaining_percent")
    current_five_remaining = current.get("five_hour_remaining_percent")
    previous_five_key = reset_key(previous_five_reset)
    notified_five_key = previous.get("notified_five_hour_reset_key")
    if (
        previous_five_reset
        and current_checked_at
        and previous_five_reset <= current_checked_at
        and previous_five_key != notified_five_key
        and current_five_remaining is not None
        and current_five_remaining >= 90
        and (previous_five_remaining is None or current_five_remaining >= previous_five_remaining)
    ):
        current["notified_five_hour_reset_key"] = previous_five_key
        return True, "five_hour_reset"

    current["notified_five_hour_reset_key"] = notified_five_key

    if signal != previous_signal and current_remaining >= previous_remaining:
        return True, "reset_text_changed"
    if current_remaining >= 90 and previous_remaining <= 50 and current_remaining - previous_remaining >= 25:
        return True, "quota_recovered"
    return False, "not_reset"


def command_check(args):
    config = load_config()
    status = read_status(args, config)
    if args.save_state:
        save_json(STATE_PATH, status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    print(format_status(status))
    return 0 if status.get("ok") else 2


def command_monitor(args):
    config = load_config()
    schedule = load_schedule()
    due, planned_at = schedule_due(schedule)
    if not due:
        print(json.dumps({
            "due": False,
            "reason": "not_due" if planned_at else "schedule_missing",
            "next_reminder_at": planned_at.isoformat(timespec="seconds") if planned_at else None,
            "schedule": schedule,
        }, ensure_ascii=False, indent=2))
        return 0

    try:
        current = read_status(args, config)
    except Exception as exc:
        title = "Codex 额度检查失败"
        message = f"没有读到 Codex 使用页面：{exc}"
        notified = False
        if should_send_error_notification():
            send_notifications(config, title, message, include_phone=False)
            notified = True
        save_error(exc, notified)
        return 3

    if not current.get("ok"):
        notified = False
        if should_send_error_notification():
            send_notifications(config, "Codex 额度检查失败", "读到了页面，但没有识别出剩余额度。", include_phone=False)
            notified = True
        save_error("quota was not recognized", notified)
        return 2

    sent_count = int(schedule.get("sent_count", 0)) + 1
    interval_seconds = int(config.get("post_reset_interval_seconds", DEFAULT_POST_RESET_INTERVAL_SECONDS))
    next_reminder_at = next_interval_time(planned_at, now_dt(), interval_seconds)
    message = format_status_with_next_reminder(current, next_reminder_at)
    results = send_phone_notification(config, "Codex 当前额度", message)
    if not imessage_was_sent(results):
        print(json.dumps({
            "sent": False,
            "reason": "imessage_failed",
            "results": results,
            "status": current,
            "schedule": schedule,
        }, ensure_ascii=False, indent=2))
        return 4

    save_successful_phone_reminder(current, message, results, next_reminder_at, sent_count, planned_at=planned_at)
    print(json.dumps({
        "sent": True,
        "planned_reminder_at": planned_at.isoformat(timespec="seconds"),
        "next_reminder_at": next_reminder_at.isoformat(timespec="seconds"),
        "sent_count": sent_count,
        "results": results,
        "status": current,
    }, ensure_ascii=False, indent=2))
    return 0


def send_current_and_seed_schedule(args, include_phone=True):
    config = load_config()
    if getattr(args, "recipient", None):
        config["imessage_recipient"] = args.recipient
    status = read_status(args, config)
    if not status.get("ok"):
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 2
    next_reminder_at = get_first_next_reminder_at(status)
    if not next_reminder_at:
        print(json.dumps({
            "error": "没有读到 5 小时额度重置时间，无法设置下一次提醒。",
            "status": status,
        }, ensure_ascii=False, indent=2))
        return 2
    message = format_status_with_next_reminder(status, next_reminder_at)
    results = send_notifications(config, "Codex 当前额度", message, include_phone=include_phone)
    if include_phone and not imessage_was_sent(results):
        save_json(STATE_PATH, status)
        print(json.dumps({"message": message, "results": results, "status": status}, ensure_ascii=False, indent=2))
        return 4
    save_json(STATE_PATH, status)
    if include_phone:
        save_successful_phone_reminder(status, message, results, next_reminder_at, 1)
    print(json.dumps({
        "message": message,
        "next_reminder_at": next_reminder_at.isoformat(timespec="seconds"),
        "results": results,
        "status": status,
    }, ensure_ascii=False, indent=2))
    return 0 if not results.get("mac") or results["mac"].get("ok") else 3


def command_notify_test(args):
    return send_current_and_seed_schedule(args, include_phone=not args.mac_only)


def command_notify_current(args):
    return send_current_and_seed_schedule(args, include_phone=True)


def command_set_imessage(args):
    config = load_config()
    config["imessage_recipient"] = args.recipient
    config["notify_imessage"] = True
    save_json(CONFIG_PATH, config)
    print(f"iMessage recipient set to: {args.recipient}")
    return 0


def command_install(args):
    ensure_dirs()
    config = load_config()
    save_json(CONFIG_PATH, config)

    script_path = Path(__file__).resolve()
    plist = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [sys.executable, str(script_path), "--timeout", "25", "monitor"],
        "StartInterval": int(config.get("schedule_poll_interval_seconds", DEFAULT_SCHEDULE_POLL_INTERVAL_SECONDS)),
        "RunAtLoad": True,
        "StandardOutPath": str(LOG_DIR / "launchd.out.log"),
        "StandardErrorPath": str(LOG_DIR / "launchd.err.log"),
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        },
    }
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(plist, handle)

    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(PLIST_PATH)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    boot = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if boot.returncode != 0:
        print((boot.stderr or boot.stdout).strip(), file=sys.stderr)
        return boot.returncode
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{LAUNCHD_LABEL}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Installed launchd job: {PLIST_PATH}")
    print("Wakes every 1 minute; checks quota only at the scheduled reminder time.")
    return 0


def command_uninstall(args):
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(PLIST_PATH)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print("Uninstalled Codex quota alert job.")
    return 0


def command_status(args):
    state = load_json(STATE_PATH, {})
    config = load_config()
    schedule = load_schedule()
    print(json.dumps({
        "config": config,
        "state": state,
        "schedule": schedule,
        "plist": str(PLIST_PATH),
        "plist_exists": PLIST_PATH.exists(),
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Check Codex quota and send reset reminders.")
    parser.add_argument("--mock-text-file", help="Read page text from a file for tests.")
    parser.add_argument("--timeout", type=int, default=45, help="Chrome page load timeout in seconds.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="Read and print current quota status.")
    check.add_argument("--save-state", action="store_true", help="Save this status as the monitor baseline.")
    check.set_defaults(func=command_check)

    monitor = subparsers.add_parser("monitor", help="Wake scheduler and send quota only when the reminder is due.")
    monitor.set_defaults(func=command_monitor)

    notify_test = subparsers.add_parser("notify-test", help="Send a test notification.")
    notify_test.add_argument("--recipient", help="Temporary iMessage recipient for this test.")
    notify_test.add_argument("--mac-only", action="store_true", help="Only test Mac notification.")
    notify_test.set_defaults(func=command_notify_test)

    notify_current = subparsers.add_parser("notify-current", help="Read live quota and send the current status.")
    notify_current.set_defaults(func=command_notify_current)

    set_imessage = subparsers.add_parser("set-imessage", help="Set phone number or Apple ID for iMessage notifications.")
    set_imessage.add_argument("recipient")
    set_imessage.set_defaults(func=command_set_imessage)

    install = subparsers.add_parser("install", help="Install local reminder scheduler.")
    install.set_defaults(func=command_install)

    uninstall = subparsers.add_parser("uninstall", help="Remove the local launchd reminder.")
    uninstall.set_defaults(func=command_uninstall)

    status = subparsers.add_parser("status", help="Print config and last state.")
    status.set_defaults(func=command_status)
    return parser


def main():
    args = build_parser().parse_args()
    ensure_dirs()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
