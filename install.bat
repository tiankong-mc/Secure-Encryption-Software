@echo off
chcp 65001 >nul
title Encryption - 依赖安装

echo ========================================
echo    Encryption 依赖安装脚本
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.9 或更高版本。
    echo        下载地址：https://www.python.org/downloads/
    echo        安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

echo [信息] 当前 Python 版本：
python --version
echo.

echo [信息] 正在升级 pip...
python -m pip install --upgrade pip

echo.
echo [信息] 正在安装依赖（使用清华镜像加速）...
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

if errorlevel 1 (
    echo.
    echo [错误] 安装失败，请检查网络后重试。
    echo        也可以手动执行：
    echo        python -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo.
echo ========================================
echo   安装完成！双击 main.py 或运行：
echo   python main.py
echo ========================================
pause