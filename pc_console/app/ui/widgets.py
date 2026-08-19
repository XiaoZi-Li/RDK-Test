# -*- coding: utf-8 -*-
"""widgets.py - 通用界面部件

提供各页面复用的小部件：
  - make_card:      带标题的卡片容器
  - StatusDotLabel: 带彩色圆点的状态行（运行中/未运行）
  - NoticeLabel:    操作结果提示条（成功/失败/中性）
  - InfoRow:        "标签: 值" 信息行
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)


def make_card(title: str, stretch_last: bool = True):
    """创建带标题的卡片容器

    :param title: 卡片标题
    :return: (卡片QFrame, 内容区QVBoxLayout)
    """
    card = QFrame()
    card.setObjectName("card")
    outer = QVBoxLayout(card)
    outer.setContentsMargins(14, 12, 14, 14)
    outer.setSpacing(8)

    title_label = QLabel(title)
    title_label.setObjectName("cardTitle")
    outer.addWidget(title_label)

    body = QVBoxLayout()
    body.setSpacing(6)
    outer.addLayout(body)
    if stretch_last:
        outer.addStretch(1)
    return card, body


class StatusDotLabel(QWidget):
    """带彩色圆点的状态行: ● 组件名        [运行中]"""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(16)
        self._dot.setAlignment(Qt.AlignCenter)

        self._name = QLabel(name)
        self._name.setStyleSheet("color: #c9d1d9;")

        self._state = QLabel("未运行")
        self._state.setFixedWidth(64)
        self._state.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addWidget(self._dot)
        layout.addWidget(self._name, 1)
        layout.addWidget(self._state)

    def set_state(self, ok: bool, on_text: str = "正常", off_text: str = "未运行"):
        """更新状态: ok=True 绿色, ok=False 红色"""
        if ok:
            self._dot.setStyleSheet("color: #3fb950; font-weight: bold;")
            self._state.setStyleSheet("color: #3fb950;")
            self._state.setText(on_text)
        else:
            self._dot.setStyleSheet("color: #f85149;")
            self._state.setStyleSheet("color: #f85149;")
            self._state.setText(off_text)


class NoticeLabel(QLabel):
    """操作结果提示条: success(绿) / error(红) / info(蓝) / hidden"""

    STYLE_SUCCESS = "background:#1a3a2a;color:#3fb950;border-radius:4px;padding:6px 10px;"
    STYLE_ERROR = "background:#3a1a1a;color:#f85149;border-radius:4px;padding:6px 10px;"
    STYLE_INFO = "background:#1a2a3a;color:#58a6ff;border-radius:4px;padding:6px 10px;"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.hide()

    def show_success(self, text: str):
        self.setStyleSheet(self.STYLE_SUCCESS)
        self.setText(text)
        self.show()

    def show_error(self, text: str):
        self.setStyleSheet(self.STYLE_ERROR)
        self.setText(text)
        self.show()

    def show_info(self, text: str):
        self.setStyleSheet(self.STYLE_INFO)
        self.setText(text)
        self.show()


class InfoRow(QWidget):
    """'标签 | 值' 信息行"""

    def __init__(self, label: str, value: str = "--", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(8)

        self._label = QLabel(label)
        self._label.setStyleSheet("color: #8b949e;")
        self._label.setFixedWidth(96)

        self._value = QLabel(value)
        self._value.setStyleSheet("color: #c9d1d9;")
        self._value.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout.addWidget(self._label)
        layout.addWidget(self._value, 1)

    def set_value(self, value: str, color: str = "#c9d1d9"):
        """更新值文字与颜色"""
        self._value.setText(value)
        self._value.setStyleSheet(f"color: {color};")
