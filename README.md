# Codex Quota Alarm

一个 macOS 本地小工具：每 30 分钟检查一次 Codex 额度，在 5 小时额度或每周额度重置后，通过 Mac 通知和 iMessage 提醒你。

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

这会保存收件人，并发送一条测试消息。

## 自动提醒规则

安装后会创建一个本地定时任务：

- 每 30 分钟检查一次
- 5 小时额度重置后提醒
- 每周额度重置后提醒
- 普通检查不发消息，避免刷屏
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

它不是每 30 分钟都发消息，而是每 30 分钟检查一次。只有额度重置后才会提醒。

### 为什么 Chrome 会打开一个窗口？

检查时会临时打开一个独立 Chrome 窗口读取额度，读完自动关闭，不会占用你正在浏览的标签页。

### iMessage 显示发送成功，但手机没收到？

确认 Mac 的信息 App 已登录同一个 Apple ID，并且这个号码或 Apple ID 能正常收到来自 Mac 的 iMessage。
