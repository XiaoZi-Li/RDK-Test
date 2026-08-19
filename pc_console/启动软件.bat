@echo off
rem 机器狗远程监控与运动控制上位机软件 V1.0 - Windows 一键启动脚本
rem 首次运行自动创建虚拟环境并安装依赖

cd /d %~dp0

if not exist .venv (
    echo [首次运行] 正在创建虚拟环境...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

echo 正在启动软件...
python main.py %*

pause
