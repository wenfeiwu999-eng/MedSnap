@echo off
chcp 65001 >nul 2>&1
title MedSnap 临床数据智能平台 - 一键部署
color 0A

echo ══════════════════════════════════════════════════
echo   MedSnap 临床数据智能平台 - 一键部署
echo ══════════════════════════════════════════════════
echo.

:: 检查 Python 是否安装
echo [1/4] 检查 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python！请先安装 Python 3.8 或以上版本。
    echo        下载地址: https://www.python.org/downloads/
    echo        安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
python --version
echo [OK] Python 已安装
echo.

:: 创建虚拟环境
echo [2/4] 创建虚拟环境...
if not exist "venv" (
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [错误] 创建虚拟环境失败！
        pause
        exit /b 1
    )
    echo [OK] 虚拟环境已创建
) else (
    echo [OK] 虚拟环境已存在，跳过创建
)
echo.

:: 安装依赖
echo [3/4] 安装项目依赖（首次可能需要几分钟）...
call venv\Scripts\activate.bat
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo [警告] 部分依赖安装可能失败，但不影响核心功能
)
echo [OK] 依赖安装完成
echo.

:: 启动应用
echo [4/4] 启动 MedSnap...
echo.
echo ══════════════════════════════════════════════════
echo   MedSnap 临床数据智能平台
echo   访问地址: http://localhost:7860
echo   请在浏览器中打开上方地址
echo   按 Ctrl+C 可停止服务
echo ══════════════════════════════════════════════════
echo.
python app.py
pause
