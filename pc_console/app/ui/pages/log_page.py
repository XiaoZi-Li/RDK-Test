# -*- coding: utf-8 -*-
"""log_page.py - 日志中心页

查看板端各组件的运行日志：
  - 左侧日志源列表（运动仲裁器/运动中枢/双目深度/避障/机器人/手势/语音助手）
  - 右侧显示选中日志源的末尾内容（等宽字体）
  - 支持手动刷新与自动刷新（随状态轮询周期）

日志内容只读，可通过 Ctrl+C 复制选中文字。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem,
                               QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from ...core.models import LOG_SOURCES
from ...core.session import BoardSession
from ..widgets import NoticeLabel, make_card


class LogPage(QWidget):
    """日志中心页"""

    def __init__(self, session: BoardSession, parent=None):
        super().__init__(parent)
        self._session = session
        self._current_key = None      # 当前选中的日志源
        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        card, body = make_card("日志中心", stretch_last=False)
        root.addWidget(card, 1)

        content = QHBoxLayout()
        content.setSpacing(10)

        # ---- 左侧: 日志源列表 ----
        self._source_list = QListWidget()
        self._source_list.setFixedWidth(170)
        self._source_list.setStyleSheet("background:#10151d;border:1px solid #30363d;"
                                        "border-radius:6px;")
        for key, name in LOG_SOURCES:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, key)
            self._source_list.addItem(item)
        content.addWidget(self._source_list)

        # ---- 右侧: 日志内容 ----
        right = QVBoxLayout()
        right.setSpacing(8)

        toolbar = QHBoxLayout()
        self._title_label = QLabel("选择左侧日志源查看")
        self._title_label.setObjectName("accentText")
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self._load_current_log)
        self._auto_check = QCheckBox("自动刷新（跟随状态轮询）")
        self._auto_check.setChecked(True)
        self._auto_check.stateChanged.connect(
            lambda _state: self._load_current_log())
        toolbar.addWidget(self._title_label)
        toolbar.addStretch(1)
        toolbar.addWidget(self._auto_check)
        toolbar.addWidget(btn_refresh)
        right.addLayout(toolbar)

        self._log_view = QPlainTextEdit()
        self._log_view.setObjectName("logView")
        self._log_view.setReadOnly(True)
        self._log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._log_view.setPlaceholderText("选择左侧日志源查看末尾日志...")
        right.addWidget(self._log_view, 1)

        self._notice = NoticeLabel()
        right.addWidget(self._notice)

        content.addLayout(right, 1)
        body.addLayout(content, 1)

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _connect_signals(self):
        self._source_list.currentItemChanged.connect(self._on_source_changed)
        # 自动刷新跟随状态轮询信号
        self._session.statusUpdated.connect(
            lambda _status: self._auto_refresh())

    # ------------------------------------------------------------------
    # 日志加载
    # ------------------------------------------------------------------
    def _on_source_changed(self, current, _previous):
        """切换日志源"""
        if current is None:
            return
        self._current_key = current.data(Qt.UserRole)
        self._title_label.setText(
            f"{current.text()} 日志（末尾 {self._session.config.log_lines} 行）")
        self._load_current_log()

    def _load_current_log(self):
        """手动/触发式加载当前日志源"""
        if not self._current_key:
            return
        key = self._current_key
        self._session.async_get_log(
            key,
            on_done=lambda res: self._show_log(res),
            on_error=lambda err: self._notice.show_error(f"日志加载失败: {err}"))

    def _auto_refresh(self):
        """自动刷新回调（仅当开关开启且有选中日志源时拉取）"""
        if self._auto_check.isChecked() and self._current_key:
            self._load_current_log()

    def _show_log(self, result: dict):
        """渲染日志内容并滚动到底部"""
        content = result.get("content", "")
        if not content:
            content = "(日志为空)"
        self._log_view.setPlainText(content)
        bar = self._log_view.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._notice.hide()
