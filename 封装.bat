@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo   SecureVault 打包脚本
echo ========================================
echo.

REM ---------- 切换到脚本所在目录 ----------
cd /d "%~dp0"

REM ---------- 检查 Python ----------
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装并加入 PATH。
    pause
    exit /b 1
)

REM ---------- 检查 PyInstaller ----------
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [信息] 未安装 PyInstaller，正在安装...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败。
        pause
        exit /b 1
    )
)

REM ---------- 清理旧产物 ----------
echo [信息] 清理旧产物...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "__pycache__" rmdir /s /q "__pycache__"
if exist "Encryption.spec" del /f /q "Encryption.spec"
REM 清理所有子目录的 __pycache__，避免旧 pyc 干扰打包
for /d /r %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d"
)
echo [信息] 清理完成。
echo.

REM ---------- 打包 ----------
echo [信息] 开始打包...
python -m PyInstaller --onefile --windowed --name Encryption --icon=myicon_1.ico --add-data "lang;lang" --add-data "myicon_1.ico;." main.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败。
    pause
    exit /b 1
)

echo.
echo [信息] 打包成功：dist\Encryption.exe
echo.

REM ---------- 计算 SHA-256 ----------
echo ========================================
echo   SHA-256 校验值
echo ========================================
echo.

set "HASH="
for /f "skip=1 tokens=* delims=" %%H in ('certutil -hashfile "dist\Encryption.exe" SHA256 ^| findstr /r /v "^CertUtil"') do (
    if not defined HASH (
        set "HASH=%%H"
    )
)

REM 去掉哈希里的空格
set "HASH_CLEAN=!HASH: =!"

if "!HASH_CLEAN!"=="" (
    echo [警告] 未能自动计算 SHA-256，请手动执行：
    echo     certutil -hashfile dist\Encryption.exe SHA256
) else (
    echo SHA-256: !HASH_CLEAN!
    echo.
    echo 请把上面这一行直接复制到 GitHub Release 的说明里。
)

echo.
echo ========================================
echo   完成
echo ========================================
echo.
echo 产物路径：
echo   %~dp0dist\Encryption.exe
echo.
echo 下一步：
echo   1. 打开 GitHub Releases 页面，编辑 Release
echo.

REM 打开 dist 目录方便查看
if exist "dist" explorer "dist"

pause
endlocal