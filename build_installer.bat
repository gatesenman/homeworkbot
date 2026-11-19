@echo off
chcp 65001 >nul
cd /d %~dp0
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" goto noiscc
if not exist dist\HomeworkBot\HomeworkBot.exe call build_exe.bat nopause
"%ISCC%" installer\HomeworkBot.iss
if errorlevel 1 exit /b 1
echo 安装包: dist\HomeworkBot-Setup-3.3.0.exe
exit /b 0
:noiscc
echo 未找到 Inno Setup 6, 请先安装: winget install JRSoftware.InnoSetup
exit /b 1
