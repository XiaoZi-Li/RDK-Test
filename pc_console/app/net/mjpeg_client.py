# -*- coding: utf-8 -*-
"""mjpeg_client.py - MJPEG 视频流接收线程

以 HTTP multipart/x-mixed-replace 方式持续读取板端 MJPEG 视频流，
在独立线程中按 JPEG 帧边界（FFD8 ... FFD9）拆帧，
通过信号将 QImage 图像帧投递给界面线程渲染。

设计要点：
  - 断线自动重连（带退避），网络恢复后无需人工干预
  - 帧解析在读取线程内完成，界面线程只做贴图，保证流畅
  - 提供 fps 统计，便于诊断带宽与延迟
"""

import time
import urllib.request
import urllib.error

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

# JPEG 帧边界标记
_JPEG_SOI = b"\xff\xd8"   # 帧头 (Start Of Image)
_JPEG_EOI = b"\xff\xd9"   # 帧尾 (End Of Image)

# 每次从 socket 读取的块大小（字节）
_CHUNK_SIZE = 4096


class MjpegStreamWorker(QThread):
    """单路 MJPEG 视频流接收工作线程

    信号:
        frameReady(QImage)  解析出一帧图像（界面线程接收）
        stateChanged(str)   连接状态变化: "connecting"/"streaming"/"reconnecting"/"stopped"
    """

    frameReady = Signal(QImage)
    stateChanged = Signal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._running = False
        # 重连退避参数：首次 1s，每次翻倍，上限 10s
        self._retry_min = 1.0
        self._retry_max = 10.0
        # 帧率统计
        self._frame_times = []

    # ------------------------------------------------------------------
    # 线程控制
    # ------------------------------------------------------------------
    def set_url(self, url: str):
        """更新视频流地址（下次重连生效）"""
        self._url = url

    def stop(self):
        """请求线程退出（立即返回，不等待）"""
        self._running = False

    # ------------------------------------------------------------------
    # 帧率统计
    # ------------------------------------------------------------------
    def fps(self) -> float:
        """最近 2 秒内的平均帧率"""
        now = time.monotonic()
        self._frame_times = [t for t in self._frame_times if now - t <= 2.0]
        if len(self._frame_times) < 2:
            return 0.0
        return (len(self._frame_times) - 1) / 2.0

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def run(self):
        self._running = True
        retry_delay = self._retry_min

        while self._running:
            self.stateChanged.emit("connecting")
            try:
                self._stream_loop()
                # 正常返回说明 stop() 被调用
                break
            except Exception as e:
                if not self._running:
                    break
                # 读取失败（断流/板端重启）→ 退避重连
                self.stateChanged.emit("reconnecting")
                self._sleep_interruptible(retry_delay)
                retry_delay = min(retry_delay * 2, self._retry_max)

        self.stateChanged.emit("stopped")

    def _stream_loop(self):
        """建立连接并持续读流，直到 stop() 或连接中断"""
        req = urllib.request.Request(self._url, headers={"Accept": "multipart/x-mixed-replace"})
        resp = urllib.request.urlopen(req, timeout=8.0)  # 连接超时
        self.stateChanged.emit("streaming")

        buf = b""
        while self._running:
            chunk = resp.read(_CHUNK_SIZE)
            if not chunk:
                # 板端关闭连接
                raise ConnectionError("流被对端关闭")
            buf += chunk

            # 循环提取缓冲区内所有完整帧（可能一次读到多帧）
            while True:
                start = buf.find(_JPEG_SOI)
                if start < 0:
                    # 无帧头：保留末尾 1 字节防止标记跨块
                    buf = buf[-1:]
                    break
                end = buf.find(_JPEG_EOI, start + 2)
                if end < 0:
                    # 帧未读完：丢弃帧头之前的垃圾数据，等待后续块
                    buf = buf[start:]
                    break
                frame_data = buf[start:end + 2]
                buf = buf[end + 2:]

                image = self._decode_frame(frame_data)
                if image is not None and not image.isNull():
                    self._frame_times.append(time.monotonic())
                    self.frameReady.emit(image)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_frame(data: bytes):
        """将 JPEG 字节流解码为 QImage；解码失败返回 None"""
        image = QImage()
        if image.loadFromData(data, "JPEG"):
            return image
        return None

    def _sleep_interruptible(self, seconds: float):
        """可中断的休眠（stop() 时立即退出）"""
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            self.msleep(100)
