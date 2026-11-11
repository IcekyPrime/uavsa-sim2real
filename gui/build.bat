@echo off
rem 打包 UAVSA.exe（需先安装 pyinstaller + pywebview）
chcp 65001 >nul
cd /d "%~dp0"

echo [1/2] 安装打包依赖...
python -m pip install pyinstaller pywebview -q

echo [2/2] 打包 exe...
python -m PyInstaller --noconfirm --clean UAVSA.spec

echo.
echo 完成：gui\dist\UAVSA.exe
pause
