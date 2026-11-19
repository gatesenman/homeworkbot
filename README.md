# 作业小助手 HomeworkBot

**3.3.0** · 在后台接收 QQ 班级群消息，找出老师布置的作业，用 AI 整理成统一格式并按日期存档，再推送到企业微信群。v3.0 起无需打开 QQ / 微信窗口。

## 功能特性

- QQ 班级群 → NapCat（OneBot v11）→ 作业小助手 → 企业微信群机器人 Webhook。
- 可用大模型（如 DeepSeek、通义千问）整理作业；不填 Key 时使用内置规则。
- 完全后台运行：NapCat 登录 QQ 小号，推送走企业微信 Webhook。
- 支持反向 / 正向 WebSocket 或 HTTP 上报与 NapCat 对接，并可在应用内测试连接。

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

- [源码 README](README.original.md)

---

## English

# HomeworkBot

**3.3.0** · Ingests class-group QQ messages in the background, finds homework assignments, normalizes them with AI, archives them by date, and pushes them to a WeCom group. Since v3.0 it does not need the QQ or WeChat windows to stay open.

## Features

- Flow: class QQ group → NapCat (OneBot v11) → HomeworkBot → WeCom group webhook.
- Optional LLM (for example DeepSeek or Qwen) to normalize assignments; built-in rules are used when no key is configured.
- Fully headless: NapCat logs in with a secondary QQ account; delivery uses a WeCom webhook.
- Connect to NapCat over reverse or forward WebSocket or HTTP postback, and test the link in the app.

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

- [源码 README](README.original.md)

