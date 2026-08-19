# -*- coding: utf-8 -*-
"""video_widget.py - 单路视频画面控件

封装一路 MJPEG 视频画面的接收与展示：
  - 在线模式: 内部持有 MjpegStreamWorker 线程拉流
  - 演示模式: 内部 QTimer 周期调用 DemoFrameFactory 合成画面

控件提供帧率统计与连接状态显示，画面按比例缩放自适应控件尺寸。
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)

from ..core.simulator import DemoFrameFactory
from ..net.mjpeg_client import MjpegStreamWorker

# 演示模式帧生成周期（毫秒），约 15fps
_DEMO_FRAME_MS = 66


class VideoWidget(QFrame):
    """单路视频画面控件

    信号:
        stateChanged(str)  本路视频连接状态变化
    """

    stateChanged = Signal(str)

    def __init__(self, name: str, port: int, subpath: str, parent=None):
        super().__init__(parent)
        self.setObjectName("videoCard")
        self._name = name
        self._port = port
        self._subpath = subpath

        # 流工作对象
        self._worker = None           # 在线模式拉流线程
        self._demo_timer = None       # 演示模式帧定时器
        self._demo_factory = None     # 演示帧合成器
        self._demo_index = 0          # 演示画面路号

        # 帧率刷新定时器（每秒更新一次表头）
        self._fps_timer = QTimer(self)
        self._fps_timer.timeout.connect(self._refresh_fps)
        self._last_pixmap = None

        self._build_ui()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(4)

        # 表头：名称 + 端口 + 状态
        header = QHBoxLayout()
        self._title_label = QLabel(f"{self._name}")
        self._title_label.setObjectName("accentText")
        self._state_label = QLabel("未连接")
        self._state_label.setObjectName("dimText")
        header.addWidget(self._title_label)
        header.addStretch(1)
        header.addWidget(self._state_label)
        layout.addLayout(header)

        # 画面区域
        self._view = QLabel()
        self._view.setObjectName("videoPlaceholder")
        self._view.setAlignment(Qt.AlignCenter)
        self._view.setMinimumSize(240, 135)
        self._view.setStyleSheet("background: #0d1117; border-radius: 4px;")
        layout.addWidget(self._view, 1)

    # ------------------------------------------------------------------
    # 启停控制
    # ------------------------------------------------------------------
    def start(self, board_host: str, demo: bool, demo_index: int = 0):
        """启动本路视频

        :param board_host: 板端 IP（在线模式）
        :param demo:       是否演示模式
        :param demo_index: 演示画面路号 0右眼/1左眼/2深度/3YOLO/4手势
        """
        self.stop()
        if demo:
            self._start_demo(demo_index)
        else:
            self._start_live(board_host)
        self._fps_timer.start(1000)

    def stop(self):
        """停止本路视频并释放资源"""
        self._fps_timer.stop()
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(2000)
            self._worker = None
        if self._demo_timer is not None:
            self._demo_timer.stop()
            self._demo_timer = None
        self._demo_factory = None
        self._set_state("未连接")

    # ------------------------------------------------------------------
    # 在线模式
    # ------------------------------------------------------------------
    def _start_live(self, board_host: str):
        url = f"http://{board_host}:{self._port}{self._subpath}"
        self._worker = MjpegStreamWorker(url)
        self._worker.frameReady.connect(self._show_frame)
        self._worker.stateChanged.connect(self._on_worker_state)
        self._worker.start()

    def _on_worker_state(self, state: str):
        """拉流线程状态回调: connecting/streaming/reconnecting/stopped"""
        names = {
            "connecting": "连接中...",
            "streaming": "接收中",
            "reconnecting": "重连中...",
            "stopped": "未连接",
        }
        self._set_state(names.get(state, state))
        self.stateChanged.emit(state)

    # ------------------------------------------------------------------
    # 演示模式
    # ------------------------------------------------------------------
    def _start_demo(self, demo_index: int):
        self._demo_index = demo_index
        self._demo_factory = DemoFrameFactory()
        self._demo_timer = QTimer(self)
        self._demo_timer.timeout.connect(self._make_demo_frame)
        self._demo_timer.start(_DEMO_FRAME_MS)
        self._set_state("演示中")
        self.stateChanged.emit("streaming")

    def _make_demo_frame(self):
        """生成一帧演示画面"""
        if self._demo_factory is None:
            return
        image = self._demo_factory.make_frame(self._demo_index)
        self._show_frame(image)

    # ------------------------------------------------------------------
    # 画面渲染
    # ------------------------------------------------------------------
    def _show_frame(self, image: QImage):
        """将一帧图像缩放后显示"""
        if image is None or image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        self._last_pixmap = pixmap
        self._fit_pixmap()

    def _fit_pixmap(self):
        """按控件尺寸等比例缩放画面"""
        if self._last_pixmap is None:
            return
        scaled = self._last_pixmap.scaled(
            self._view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._view.setPixmap(scaled)

    def _refresh_fps(self):
        """每秒刷新一次帧率显示（在线模式取自拉流线程统计）"""
        fps = self._worker.fps() if self._worker is not None else 15.0
        if self._demo_timer is not None:
            text = "演示中"
        else:
            text = self._state_label.text().split(" · ")[0]
            text = f"{text} · {fps:.1f}fps"
        self._state_label.setText(text)

    def _set_state(self, text: str):
        """更新表头状态文字与配色"""
        self._state_label.setText(text)
        if text in ("接收中", "演示中"):
            self._state_label.setProperty("class", "ok")
            self._state_label.setStyleSheet("color: #3fb950;")
        elif text in ("未连接",):
            self._state_label.setStyleSheet("color: #556070;")
        else:
            self._state_label.setStyleSheet("color: #ffaa00;")

    # ------------------------------------------------------------------
    # 窗口尺寸变化时保持画面比例
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_pixmap()
