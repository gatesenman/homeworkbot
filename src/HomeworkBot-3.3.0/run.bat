@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist .venv (
  echo 首次运行, 正在创建虚拟环境并安装依赖...
  python -m venv .venv || (echo 请先安装 Python 3.9+ 并勾选 Add to PATH & pause & exit /b 1)
  .venv\Scripts\python -m pip install -U pip -i https://pypi.tuna.tsinghua.edu.cn/simple
  .venv\Scripts\pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)
start "" .venv\Scripts\pythonw.exe main.py %*
