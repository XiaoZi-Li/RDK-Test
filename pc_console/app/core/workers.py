# -*- coding: utf-8 -*-
"""workers.py - 后台任务与状态轮询

提供两类并发设施：
  1. AsyncTask / run_async : 通用后台任务（一次性请求，
     如发送动作指令、拉取日志、系统命令、对话请求），
     基于全局 QThreadPool，通过信号把结果投递回界面线程。
  2. StatusPoller(QThread) : 周期性轮询板端状态与避障状态，
     网络异常时上报错误信号，恢复后上报恢复信号。
"""

import time

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal


# ----------------------------------------------------------------------
# 通用后台任务
# ----------------------------------------------------------------------
class _TaskSignals(QObject):
    """任务结果信号载体（QRunnable 本身不是 QObject，无法持信号）"""
    done = Signal(object)     # 携带任务返回值
    failed = Signal(str)      # 携带异常消息


class AsyncTask(QRunnable):
    """在全局线程池中执行一个可调用对象

    :param fn:        无参可调用对象（用 lambda/闭包携带参数）
    :param on_done:   成功回调 fn(result)，在界面线程执行
    :param on_error:  失败回调 fn(error_message)，在界面线程执行
    """

    def __init__(self, fn, on_done=None, on_error=None):
        super().__init__()
        self._fn = fn
        self.signals = _TaskSignals()
        if on_done is not None:
            self.signals.done.connect(on_done)
        if on_error is not None:
            self.signals.failed.connect(on_error)
        self.setAutoDelete(True)

    def run(self):
        try:
            result = self._fn()
        except Exception as e:          # noqa: BLE001 - 统一上报给界面
            self.signals.failed.emit(str(e))
        else:
            self.signals.done.emit(result)


def run_async(fn, on_done=None, on_error=None):
    """把任务提交到全局线程池执行（界面线程立即返回）"""
    QThreadPool.globalInstance().start(AsyncTask(fn, on_done, on_error))


# ----------------------------------------------------------------------
# 状态轮询线程
# ----------------------------------------------------------------------
class StatusPoller(QThread):
    """板端状态轮询线程

    每个周期依次执行：
      backend.get_status()       → statusReady(dict)
      backend.get_avoid_status() → avoidReady(dict)
    任一步骤失败即上报 pollFailed(错误消息)；
    由失败恢复为成功时上报 pollRecovered()。

    休眠可被 stop() 立即打断，保证程序退出干净。
    """

    statusReady = Signal(dict)
    avoidReady = Signal(dict)
    pollFailed = Signal(str)
    pollRecovered = Signal()

    def __init__(self, backend, interval: float, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._interval = max(0.5, float(interval))
        self._running = False

    # ------------------------------------------------------------------
    def set_interval(self, interval: float):
        """动态调整轮询间隔（下一个周期生效）"""
        if interval >= 0.5:
            self._interval = float(interval)

    def stop(self):
        """请求线程退出"""
        self._running = False

    # ------------------------------------------------------------------
    def run(self):
        self._running = True
        was_failed = False

        while self._running:
            try:
                status = self._backend.get_status()
                avoid = self._backend.get_avoid_status()
            except Exception as e:      # noqa: BLE001
                if not was_failed:
                    self.pollFailed.emit(str(e))
                was_failed = True
            else:
                self.statusReady.emit(status)
                self.avoidReady.emit(avoid)
                if was_failed:
                    self.pollRecovered.emit()
                    was_failed = False
            self._sleep_until_next_cycle()

    def _sleep_until_next_cycle(self):
        """可中断休眠：每 100ms 检查一次退出标志"""
        deadline = time.monotonic() + self._interval
        while self._running and time.monotonic() < deadline:
            self.msleep(100)
