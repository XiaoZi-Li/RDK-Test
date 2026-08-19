# -*- coding: utf-8 -*-
"""avoid_page.py - 避障监测页

展示双目避障子系统的实时状态并提供模式切换：
  - 自动巡航开关（on=避障控车 / off=纯监测不控车）
  - 避障状态机阶段（巡航/停车/后退/转向躲避）
  - 左/中/右三区最近距离与近像素占比
  - 方位判定结果与 USB 语义检测融合结果

数据来源: BoardSession.avoidUpdated 信号（随状态轮询刷新）。
"""

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ...core.models import AvoidStatus
from ...core.session import BoardSession
from ..widgets import InfoRow, NoticeLabel, make_card


class AvoidPage(QWidget):
    """避障监测页"""

    def __init__(self, session: BoardSession, parent=None):
        super().__init__(parent)
        self._session = session
        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # ---- 模式控制卡 ----
        card_mode, body_mode = make_card("避障模式控制", stretch_last=False)
        root.addWidget(card_mode)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_on = QPushButton("开启自动巡航")
        btn_on.setObjectName("success")
        btn_on.clicked.connect(lambda: self._set_mode("on"))
        btn_off = QPushButton("关闭避障（纯监测）")
        btn_off.setObjectName("danger")
        btn_off.clicked.connect(lambda: self._set_mode("off"))
        btn_row.addWidget(btn_on)
        btn_row.addWidget(btn_off)
        btn_row.addStretch(1)
        body_mode.addLayout(btn_row)

        self._mode_label = QLabel("当前模式: 未知")
        self._mode_label.setObjectName("accentText")
        body_mode.addWidget(self._mode_label)

        self._notice = NoticeLabel()
        body_mode.addWidget(self._notice)

        mode_hint = QLabel(
            "开启后持续前进：左障碍自动右转，右障碍自动左转，正前障碍停车播报后"
            "退并向空旷侧转向，清空后续走；关闭后为纯监测模式，只显示判断结果不控车。")
        mode_hint.setStyleSheet("color: #7a8a9a; font-size: 12px;")
        mode_hint.setWordWrap(True)
        body_mode.addWidget(mode_hint)

        # ---- 实时状态卡 ----
        card_status, body_status = make_card("实时避障状态", stretch_last=False)
        root.addWidget(card_status)

        self._row_node = InfoRow("节点状态", "--")
        self._row_state = InfoRow("避障阶段", "--")
        self._row_decision = InfoRow("方位判定", "--")
        self._row_distance = InfoRow("三区距离", "--")
        self._row_ratio = InfoRow("近像素占比", "--")
        self._row_usb = InfoRow("USB 检测", "--")
        for row in (self._row_node, self._row_state, self._row_decision,
                    self._row_distance, self._row_ratio, self._row_usb):
            body_status.addWidget(row)

        body_status.addStretch(1)
        root.addStretch(1)

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _connect_signals(self):
        self._session.avoidUpdated.connect(self._on_avoid_updated)

    # ------------------------------------------------------------------
    # 状态刷新
    # ------------------------------------------------------------------
    def _on_avoid_updated(self, status: AvoidStatus):
        """避障状态到达：刷新各信息行"""
        # 节点在线状态
        if status.node_online:
            self._row_node.set_value("在线", "#3fb950")
        else:
            self._row_node.set_value("离线（先启动全部组件）", "#f85149")
            self._mode_label.setText("当前模式: 节点离线")
            self._mode_label.setStyleSheet("color: #f85149; font-weight: bold;")
            return

        # 模式
        if status.avoid_mode:
            self._mode_label.setText("当前模式: 自动巡航中（避障控车）")
            self._mode_label.setStyleSheet("color: #3fb950; font-weight: bold;")
        else:
            self._mode_label.setText("当前模式: 纯监测（不控车）")
            self._mode_label.setStyleSheet("color: #8b949e; font-weight: bold;")

        # 状态机阶段
        self._row_state.set_value(status.state_text(), "#58a6ff")

        # 方位判定
        decision = status.decision_text()
        if decision:
            color = "#f85149" if status.decision != "sensor_error" else "#ffaa00"
            self._row_decision.set_value(decision, color)
        else:
            self._row_decision.set_value("无障碍", "#3fb950")

        # 三区距离
        distance_text = status.distance_text()
        self._row_distance.set_value(distance_text or "--")

        # 近像素占比
        ratio_text = status.ratio_text()
        self._row_ratio.set_value(ratio_text or "--")

        # USB 语义检测
        usb_text = status.usb_text()
        if usb_text:
            self._row_usb.set_value(usb_text, "#ffaa00")
        else:
            self._row_usb.set_value("无目标", "#8b949e")

    # ------------------------------------------------------------------
    # 模式切换
    # ------------------------------------------------------------------
    def _set_mode(self, mode: str):
        """切换避障模式"""
        self._session.async_set_avoid_mode(
            mode,
            on_done=lambda res: self._notice.show_success(
                res.get("message", "避障模式已切换")),
            on_error=lambda err: self._notice.show_error(f"切换失败: {err}"))
