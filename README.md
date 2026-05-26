# Codex Quota Alarm

一个 macOS 本地小工具：按 Codex 5 小时额度节奏检查额度，并通过 iMessage 给手机发送当前额度。

它会读取 ChatGPT 的 Codex 使用情况页面：

- 5 小时剩余额度
- 5 小时重置时间
- 每周剩余额度
- 每周重置时间

## 要求

- macOS
- Google Chrome
- Chrome 已登录 ChatGPT/Codex
- Python 3
- 如果要手机提醒：Mac 的信息 App 已登录 iMessage

## 安装

```bash
git clone https://github.com/mike2605/codex-quota-alarm.git
cd codex-quota-alarm
./install.sh
```

然后打开 Chrome 菜单：

```text
View > Developer > Allow JavaScript from Apple Events
```

中文 Chrome 一般是：

```text
显示 > 开发者 > 允许 Apple 事件中的 JavaScript
```

## 手动检查

```bash
./check
```

## 设置 iMessage 手机提醒

```bash
./configure.sh "+8613800000000"
```

这会保存收件人，立刻读取一次真实额度，并把当前额度发送到手机。
短信最后会显示下一次提醒时间。

## 自动提醒规则

安装后会创建一个本地定时任务：

- 输入手机号后立刻查看并发送第一条真实额度
- 第二条等到 5 小时额度重置时间再发送
- 第三条开始，每 2.5 小时查看并发送一次
- 没到提醒时间时，不打开 Chrome、不读取额度、不发送手机信息
- 每次查看额度时，都会发送一条手机信息
- 页面读取失败时，最多每 6 小时发一次 Mac 失败提醒

## 卸载

```bash
./uninstall.sh
```

本地配置默认保存在：

```text
~/.codex/codex-quota-alert
```

## 隐私

这个工具只在本机运行。

- 不上传账号
- 不保存密码
- 不上传额度数据
- 不需要 OpenAI API Key

它只是通过 Chrome 读取你自己已经登录的 Codex 使用情况页面。

## 常见问题

### 为什么没有收到提醒？

先运行 `./configure.sh "+手机号"`。第一条会立刻发送，后续会按短信里的“下次提醒时间”发送。

### 为什么 Chrome 会打开一个窗口？

检查时会临时打开一个独立 Chrome 窗口读取额度，读完自动关闭，不会占用你正在浏览的标签页。

### iMessage 显示发送成功，但手机没收到？

确认 Mac 的信息 App 已登录同一个 Apple ID，并且这个号码或 Apple ID 能正常收到来自 Mac 的 iMessage。
