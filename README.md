# 作业小助手 HomeworkBot

**3.3.0** · 在后台接收 QQ 班级群消息，找出老师布置的作业，用 AI 整理成统一格式并按日期存档，再推送到企业微信群。v3.0 起无需打开 QQ / 微信窗口。

## 功能特性

- QQ 班级群 → NapCat（OneBot v11）→ 作业小助手 → 企业微信群机器人 Webhook。
- 可用大模型（如 DeepSeek、通义千问）整理作业；不填 Key 时使用内置规则。
- 完全后台运行：NapCat 登录 QQ 小号，推送走企业微信 Webhook。
- 支持反向 / 正向 WebSocket 或 HTTP 上报与 NapCat 对接，并可在应用内测试连接。

## 下载

本仓库目前没有已发布的 GitHub Release 安装包。请从源码运行。GitHub 自动生成的 Source code zip/tar 不算安装包。

## 界面截图

仓库里目前还没有已提交的真实产品界面截图（图标、logo 或品牌图不算）。请不要把下列预留路径当成已经存在的图片去引用（避免破链）。待在真实运行窗口中截取后放入：

- `docs/screenshots/01-workbench.png`
- `docs/screenshots/02-main-or-result.png`

截图说明必须写明操作系统、软件版本、是否示例/演示数据，以及是否在 Windows 安装后截取。

## 技术栈

- Python 3.9+
- NapCat（OneBot v11）
- 企业微信群机器人 Webhook

## 从源码运行

源码在仓库根目录。本仓库不包含安装包。

```bash
# Windows 可双击 run.bat（首次自动安装依赖）
# 或：
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```
还需自行准备：QQ 小号 + NapCat，以及企业微信群机器人 Webhook。配置步骤见该目录 README（请忽略其中未包含在本仓库的安装包文件名）。

## 文档

## 贡献

欢迎通过 Issue 和 Pull Request 参与，详见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。参与时请遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可证

本仓库尚未附带 LICENSE 文件，许可证未指定。

---

## English

# HomeworkBot

**3.3.0** · Ingests class-group QQ messages in the background, finds homework assignments, normalizes them with AI, archives them by date, and pushes them to a WeCom group. Since v3.0 it does not need the QQ or WeChat windows to stay open.

## Features

- Flow: class QQ group → NapCat (OneBot v11) → HomeworkBot → WeCom group webhook.
- Optional LLM (for example DeepSeek or Qwen) to normalize assignments; built-in rules are used when no key is configured.
- Fully headless: NapCat logs in with a secondary QQ account; delivery uses a WeCom webhook.
- Connect to NapCat over reverse or forward WebSocket or HTTP postback, and test the link in the app.

## Downloads

This repository has no published GitHub Release installer. Run it from source. The automatic Source code zip/tar from GitHub is not an installer.

## Screenshots

No real product-window screenshot has been committed yet (icons, logos, and brand art do not count). Do not add markdown image links to the reserved paths below until the files exist (that would be a broken link). After a live capture, place:

- `docs/screenshots/01-workbench.png`
- `docs/screenshots/02-main-or-result.png`

Captions must state the OS, version, whether the data is sample/demo, and whether the shot was taken after a Windows install.

## Tech stack

- Python 3.9+
- NapCat（OneBot v11）
- 企业微信群机器人 Webhook

## Getting started

Source is at the repository root. This repository does not include installers.

```bash
# On Windows you can double-click run.bat (it installs dependencies on first run)
# Or:
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```
You also need a secondary QQ account with NapCat, and a WeCom group webhook. Setup steps are in that README; ignore installer filenames that are not in this repository.

## Documentation

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Please report vulnerabilities privately via [SECURITY.md](SECURITY.md). This project follows [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

No LICENSE file is included in this repository; the license is unspecified.
