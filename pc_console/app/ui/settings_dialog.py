# -*- coding: utf-8 -*-
"""settings_dialog.py - 连接设置对话框

编辑上位机连接与行为参数：
  - 板端 IP 与 API 端口
  - 状态轮询间隔
  - 长按心跳间隔
  - 遥控发送频率
  - 演示模式开关

确认后配置写盘并通知主窗口重启会话。
"""

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QVBoxLayout)

from ..config import ConsoleConfig


class SettingsDialog(QDialog):
    """连接设置对话框"""

    def __init__(self, config: ConsoleConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("连接设置")
        self.setMinimumWidth(420)
        self._build_ui()
        self._load_from_config()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        # 板端 IP
        self._edit_host = QLineEdit()
        self._edit_host.setPlaceholderText("例如 192.168.1.10")
        form.addRow("板端 IP 地址:", self._edit_host)

        # API 端口
        self._spin_api_port = QDoubleSpinBox()
        self._spin_api_port.setRange(1, 65535)
        self._spin_api_port.setDecimals(0)
        self._spin_api_port.setValue(8081)
        form.addRow("板端 API 端口:", self._spin_api_port)

        # 轮询间隔
        self._spin_poll = QDoubleSpinBox()
        self._spin_poll.setRange(0.5, 30.0)
        self._spin_poll.setSingleStep(0.5)
        self._spin_poll.setSuffix(" 秒")
        form.addRow("状态轮询间隔:", self._spin_poll)

        # 心跳间隔
        self._spin_heartbeat = QDoubleSpinBox()
        self._spin_heartbeat.setRange(50, 2000)
        self._spin_heartbeat.setDecimals(0)
        self._spin_heartbeat.setSingleStep(50)
        self._spin_heartbeat.setSuffix(" 毫秒")
        form.addRow("长按心跳间隔:", self._spin_heartbeat)

        # 遥控频率
        self._spin_move_rate = QDoubleSpinBox()
        self._spin_move_rate.setRange(1, 30)
        self._spin_move_rate.setSingleStep(1)
        self._spin_move_rate.setSuffix(" Hz")
        form.addRow("遥控发送频率:", self._spin_move_rate)

        # 请求超时
        self._spin_timeout = QDoubleSpinBox()
        self._spin_timeout.setRange(1, 30)
        self._spin_timeout.setSingleStep(0.5)
        self._spin_timeout.setSuffix(" 秒")
        form.addRow("请求超时:", self._spin_timeout)

        root.addLayout(form)

        # 演示模式
        demo_row = QHBoxLayout()
        self._check_demo = QCheckBox("演示模式（使用内置模拟数据源，无需连接真实板端）")
        demo_row.addWidget(self._check_demo)
        root.addLayout(demo_row)

        hint = QLabel("修改连接参数后点击\"确定\"立即生效并保存；"
                      "板端 IP 为板端 dashboard 服务所在地址。")
        hint.setStyleSheet("color: #7a8a9a; font-size: 12px;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    # 数据加载 / 校验 / 保存
    # ------------------------------------------------------------------
    def _load_from_config(self):
        """从配置对象填充控件"""
        self._edit_host.setText(self._config.board_host)
        self._spin_api_port.setValue(self._config.api_port)
        self._spin_poll.setValue(self._config.poll_interval)
        self._spin_heartbeat.setValue(self._config.heartbeat_ms)
        self._spin_move_rate.setValue(self._config.move_rate_hz)
        self._spin_timeout.setValue(self._config.request_timeout)
        self._check_demo.setChecked(self._config.demo_mode)

    def _on_accept(self):
        """校验输入并接受对话框"""
        host = self._edit_host.text().strip()
        if not host:
            self._edit_host.setFocus()
            self._edit_host.setStyleSheet("border: 1px solid #f85149;")
            return
        self._config.board_host = host
        self._config.api_port = int(self._spin_api_port.value())
        self._config.poll_interval = float(self._spin_poll.value())
        self._config.heartbeat_ms = int(self._spin_heartbeat.value())
        self._config.move_rate_hz = float(self._spin_move_rate.value())
        self._config.request_timeout = float(self._spin_timeout.value())
        self._config.demo_mode = self._check_demo.isChecked()
        self._config.save()
        self.accept()
