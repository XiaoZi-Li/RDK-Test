# -*- coding: utf-8 -*-
"""motion_page.py - 运动控制页

提供两类运动控制方式：
  1. 离散动作控制: 8 个动作按钮（前进/后退/左转/右转/行走
     支持长按持续运动，按住期间以心跳间隔重复下发指令，
     松开立即发送停止；坐下/站立/停止为单次触发）
  2. 连续遥控模式: 速度滑杆 + 连续发送开关，
     按 follow_control 协议以固定频率持续下发速度指令，
     停止发送后板端仲裁器自动超时停车

支持键盘操作: W前进 S后退 A左转 D右转 空格急停。
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from ...config import ConsoleConfig
from ...core.models import DISCRETE_ACTIONS
from ...core.session import BoardSession
from ..widgets import NoticeLabel, make_card

# 长按按钮的动作名（支持持续运动）
_HOLD_ACTIONS = {"forward", "backward", "turn_left", "turn_right", "walk"}

# 键盘按键 → 动作映射
_KEY_ACTIONS = {
    Qt.Key_W: "forward",
    Qt.Key_S: "backward",
    Qt.Key_A: "turn_left",
    Qt.Key_D: "turn_right",
}


class MotionPage(QWidget):
    """运动控制页"""

    def __init__(self, session: BoardSession, config: ConsoleConfig,
                 parent=None):
        super().__init__(parent)
        self._session = session
        self._config = config

        self._hold_buttons = {}       # 动作名 -> QPushButton
        self._hold_timer = None       # 长按心跳定时器
        self._holding_action = None   # 当前长按中的动作
        self._active_keys = {}        # 键盘长按追踪: 按键 -> 动作

        self._remote_timer = None     # 连续遥控发送定时器
        self._notice = NoticeLabel()

        self._build_ui()
        self.setFocusPolicy(Qt.StrongFocus)

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        content = QHBoxLayout()
        content.setSpacing(12)
        root.addLayout(content, 1)

        # ---- 左: 离散动作控制 ----
        card_actions, body_actions = make_card("离散动作控制", stretch_last=False)
        content.addWidget(card_actions, 3)

        grid = QGridLayout()
        grid.setSpacing(8)
        body_actions.addLayout(grid)

        # 前进/后退/左转/右转/行走 为可长按按钮
        display_names = {
            "forward": "前进 (W)", "backward": "后退 (S)",
            "turn_left": "左转 (A)", "turn_right": "右转 (D)",
            "walk": "行走", "sit": "坐下", "stand": "站立", "stop": "停止 (空格)",
        }
        positions = {
            "forward": (0, 0), "backward": (0, 1),
            "turn_left": (0, 2), "turn_right": (0, 3),
            "walk": (1, 0), "sit": (1, 1), "stand": (1, 2), "stop": (1, 3),
        }
        for action, _cn_name, _holdable in DISCRETE_ACTIONS:
            button = QPushButton(display_names.get(action, action))
            button.setObjectName("motionPad")
            if action == "stop":
                button.setStyleSheet(
                    "QPushButton#motionPad { color:#f85149; border-color:#5a2a2a; }"
                    "QPushButton#motionPad:hover { background:#3a1a1a; }")
            if action in _HOLD_ACTIONS:
                button.pressed.connect(
                    lambda a=action: self._press_action(a))
                button.released.connect(lambda: self._release_action())
            else:
                button.clicked.connect(
                    lambda _checked=False, a=action: self._send_action_once(a))
            position = positions.get(action)
            if position:
                grid.addWidget(button, position[0], position[1])
            self._hold_buttons[action] = button

        hint = QLabel("方向与行走按钮支持长按：按住持续运动，松开即停（0.2s 心跳保持仲裁通道）。")
        hint.setStyleSheet("color: #7a8a9a; font-size: 12px;")
        hint.setWordWrap(True)
        body_actions.addWidget(hint)

        body_actions.addWidget(self._notice)

        # ---- 右: 连续遥控模式 ----
        card_remote, body_remote = make_card("连续遥控模式", stretch_last=True)
        content.addWidget(card_remote, 2)

        group_speed = QGroupBox("速度设定")
        group_speed.setStyleSheet("QGroupBox { color:#8b949e; border:1px solid #30363d;"
                                  "border-radius:6px; margin-top:8px; padding-top:6px; }")
        speed_layout = QHBoxLayout()
        speed_layout.setSpacing(16)

        # 前进/后退速度（纵向滑杆，上=前进）
        fwd_layout = QVBoxLayout()
        fwd_label = QLabel("前进 / 后退")
        fwd_label.setAlignment(Qt.AlignCenter)
        fwd_label.setStyleSheet("color: #8b949e;")
        self._fwd_slider = QSlider(Qt.Vertical)
        self._fwd_slider.setRange(-100, 100)
        self._fwd_slider.setValue(0)
        self._fwd_slider.setInvertedAppearance(True)
        self._fwd_slider.setTickPosition(QSlider.TicksBothSides)
        self._fwd_slider.valueChanged.connect(self._on_slider_changed)
        fwd_layout.addWidget(fwd_label)
        fwd_layout.addWidget(self._fwd_slider, 1)

        # 转向速度（横向滑杆，左=左转）
        turn_layout = QVBoxLayout()
        turn_label = QLabel("左转 / 右转")
        turn_label.setAlignment(Qt.AlignCenter)
        turn_label.setStyleSheet("color: #8b949e;")
        self._turn_slider = QSlider(Qt.Horizontal)
        self._turn_slider.setRange(-100, 100)
        self._turn_slider.setValue(0)
        self._turn_slider.valueChanged.connect(self._on_slider_changed)
        turn_layout.addWidget(turn_label)
        turn_layout.addWidget(self._turn_slider)

        speed_layout.addLayout(fwd_layout)
        speed_layout.addLayout(turn_layout)
        group_speed.setLayout(speed_layout)
        body_remote.addWidget(group_speed)

        # 速度读数
        self._speed_label = QLabel("当前速度: 前进 0.00 | 转向 0.00")
        self._speed_label.setObjectName("accentText")
        body_remote.addWidget(self._speed_label)

        # 遥控开关
        btn_row = QHBoxLayout()
        self._btn_remote = QPushButton("开始遥控")
        self._btn_remote.setObjectName("success")
        self._btn_remote.setCheckable(True)
        self._btn_remote.toggled.connect(self._on_remote_toggled)
        btn_zero = QPushButton("速度归零")
        btn_zero.clicked.connect(self._zero_sliders)
        btn_row.addWidget(self._btn_remote)
        btn_row.addWidget(btn_zero)
        body_remote.addLayout(btn_row)

        remote_hint = QLabel("开始遥控后按固定频率持续下发 follow_control 指令；"
                             "关闭遥控或速度归零后机器狗自动停止。")
        remote_hint.setStyleSheet("color: #7a8a9a; font-size: 12px;")
        remote_hint.setWordWrap(True)
        body_remote.addWidget(remote_hint)
        body_remote.addStretch(1)

    # ------------------------------------------------------------------
    # 离散动作控制
    # ------------------------------------------------------------------
    def _send_action_once(self, action: str):
        """单次发送动作指令"""
        self._session.async_send_action(
            action,
            on_done=lambda res: self._notice.show_success(
                res.get("message", f"已发送: {action}")),
            on_error=lambda err: self._notice.show_error(f"发送失败: {err}"))

    def _press_action(self, action: str):
        """长按开始：立即发送 + 周期心跳"""
        self._release_action(silent=True)   # 防卡键：先清掉上一个
        self._holding_action = action
        self._session.async_send_action(action)
        self._notice.show_info(f"按住中: {action}（松开停止）")
        if self._hold_timer is None:
            self._hold_timer = QTimer(self)
            self._hold_timer.timeout.connect(self._heartbeat)
        self._hold_timer.start(self._config.heartbeat_ms)

    def _release_action(self, silent: bool = False):
        """长按结束：停心跳 + 发送停止"""
        if self._hold_timer is not None:
            self._hold_timer.stop()
        if self._holding_action is not None:
            self._holding_action = None
            self._session.async_send_action("stop")
            if not silent:
                self._notice.show_success("已停止")

    def _heartbeat(self):
        """长按心跳：持续下发当前动作保持仲裁通道活跃"""
        if self._holding_action:
            self._session.async_send_action(self._holding_action)

    # ------------------------------------------------------------------
    # 连续遥控模式
    # ------------------------------------------------------------------
    def _on_slider_changed(self):
        """滑杆变化：更新速度读数"""
        fwd = self._fwd_slider.value() / 100.0
        turn = self._turn_slider.value() / 100.0
        self._speed_label.setText(f"当前速度: 前进 {fwd:+.2f} | 转向 {turn:+.2f}")

    def _zero_sliders(self):
        """速度归零（滑杆回中）"""
        self._fwd_slider.setValue(0)
        self._turn_slider.setValue(0)
        if self._remote_timer is not None and self._remote_timer.isActive():
            # 归零后保持发送一轮零速指令以确保停车
            self._session.async_send_move(0.0, 0.0)

    def _on_remote_toggled(self, checked: bool):
        """开始/停止连续遥控"""
        if checked:
            self._btn_remote.setText("停止遥控")
            self._btn_remote.setObjectName("danger")
            interval_ms = int(1000 / max(1.0, self._config.move_rate_hz))
            if self._remote_timer is None:
                self._remote_timer = QTimer(self)
                self._remote_timer.timeout.connect(self._send_remote_frame)
            self._remote_timer.start(interval_ms)
            self._notice.show_info("连续遥控已开启")
        else:
            self._btn_remote.setText("开始遥控")
            self._btn_remote.setObjectName("success")
            if self._remote_timer is not None:
                self._remote_timer.stop()
            self._session.async_send_move(0.0, 0.0)   # 确保停车
            self._notice.show_success("连续遥控已停止")
        # 强制刷新样式
        self._btn_remote.style().unpolish(self._btn_remote)
        self._btn_remote.style().polish(self._btn_remote)

    def _send_remote_frame(self):
        """发送一帧遥控速度指令"""
        fwd = self._fwd_slider.value() / 100.0
        turn = self._turn_slider.value() / 100.0
        self._session.async_send_move(fwd, turn)

    # ------------------------------------------------------------------
    # 键盘控制
    # ------------------------------------------------------------------
    def keyPressEvent(self, event):
        """键盘长按: W/S/A/D 触发对应动作"""
        key = event.key()
        if key == Qt.Key_Space:
            self._release_action()
            self._send_action_once("stop")
            return
        action = _KEY_ACTIONS.get(key)
        if action and key not in self._active_keys:
            self._active_keys[key] = action
            self._press_action(action)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """键盘松开: 停止对应动作"""
        key = event.key()
        if key in self._active_keys:
            del self._active_keys[key]
            self._release_action()
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        """页面失焦兜底停车（防止长按状态卡住）"""
        self._active_keys.clear()
        self._release_action(silent=True)
        super().focusOutEvent(event)
