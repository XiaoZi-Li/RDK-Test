# -*- coding: utf-8 -*-
"""session.py - 板端会话管理

统一封装"真实板端"与"内置演示"两种数据源：
  - 在线模式: 底层为 ApiClient，经 StatusPoller 线程周期轮询
  - 演示模式: 底层为 DemoBoard，经 QTimer 周期生成模拟数据

对外发出统一信号：
  statusUpdated(object)      解析后的 SystemStatus 数据模型
  avoidUpdated(object)       解析后的 AvoidStatus 数据模型
  connectionChanged(bool,str) 连接状态与提示消息

页面与控件只依赖 BoardSession，无需感知底层数据源。
"""

from PySide6.QtCore import QObject, QTimer, Signal

from ..config import ConsoleConfig
from ..core.models import SystemStatus
from ..core.simulator import DemoBoard, parse_avoid, parse_status
from ..core.workers import StatusPoller, run_async
from ..net.api_client import ApiClient


class BoardSession(QObject):
    """板端会话：数据源选择、轮询调度与统一信号分发"""

    statusUpdated = Signal(object)          # SystemStatus
    avoidUpdated = Signal(object)           # AvoidStatus
    connectionChanged = Signal(bool, str)   # (是否在线, 消息)

    def __init__(self, config: ConsoleConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._backend = None        # ApiClient 或 DemoBoard（惰性创建）
        self._poller = None         # 在线模式的轮询线程
        self._demo_timer = None     # 演示模式的定时器
        self._online = False        # 当前连接状态

    # ------------------------------------------------------------------
    # 数据源
    # ------------------------------------------------------------------
    @property
    def backend(self):
        """当前数据源（首次访问时创建）"""
        if self._backend is None:
            if self.config.demo_mode:
                self._backend = DemoBoard(self.config.board_host)
            else:
                self._backend = ApiClient(self.config.base_url,
                                          self.config.request_timeout)
        return self._backend

    @property
    def online(self) -> bool:
        """当前是否处于在线状态"""
        return self._online

    # ------------------------------------------------------------------
    # 会话生命周期
    # ------------------------------------------------------------------
    def start(self):
        """按当前配置启动轮询"""
        self.stop()
        if self.config.demo_mode:
            self._start_demo_mode()
        else:
            self._start_live_mode()

    def stop(self):
        """停止轮询并释放线程资源"""
        if self._poller is not None:
            self._poller.stop()
            self._poller.wait(2000)
            self._poller = None
        if self._demo_timer is not None:
            self._demo_timer.stop()
            self._demo_timer = None
        # 切换模式后重建数据源
        self._backend = None

    def restart_with_config(self, config: ConsoleConfig):
        """应用新配置并重启会话"""
        self.config = config
        self.start()

    # ------------------------------------------------------------------
    # 在线模式
    # ------------------------------------------------------------------
    def _start_live_mode(self):
        self._poller = StatusPoller(self.backend, self.config.poll_interval)
        self._poller.statusReady.connect(self._on_status_raw)
        self._poller.avoidReady.connect(self._on_avoid_raw)
        self._poller.pollFailed.connect(
            lambda msg: self._set_online(False, msg))
        self._poller.pollRecovered.connect(
            lambda: self._set_online(True, "板端连接正常"))
        self._poller.start()
        self._set_online(False, "正在连接板端...")

    # ------------------------------------------------------------------
    # 演示模式
    # ------------------------------------------------------------------
    def _start_demo_mode(self):
        interval_ms = int(min(self.config.poll_interval, 2.0) * 1000)
        self._demo_timer = QTimer(self)
        self._demo_timer.timeout.connect(self._poll_demo_once)
        self._demo_timer.start(interval_ms)
        self._poll_demo_once()
        self._set_online(True, "演示模式（内置模拟数据源）")

    def _poll_demo_once(self):
        """演示模式单次轮询：直接在界面线程执行（模拟器无 I/O 开销）"""
        try:
            self._on_status_raw(self.backend.get_status())
            self._on_avoid_raw(self.backend.get_avoid_status())
        except Exception:            # noqa: BLE001 - 模拟器不应失败
            pass

    # ------------------------------------------------------------------
    # 信号分发
    # ------------------------------------------------------------------
    def _on_status_raw(self, data: dict):
        """原始状态数据 → 数据模型 → 广播"""
        status = parse_status(data)
        self.statusUpdated.emit(status)

    def _on_avoid_raw(self, data: dict):
        """原始避障数据 → 数据模型 → 广播"""
        self.avoidUpdated.emit(parse_avoid(data))

    def _set_online(self, online: bool, message: str):
        if online != self._online:
            self._online = online
        self.connectionChanged.emit(online, message)

    # ------------------------------------------------------------------
    # 异步操作入口（页面统一调用）
    # ------------------------------------------------------------------
    def async_send_action(self, action: str, on_done=None, on_error=None):
        """后台发送离散动作指令"""
        run_async(lambda: self.backend.send_action(action), on_done, on_error)

    def async_send_move(self, forward: float, turn: float,
                        on_done=None, on_error=None):
        """后台发送连续遥控指令"""
        run_async(lambda: self.backend.send_move(forward, turn, "remote"),
                  on_done, on_error)

    def async_chat(self, text: str, speak: bool, on_done=None, on_error=None):
        """后台发送大模型对话请求"""
        run_async(lambda: self.backend.chat(text, speak), on_done, on_error)

    def async_get_log(self, log_key: str, on_done=None, on_error=None):
        """后台拉取日志"""
        run_async(lambda: self.backend.get_log(log_key), on_done, on_error)

    def async_sys_command(self, command: str, on_done=None, on_error=None):
        """后台执行系统级命令 start/stop/restart"""
        run_async(lambda: self.backend.sys_command(command), on_done, on_error)

    def async_restart_stereo(self, on_done=None, on_error=None):
        """后台重启双目深度链路"""
        run_async(lambda: self.backend.restart_stereo(), on_done, on_error)

    def async_restart_robot(self, on_done=None, on_error=None):
        """后台重启运动中枢"""
        run_async(lambda: self.backend.restart_robot(), on_done, on_error)

    def async_set_avoid_mode(self, mode: str, on_done=None, on_error=None):
        """后台切换避障模式 on/off"""
        run_async(lambda: self.backend.set_avoid_mode(mode), on_done, on_error)
