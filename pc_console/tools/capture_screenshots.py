#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""capture_screenshots.py - 用户手册界面截图采集脚本

在演示模式下启动软件，自动遍历全部功能页面并保存高清截图，
用于软件著作权申报材料中的《用户操作手册》配图。

脚本会模拟真实操作：
  - 对话页自动发送一条指令并等待演示回复
  - 日志页自动选中第一个日志源加载内容

用法:
  QT_QPA_PLATFORM=offscreen python3 tools/capture_screenshots.py [输出目录]
"""

import os
import sys

# 保证可以从项目根目录导入 app 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.config import ConsoleConfig
from app.ui.main_window import MainWindow

# 每页截图前的渲染等待时间（毫秒）
SETTLE_MS = 2600


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "screenshots"
    os.makedirs(out_dir, exist_ok=True)

    config = ConsoleConfig()
    config.load()
    config.demo_mode = True

    app = QApplication(sys.argv)
    window = MainWindow(config)
    window.resize(1280, 800)
    window.show()
    window.start()

    state = {"step": 0}

    def save(filename):
        """保存当前窗口截图"""
        out_path = os.path.join(out_dir, filename)
        pixmap = window.grab()
        pixmap.save(out_path)
        print(f"已保存: {out_path}")

    def go_to(page_index: int):
        """切换左侧导航到指定页面"""
        window._nav.setCurrentRow(page_index)

    # ------------------------------------------------------------------
    # 截图步骤编排（每步固定间隔推进）
    # ------------------------------------------------------------------
    def step_overview():
        go_to(0)
        QTimer.singleShot(SETTLE_MS, lambda: (save("01_overview.png"), step_video()))

    def step_video():
        go_to(1)
        QTimer.singleShot(SETTLE_MS + 800, lambda: (save("02_video.png"), step_motion()))

    def step_motion():
        go_to(2)
        page = window._pages["motion"]
        page._fwd_slider.setValue(40)     # 模拟速度设定状态
        QTimer.singleShot(SETTLE_MS, lambda: (save("03_motion.png"), step_chat()))

    def step_chat():
        go_to(3)
        page = window._pages["chat"]
        page._input.setText("先坐下再站起来")
        QTimer.singleShot(400, page._send_message)
        QTimer.singleShot(SETTLE_MS + 1600,
                          lambda: (save("04_chat.png"), step_avoid()))

    def step_avoid():
        go_to(4)
        QTimer.singleShot(SETTLE_MS, lambda: (save("05_avoid.png"), step_log()))

    def step_log():
        go_to(5)
        page = window._pages["log"]
        page._source_list.setCurrentRow(0)   # 选中"运动仲裁器"日志
        QTimer.singleShot(SETTLE_MS + 600, lambda: (save("06_log.png"), step_system()))

    def step_system():
        go_to(6)
        QTimer.singleShot(SETTLE_MS, lambda: (save("07_system.png"), finish()))

    def finish():
        window.shutdown()
        app.quit()
        print("全部截图完成")

    # 首帧渲染稳定后开始
    QTimer.singleShot(1500, step_overview)
    app.exec()


if __name__ == "__main__":
    main()
