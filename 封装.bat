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

REM ---------- 检查 cryptography（用于签名） ----------
python -c "import cryptography" >nul 2>&1
if errorlevel 1 (
    echo [信息] 未安装 cryptography，尝试安装...
    python -m pip install cryptography
    if errorlevel 1 (
        echo [警告] cryptography 安装失败，本次将跳过签名生成。
        echo         如果 updater.py 中已配置 SIGNING_PUBLIC_KEY，
        echo         缺少签名会导致用户端无法更新！
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

REM ---------- 生成签名 ----------
echo ========================================
echo   生成签名文件
echo ========================================
echo.

python sign.py
set "SIGN_RC=!errorlevel!"

if not "!SIGN_RC!"=="0" (
    echo.
    echo [警告] 签名生成失败（退出码 !SIGN_RC!）。
    echo.
    echo         如果 updater.py 里的 SIGNING_PUBLIC_KEY 为 ""（空），
    echo         用户端会跳过签名校验，仍能更新。
    echo.
    echo         如果 SIGNING_PUBLIC_KEY 已配置，则用户端会拒绝本次更新！
    echo         请排查签名问题后重新运行本脚本。
    echo.
) else (
    if exist "dist\Encryption.exe.sig" (
        echo [信息] 签名文件已就绪：dist\Encryption.exe.sig
    )
)

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
echo 产物清单：
echo   %~dp0dist\Encryption.exe
if exist "dist\Encryption.exe.sig" (
    echo   %~dp0dist\Encryption.exe.sig
)
echo.
echo 下一步：
echo   1. 打开 GitHub Releases 页面，编辑 Release
echo   2. 上传 dist\Encryption.exe
if exist "dist\Encryption.exe.sig" (
    echo   3. 同时上传 dist\Encryption.exe.sig
    echo   4. 把上面的 SHA-256 粘贴到 Release 说明里
) else (
    echo   3. 把上面的 SHA-256 粘贴到 Release 说明里
    echo   4. 如需签名保护，请排查签名失败原因后重新打包
)
echo.

REM 打开 dist 目录方便查看
if exist "dist" explorer "dist"

pause
endlocal