# -*- coding: utf-8 -*-
"""main_window.py - 软件主窗口

整体布局：
  ┌──────────────────────────────────────────────┐
  │ 顶部标题栏: 软件名称 | 版本 | 板端地址 | 设置 │
  ├──────────┬───────────────────────────────────┤
  │ 左侧导航 │  QStackedWidget 功能页面区          │
  │  系统总览│   - 系统总览页                      │
  │  视频监控│   - 视频监控页                      │
  │  运动控制│   - 运动控制页                      │
  │  对话控制│   - 对话控制页                      │
  │  避障监测│   - 避障监测页                      │
  │  日志中心│   - 日志中心页                      │
  │  系统管理│   - 系统管理页                      │
  ├──────────┴───────────────────────────────────┤
  │ 底部状态栏: 连接状态 | 数据源 | 最后更新时间    │
  └──────────────────────────────────────────────┘

负责: 页面注册与切换、全局会话生命周期、设置与关于对话框。
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QStatusBar,
                               QVBoxLayout, QWidget)

from ..config import ConsoleConfig
from ..core.session import BoardSession
from ..version import (APP_DESCRIPTION, APP_NAME, APP_NAME_EN, APP_VERSION,
                       COPYRIGHT_TEXT)
from .pages.avoid_page import AvoidPage
from .pages.chat_page import ChatPage
from .pages.log_page import LogPage
from .pages.motion_page import MotionPage
from .pages.overview_page import OverviewPage
from .pages.system_page import SystemPage
from .pages.video_page import VideoPage
from .settings_dialog import SettingsDialog
from .theme import MAIN_QSS

# 导航项: (标题, 页面标识)
_NAV_ITEMS = [
    ("系统总览", "overview"),
    ("视频监控", "video"),
    ("运动控制", "motion"),
    ("对话控制", "chat"),
    ("避障监测", "avoid"),
    ("日志中心", "log"),
    ("系统管理", "system"),
]


class MainWindow(QMainWindow):
    """软件主窗口"""

    def __init__(self, config: ConsoleConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._session = BoardSession(config, self)
        self._pages = {}
        self._page_keys = []       # 与堆栈顺序对应的页面标识

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1280, 800)
        self.setStyleSheet(MAIN_QSS)

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶部标题栏 ----
        root.addWidget(self._build_top_bar())

        # ---- 中部: 导航 + 页面堆栈 ----
        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)

        self._nav = QListWidget()
        self._nav.setObjectName("navList")
        self._nav.setFixedWidth(170)
        for title, key in _NAV_ITEMS:
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, key)
            item.setTextAlignment(Qt.AlignVCenter)
            self._nav.addItem(item)
        self._nav.setCurrentRow(0)
        middle.addWidget(self._nav)

        self._stack = QStackedWidget()
        self._register_pages()
        middle.addWidget(self._stack, 1)

        root.addLayout(middle, 1)

        # ---- 底部状态栏 ----
        root.addWidget(self._build_status_bar())

    def _build_top_bar(self) -> QFrame:
        """顶部标题栏"""
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(58)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 8, 18, 8)

        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        subtitle = QLabel(f"{APP_NAME_EN} {APP_VERSION}")
        subtitle.setObjectName("appSubTitle")

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        self._host_label = QLabel("板端: --")
        self._host_label.setObjectName("dimText")
        self._mode_badge = QLabel("在线模式")
        self._mode_badge.setStyleSheet(
            "color:#ffaa00;border:1px solid #5a4420;border-radius:4px;"
            "padding:2px 8px;font-size:12px;")

        btn_settings = QPushButton("连接设置")
        btn_settings.clicked.connect(self._open_settings)
        btn_about = QPushButton("关于")
        btn_about.clicked.connect(self._show_about)

        layout.addLayout(title_box)
        layout.addStretch(1)
        layout.addWidget(self._host_label)
        layout.addSpacing(12)
        layout.addWidget(self._mode_badge)
        layout.addSpacing(12)
        layout.addWidget(btn_settings)
        layout.addWidget(btn_about)
        return bar

    def _build_status_bar(self) -> QStatusBar:
        """底部状态栏"""
        status = QStatusBar()
        status.setStyleSheet(
            "QStatusBar { background:#161b22; border-top:1px solid #30363d;"
            "color:#8b949e; }")
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color:#f85149;")
        self._status_text = QLabel("未连接")
        self._status_source = QLabel("数据源: --")
        self._status_update = QLabel("最后更新: --")
        status.addWidget(self._status_dot)
        status.addWidget(self._status_text)
        status.addPermanentWidget(self._status_source)
        status.addPermanentWidget(self._status_update)
        return status

    def _register_pages(self):
        """创建并注册全部功能页面"""
        pages = {
            "overview": lambda: OverviewPage(self._session),
            "video": lambda: VideoPage(self._session, self._config),
            "motion": lambda: MotionPage(self._session, self._config),
            "chat": lambda: ChatPage(self._session),
            "avoid": lambda: AvoidPage(self._session),
            "log": lambda: LogPage(self._session),
            "system": lambda: SystemPage(self._session),
        }
        for _, key in _NAV_ITEMS:
            page = pages[key]()
            self._pages[key] = page
            self._stack.addWidget(page)
            self._page_keys.append(key)

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _connect_signals(self):
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        self._session.statusUpdated.connect(self._on_status_updated)
        self._session.connectionChanged.connect(self._on_connection_changed)

    # ------------------------------------------------------------------
    # 会话生命周期
    # ------------------------------------------------------------------
    def start(self):
        """启动会话轮询（main() 中调用）"""
        self._session.start()
        self._update_host_label()

    def shutdown(self):
        """退出前清理（停止轮询与视频流）"""
        self._video_page().stop_streams()
        self._session.stop()

    def _video_page(self) -> VideoPage:
        return self._pages["video"]

    # ------------------------------------------------------------------
    # 导航切换
    # ------------------------------------------------------------------
    def _on_nav_changed(self, row: int):
        """切换页面；进入视频页时启动拉流，离开时停止"""
        if row < 0 or row >= len(self._page_keys):
            return
        key = self._page_keys[row]
        # 离开视频页则停流节省带宽
        video_page = self._video_page()
        if key != "video" and video_page.is_started():
            video_page.stop_streams()
        self._stack.setCurrentIndex(row)
        if key == "video" and not video_page.is_started():
            video_page.start_streams()

    # ------------------------------------------------------------------
    # 状态回调
    # ------------------------------------------------------------------
    def _on_status_updated(self, status):
        """状态快照到达: 刷新底部最后更新时间"""
        self._status_update.setText(f"最后更新: {status.timestamp}")

    def _on_connection_changed(self, online: bool, message: str):
        """连接状态变化: 刷新状态栏指示灯"""
        if online:
            self._status_dot.setStyleSheet("color:#3fb950;")
            self._status_text.setText(message)
        else:
            self._status_dot.setStyleSheet("color:#f85149;")
            self._status_text.setText(message)

    def _update_host_label(self):
        """刷新顶部板端地址与模式徽标"""
        mode = "演示模式" if self._config.demo_mode else "在线模式"
        self._mode_badge.setText(mode)
        if self._config.demo_mode:
            self._mode_badge.setStyleSheet(
                "color:#ffaa00;border:1px solid #5a4420;border-radius:4px;"
                "padding:2px 8px;font-size:12px;")
        else:
            self._mode_badge.setStyleSheet(
                "color:#3fb950;border:1px solid #2a4a30;border-radius:4px;"
                "padding:2px 8px;font-size:12px;")
        self._host_label.setText(f"板端: {self._config.board_host}:{self._config.api_port}")
        self._status_source.setText(
            "数据源: " + ("内置演示" if self._config.demo_mode else "板端实时"))

    # ------------------------------------------------------------------
    # 对话框
    # ------------------------------------------------------------------
    def _open_settings(self):
        """打开连接设置并应用新配置"""
        dialog = SettingsDialog(self._config, self)
        if dialog.exec():
            self._session.restart_with_config(self._config)
            self._update_host_label()

    def _show_about(self):
        """关于对话框"""
        QMessageBox.about(
            self, "关于",
            f"<h3>{APP_NAME} {APP_VERSION}</h3>"
            f"<p>{APP_DESCRIPTION}</p>"
            f"<p style='color:#8b949e'>{COPYRIGHT_TEXT}</p>")

    # ------------------------------------------------------------------
    # 窗口关闭
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        """关闭窗口前停止后台线程"""
        self.shutdown()
        super().closeEvent(event)
