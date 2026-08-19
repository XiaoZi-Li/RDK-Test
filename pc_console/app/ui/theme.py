# -*- coding: utf-8 -*-
"""theme.py - 界面主题样式（QSS 暗色主题）

统一定义软件的全局视觉风格：深色背景、蓝色主色调、
绿色/红色状态色，与板端 Web 监控面板风格保持一致。
"""

# 全局样式表（QSS）
MAIN_QSS = """
/* ---------------- 全局 ---------------- */
QMainWindow, QDialog {
    background: #0d1117;
}
QWidget {
    color: #c9d1d9;
    font-family: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif;
    font-size: 13px;
}
QToolTip {
    background: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    padding: 4px;
}

/* ---------------- 卡片容器 ---------------- */
QFrame#card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
}
QLabel#cardTitle {
    color: #58a6ff;
    font-size: 14px;
    font-weight: bold;
    border-bottom: 1px solid #21262d;
    padding-bottom: 6px;
}

/* ---------------- 顶部标题栏 ---------------- */
QFrame#topBar {
    background: #161b22;
    border-bottom: 1px solid #30363d;
}
QLabel#appTitle {
    color: #58a6ff;
    font-size: 17px;
    font-weight: bold;
}
QLabel#appSubTitle {
    color: #7a8a9a;
    font-size: 12px;
}

/* ---------------- 左侧导航 ---------------- */
QListWidget#navList {
    background: #10151d;
    border: none;
    border-right: 1px solid #30363d;
    outline: none;
    font-size: 14px;
    padding: 8px 0;
}
QListWidget#navList::item {
    height: 44px;
    padding-left: 18px;
    color: #8b949e;
    border-left: 3px solid transparent;
}
QListWidget#navList::item:hover {
    background: #161b22;
    color: #c9d1d9;
}
QListWidget#navList::item:selected {
    background: #161b22;
    color: #58a6ff;
    border-left: 3px solid #58a6ff;
    font-weight: bold;
}

/* ---------------- 按钮 ---------------- */
QPushButton {
    background: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 7px 16px;
}
QPushButton:hover {
    background: #30363d;
    border-color: #58a6ff;
}
QPushButton:pressed {
    background: #1a2a3a;
}
QPushButton:disabled {
    color: #556070;
    background: #161b22;
    border-color: #21262d;
}
QPushButton#primary {
    background: #1a2a3a;
    border-color: #58a6ff;
    color: #58a6ff;
    font-weight: bold;
}
QPushButton#primary:hover { background: #22354a; }
QPushButton#success {
    background: #1a3a2a;
    border-color: #3fb950;
    color: #3fb950;
    font-weight: bold;
}
QPushButton#success:hover { background: #235230; }
QPushButton#danger {
    background: #3a1a1a;
    border-color: #f85149;
    color: #f85149;
    font-weight: bold;
}
QPushButton#danger:hover { background: #4a2222; }
QPushButton#motionPad {
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 8px;
    font-size: 14px;
    font-weight: bold;
    padding: 14px 6px;
}
QPushButton#motionPad:hover {
    background: #30363d;
    border-color: #58a6ff;
}
QPushButton#motionPad:checked {
    background: #1a3a2a;
    border-color: #3fb950;
    color: #3fb950;
}

/* ---------------- 输入控件 ---------------- */
QLineEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: #264f78;
}
QLineEdit:focus {
    border-color: #58a6ff;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background: #161b22;
    border: 1px solid #30363d;
    selection-background-color: #264f78;
}

/* ---------------- 滚动条 ---------------- */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #3d4650;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background: #30363d;
    border-radius: 5px;
    min-width: 30px;
}

/* ---------------- 状态列表 ---------------- */
QLabel#dotOn {
    color: #3fb950;
    font-weight: bold;
}
QLabel#dotOff {
    color: #f85149;
}
QLabel#dimText {
    color: #8b949e;
}
QLabel#okText {
    color: #3fb950;
}
QLabel#errText {
    color: #f85149;
}
QLabel#accentText {
    color: #58a6ff;
    font-weight: bold;
}

/* ---------------- 日志查看 ---------------- */
QPlainTextEdit#logView {
    font-family: 'Consolas', 'JetBrains Mono', monospace;
    font-size: 12px;
    color: #8b949e;
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
}

/* ---------------- 对话气泡 ---------------- */
QTextBrowser#chatView {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 8px;
}

/* ---------------- 视频卡片 ---------------- */
QFrame#videoCard {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
}
QLabel#videoPlaceholder {
    color: #556070;
    font-size: 13px;
}

/* ---------------- 复选框 ---------------- */
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #30363d;
    border-radius: 3px;
    background: #0d1117;
}
QCheckBox::indicator:checked {
    background: #1f6feb;
    border-color: #1f6feb;
}
QCheckBox::indicator:hover {
    border-color: #58a6ff;
}

/* ---------------- 消息提示 ---------------- */
QLabel#noticeOk {
    background: #1a3a2a;
    color: #3fb950;
    border-radius: 4px;
    padding: 6px 10px;
}
QLabel#noticeErr {
    background: #3a1a1a;
    color: #f85149;
    border-radius: 4px;
    padding: 6px 10px;
}
QLabel#noticeInfo {
    background: #1a2a3a;
    color: #58a6ff;
    border-radius: 4px;
    padding: 6px 10px;
}
"""
