# -*- coding: utf-8 -*-
"""video_page.py - 视频监控页（视频墙）

以网格形式同时展示全部板端视频流：
  右眼 / 左眼 / 深度伪彩图 / YOLO 检测 / 手势识别
支持"全屏单路"切换：双击任一路画面放大为单路大画面，
再次双击恢复网格布局。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGridLayout, QLabel, QVBoxLayout, QWidget)

from ...config import ConsoleConfig
from ...core.session import BoardSession
from ..video_widget import VideoWidget


class VideoPage(QWidget):
    """视频监控页（多路视频墙）"""

    def __init__(self, session: BoardSession, config: ConsoleConfig,
                 parent=None):
        super().__init__(parent)
        self._session = session
        self._config = config
        self._widgets = []            # VideoWidget 列表
        self._expanded = None         # 当前放大的单路控件
        self._started = False

        self._build_ui()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        tip = QLabel("双击任一路画面可放大单路查看，再次双击恢复网格布局；"
                     "画面来源为板端 MJPEG 实时流。")
        tip.setStyleSheet("color: #7a8a9a; font-size: 12px;")
        root.addWidget(tip)

        self._grid = QGridLayout()
        self._grid.setSpacing(10)
        root.addLayout(self._grid, 1)

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------
    def start_streams(self):
        """按当前配置启动全部视频流（主窗口切换到本页时调用）"""
        self.stop_streams()
        host = self._config.board_host
        for index, (port, name, subpath) in enumerate(self._config.video_streams):
            widget = VideoWidget(name, port, subpath)
            widget.mouseDoubleClickEvent = (lambda _w=widget, _e=None: self._toggle_expand(_w))
            self._widgets.append(widget)
            widget.start(host, self._config.demo_mode, demo_index=index)
        self._relayout()
        self._started = True

    def stop_streams(self):
        """停止全部视频流（离开本页时调用以节省带宽）"""
        for widget in self._widgets:
            widget.stop()
            widget.setParent(None)
            widget.deleteLater()
        self._widgets.clear()
        self._expanded = None
        self._started = False

    def is_started(self) -> bool:
        return self._started

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------
    def _relayout(self):
        """按当前模式（网格/单路放大）重新排布"""
        # 清空现有布局项
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                self._grid.removeWidget(widget)

        if self._expanded is not None:
            self._grid.addWidget(self._expanded, 0, 0, 1, 2)
            for widget in self._widgets:
                if widget is not self._expanded:
                    widget.hide()
            self._expanded.show()
        else:
            columns = 3
            for index, widget in enumerate(self._widgets):
                row = index // columns
                col = index % columns
                self._grid.addWidget(widget, row, col)
                widget.show()
        for col in range(3):
            self._grid.setColumnStretch(col, 1)
        for row in range(3):
            self._grid.setRowStretch(row, 1)

    def _toggle_expand(self, widget: VideoWidget):
        """双击切换单路放大 / 恢复网格"""
        if self._expanded is widget:
            self._expanded = None
        else:
            self._expanded = widget
        self._relayout()
