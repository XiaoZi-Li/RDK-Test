# -*- coding: utf-8 -*-
"""overview_page.py - 系统总览页

集中展示板端整体运行状态：
  - 组件运行状态灯列表
  - UDP 端口监听状态
  - 视频流在线状态
  - 板端连接信息（IP / 时间戳）
  - 快捷操作区（系统启停 / 避障模式切换）

数据来源: BoardSession.statusUpdated 信号（3 秒轮询）。
"""

from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from ...core.models import SystemStatus
from ...core.session import BoardSession
from ..widgets import InfoRow, NoticeLabel, StatusDotLabel, make_card


class OverviewPage(QWidget):
    """系统总览页"""

    def __init__(self, session: BoardSession, parent=None):
        super().__init__(parent)
        self._session = session
        self._component_rows = {}    # 组件名 -> StatusDotLabel
        self._udp_rows = {}          # UDP 端口 -> StatusDotLabel
        self._video_rows = {}        # 视频端口 -> StatusDotLabel

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        grid = QGridLayout()
        grid.setSpacing(12)
        root.addLayout(grid, 1)

        # ---- 卡片1: 组件状态 ----
        card_components, body_components = make_card("组件运行状态")
        grid.addWidget(card_components, 0, 0, 2, 1)
        self._component_container = body_components

        # ---- 卡片2: 板端连接信息 ----
        card_info, body_info = make_card("板端连接信息", stretch_last=False)
        grid.addWidget(card_info, 0, 1)
        self._row_ip = InfoRow("板端 IP", "--")
        self._row_time = InfoRow("状态时间", "--")
        self._row_comp = InfoRow("组件在线", "--")
        self._row_video = InfoRow("视频在线", "--")
        for row in (self._row_ip, self._row_time, self._row_comp, self._row_video):
            body_info.addWidget(row)

        # ---- 卡片3: UDP 端口 ----
        card_udp, body_udp = make_card("UDP 端口", stretch_last=False)
        grid.addWidget(card_udp, 1, 1)
        self._udp_container = body_udp

        # ---- 卡片4: 视频流状态 ----
        card_video, body_video = make_card("视频流在线状态", stretch_last=False)
        grid.addWidget(card_video, 0, 2)
        self._video_container = body_video

        # ---- 卡片5: 快捷操作 ----
        card_quick, body_quick = make_card("快捷操作", stretch_last=False)
        grid.addWidget(card_quick, 1, 2)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        btn_start = QPushButton("启动全部")
        btn_start.setObjectName("success")
        btn_start.clicked.connect(lambda: self._sys_command("start"))
        btn_stop = QPushButton("停止全部")
        btn_stop.setObjectName("danger")
        btn_stop.clicked.connect(lambda: self._sys_command("stop"))
        btn_restart = QPushButton("重启全部")
        btn_restart.setObjectName("primary")
        btn_restart.clicked.connect(lambda: self._sys_command("restart"))
        for b in (btn_start, btn_stop, btn_restart):
            row1.addWidget(b)
        body_quick.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        btn_avoid_on = QPushButton("开启避障巡航")
        btn_avoid_on.setObjectName("success")
        btn_avoid_on.clicked.connect(lambda: self._set_avoid("on"))
        btn_avoid_off = QPushButton("关闭避障")
        btn_avoid_off.setObjectName("danger")
        btn_avoid_off.clicked.connect(lambda: self._set_avoid("off"))
        row2.addWidget(btn_avoid_on)
        row2.addWidget(btn_avoid_off)
        body_quick.addLayout(row2)

        self._notice = NoticeLabel()
        body_quick.addWidget(self._notice)

        hint = QLabel("系统启停命令经板端 dashboard 服务执行；避障模式切换实时下发至避障节点。")
        hint.setStyleSheet("color: #7a8a9a; font-size: 12px;")
        hint.setWordWrap(True)
        body_quick.addWidget(hint)

        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 2)

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _connect_signals(self):
        self._session.statusUpdated.connect(self._on_status_updated)

    # ------------------------------------------------------------------
    # 状态刷新
    # ------------------------------------------------------------------
    def _on_status_updated(self, status: SystemStatus):
        """状态快照到达：增量刷新各状态行"""
        # 组件状态行（首次到达时按数据动态创建）
        existing = set(self._component_rows.keys())
        incoming = {c.name for c in status.components}
        if existing != incoming:
            self._rebuild_component_rows(status)
        for comp in status.components:
            row = self._component_rows.get(comp.name)
            if row is not None:
                row.set_state(comp.running, "运行中", "未运行")

        # UDP 端口行
        for udp in status.udp_ports:
            key = udp.port
            if key not in self._udp_rows:
                row = StatusDotLabel(f"UDP {udp.port}（{udp.desc}）")
                self._udp_rows[key] = row
                self._udp_container.addWidget(row)
            self._udp_rows[key].set_state(udp.listening, "监听中", "未监听")

        # 视频流行
        for video in status.video_streams:
            key = video.port
            if key not in self._video_rows:
                row = StatusDotLabel(f"{video.desc} :{video.port}")
                self._video_rows[key] = row
                self._video_container.addWidget(row)
            self._video_rows[key].set_state(video.online, "在线", "离线")

        # 汇总信息
        online_video = sum(1 for v in status.video_streams if v.online)
        self._row_ip.set_value(status.board_ip, "#58a6ff")
        self._row_time.set_value(status.timestamp)
        self._row_comp.set_value(
            f"{status.online_component_count()}/{status.total_component_count()}",
            "#3fb950" if status.online_component_count() > 0 else "#f85149")
        self._row_video.set_value(f"{online_video}/{len(status.video_streams)}",
                                  "#3fb950" if online_video > 0 else "#8b949e")

    def _rebuild_component_rows(self, status: SystemStatus):
        """组件清单变化时重建状态行"""
        for row in self._component_rows.values():
            row.setParent(None)
            row.deleteLater()
        self._component_rows.clear()
        for comp in status.components:
            row = StatusDotLabel(comp.name)
            self._component_rows[comp.name] = row
            self._component_container.addWidget(row)

    # ------------------------------------------------------------------
    # 快捷操作
    # ------------------------------------------------------------------
    def _sys_command(self, command: str):
        """执行系统级命令（带确认）"""
        names = {"start": "启动", "stop": "停止", "restart": "重启"}
        self._notice.show_info(f"正在执行 {names.get(command, command)} 全部组件...")
        self._session.async_sys_command(
            command,
            on_done=lambda res: self._notice.show_success(
                f"命令已下发: {res.get('output', '')[:120]}"),
            on_error=lambda err: self._notice.show_error(f"命令失败: {err}"))

    def _set_avoid(self, mode: str):
        """切换避障模式"""
        self._session.async_set_avoid_mode(
            mode,
            on_done=lambda res: self._notice.show_success(
                res.get("message", "避障模式已切换")),
            on_error=lambda err: self._notice.show_error(f"切换失败: {err}"))
