# -*- coding: utf-8 -*-
"""system_page.py - 系统管理页

板端组件的启停与恢复操作：
  - 启动全部 / 停止全部 / 重启全部
  - 单独重启双目深度链路（深度图异常时使用）
  - 单独重启运动中枢（sit.py）
  - 操作输出实时显示

危险操作（停止/重启）均带二次确认。
"""

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from ...core.session import BoardSession
from ..widgets import NoticeLabel, make_card


def _hint_label(text: str) -> QLabel:
    """创建灰色说明文字"""
    label = QLabel(text)
    label.setStyleSheet("color: #7a8a9a; font-size: 12px;")
    label.setWordWrap(True)
    return label


class SystemPage(QWidget):
    """系统管理页"""

    def __init__(self, session: BoardSession, parent=None):
        super().__init__(parent)
        self._session = session
        self._build_ui()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # ---- 全局操作卡 ----
        card_all, body_all = make_card("全局组件管理", stretch_last=False)
        root.addWidget(card_all)

        row1 = self._make_button_row(
            ("启动全部组件", "success", lambda: self._sys_command("start")),
            ("停止全部组件", "danger", lambda: self._sys_command("stop")),
            ("重启全部组件", "primary", lambda: self._sys_command("restart")),
        )
        body_all.addLayout(row1)
        body_all.addWidget(_hint_label(
            "重启链路耗时约 1 分钟，命令在后台执行，执行后可切换到"
            "\"系统总览\"页观察组件状态恢复情况。"))

        # ---- 单独重启卡 ----
        card_single, body_single = make_card("单独重启", stretch_last=False)
        root.addWidget(card_single)

        row_single = self._make_button_row(
            ("重启双目深度链路", "primary", self._restart_stereo),
            ("重启运动中枢", "primary", self._restart_robot),
        )
        body_single.addLayout(row_single)
        body_single.addWidget(_hint_label(
            "深度图异常（黑屏/花屏）时单独重启双目深度链路，"
            "不影响运动中枢与语音助手；机器狗无响应时单独重启运动中枢。"))

        # ---- 输出区卡 ----
        card_output, body_output = make_card("操作输出", stretch_last=False)
        root.addWidget(card_output, 1)

        self._output_view = QPlainTextEdit()
        self._output_view.setObjectName("logView")
        self._output_view.setReadOnly(True)
        self._output_view.setPlaceholderText("操作输出将显示在这里...")
        body_output.addWidget(self._output_view)

        self._notice = NoticeLabel()
        body_output.addWidget(self._notice)

    def _make_button_row(self, *buttons):
        """创建一行按钮: 每项为 (文字, 样式对象名, 回调)"""
        row = QHBoxLayout()
        row.setSpacing(8)
        for text, style, callback in buttons:
            button = QPushButton(text)
            button.setObjectName(style)
            button.clicked.connect(callback)
            row.addWidget(button)
        row.addStretch(1)
        return row

    # ------------------------------------------------------------------
    # 操作处理
    # ------------------------------------------------------------------
    def _confirm(self, title: str, text: str) -> bool:
        """危险操作二次确认"""
        answer = QMessageBox.question(
            self, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _append_output(self, text: str):
        """追加输出内容并滚动到底部"""
        self._output_view.appendPlainText(text)
        bar = self._output_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _sys_command(self, command: str):
        """全局启停命令（stop/restart 带二次确认）"""
        names = {"start": "启动", "stop": "停止", "restart": "重启"}
        if command in ("stop", "restart"):
            if not self._confirm(
                    "确认操作",
                    f"确认要{names[command]}全部板端组件吗？"):
                return
        self._notice.show_info(f"正在{names[command]}全部组件...")
        self._append_output(f">>> {names[command]}全部组件")
        self._session.async_sys_command(
            command,
            on_done=self._on_command_done,
            on_error=self._on_command_error)

    def _restart_stereo(self):
        """单独重启双目深度链路"""
        self._notice.show_info("正在重启双目深度链路（后台执行，约 1 分钟）...")
        self._append_output(">>> 重启双目深度链路")
        self._session.async_restart_stereo(
            on_done=self._on_command_done,
            on_error=self._on_command_error)

    def _restart_robot(self):
        """单独重启运动中枢"""
        if not self._confirm("确认操作", "确认要重启运动中枢吗？"):
            return
        self._notice.show_info("正在重启运动中枢...")
        self._append_output(">>> 重启运动中枢")
        self._session.async_restart_robot(
            on_done=self._on_command_done,
            on_error=self._on_command_error)

    def _on_command_done(self, result: dict):
        """命令成功回调"""
        output = result.get("output", "")
        self._notice.show_success("命令已下发，详见下方输出")
        if output:
            self._append_output(output)

    def _on_command_error(self, error: str):
        """命令失败回调"""
        self._notice.show_error(f"命令失败: {error}")
        self._append_output(f"[错误] {error}")
