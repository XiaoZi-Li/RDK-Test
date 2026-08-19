#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""main.py - 机器狗远程监控与运动控制上位机软件 程序入口

启动流程:
  1. 解析命令行参数（--demo 演示模式 / --host 板端IP / --port API端口）
  2. 加载磁盘配置文件（~/.puppy_console.json）
  3. 创建应用与主窗口，启动板端会话轮询

用法:
  python main.py                      # 按配置文件连接
  python main.py --demo               # 演示模式（内置模拟数据源）
  python main.py --host 192.168.1.10  # 指定板端 IP
"""

import argparse
import sys

from PySide6.QtWidgets import QApplication

from app.config import ConsoleConfig
from app.ui.main_window import MainWindow
from app.version import APP_NAME, APP_VERSION


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--host", default=None,
                        help="板端 IP 地址（覆盖配置文件）")
    parser.add_argument("--port", type=int, default=None,
                        help="板端 API 端口（覆盖配置文件）")
    parser.add_argument("--demo", action="store_true",
                        help="演示模式：使用内置模拟数据源，无需连接真实板端")
    return parser.parse_args()


def main() -> int:
    """程序入口"""
    args = parse_args()

    # 加载配置并应用命令行覆盖
    config = ConsoleConfig()
    config.load()
    if args.host:
        config.board_host = args.host
    if args.port:
        config.api_port = args.port
    if args.demo:
        config.demo_mode = True

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("PuppyPi")

    window = MainWindow(config)
    window.show()
    window.start()          # 窗口显示后启动会话轮询

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
