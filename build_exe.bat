@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist .venv python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python tools\make_icon.py
.venv\Scripts\pip uninstall -y -q rapidocr_onnxruntime onnxruntime opencv-python uiautomation comtypes shapely pyclipper >nul 2>&1
.venv\Scripts\pyinstaller --noconfirm --clean --onedir --windowed --name HomeworkBot ^
  --exclude-module numpy --exclude-module cv2 --exclude-module onnxruntime --exclude-module uiautomation ^
  --icon=assets\icon.ico --add-data "assets;assets" ^
  --collect-all customtkinter --collect-submodules websockets ^
  --collect-all win11toast --hidden-import pystray._win32 --hidden-import plyer.platforms.win.notification ^
  main.py
if errorlevel 1 (
  echo 打包失败, 请查看上方错误信息. 若提示拒绝访问, 请先退出正在运行的 HomeworkBot.exe
  if /i not "%1"=="nopause" pause
  exit /b 1
)
echo.
echo 打包完成: dist\HomeworkBot\HomeworkBot.exe  (请整个 HomeworkBot 文件夹一起复制)
if /i not "%1"=="nopause" pause
