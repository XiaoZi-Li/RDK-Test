# -*- coding: utf-8 -*-
"""chat_page.py - 大模型对话控制页

提供自然语言对话控制界面：
  - 输入自然语言指令（如"先坐下再站起来"），板端大模型
    解析为回复文本 + 动作序列并自动执行
  - 视觉问句（如"你能看到什么"）自动路由至视觉问答模块，
    基于实时摄像头画面回答
  - 可选"喇叭同步播报"：回答经板端语音助手喇叭播出
  - 支持清空会话重新开始

消息以 HTML 气泡形式渲染，动作序列以绿色标签展示；
会话内容以片段列表维护，整体重绘，避免富文本局部删除。
"""

import html

from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QTextBrowser, QVBoxLayout,
                               QWidget)

from ...core.session import BoardSession
from ..widgets import make_card

# "思考中"占位气泡 HTML
_THINKING_HTML = (
    '<div style="margin:6px 0;">'
    '<span style="display:inline-block;background:#21262d;'
    'color:#8b949e;border:1px solid #30363d;border-radius:8px;'
    'padding:6px 10px;">思考中...</span></div>')


class ChatPage(QWidget):
    """大模型对话控制页"""

    def __init__(self, session: BoardSession, parent=None):
        super().__init__(parent)
        self._session = session
        self._fragments = []        # 已渲染消息的 HTML 片段列表
        self._thinking_active = False   # "思考中"占位是否显示中
        self._build_ui()
        self._append_system_welcome()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        card, body = make_card("大模型对话控制", stretch_last=False)
        root.addWidget(card, 1)

        # ---- 对话显示区 ----
        self._view = QTextBrowser()
        self._view.setObjectName("chatView")
        self._view.setOpenExternalLinks(False)
        body.addWidget(self._view, 1)

        # ---- 输入区 ----
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self._input = QLineEdit()
        self._input.setPlaceholderText("输入指令或聊天内容，回车发送，如：先坐下再站起来")
        self._input.returnPressed.connect(self._send_message)
        self._btn_send = QPushButton("发送")
        self._btn_send.setObjectName("primary")
        self._btn_send.clicked.connect(self._send_message)
        self._btn_clear = QPushButton("清空会话")
        self._btn_clear.clicked.connect(self._clear_chat)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._btn_send)
        input_row.addWidget(self._btn_clear)
        body.addLayout(input_row)

        # ---- 选项行 ----
        option_row = QHBoxLayout()
        self._speak_check = QCheckBox("喇叭同步播报回答（经板端语音助手）")
        self._speak_check.setChecked(True)
        option_row.addWidget(self._speak_check)
        option_row.addStretch(1)
        body.addLayout(option_row)

        hint = QLabel("与板端语音助手共用同一大模型与动作执行通道；"
                      "视觉类问题会调用实时摄像头画面回答（回复带 [视觉] 标记）。")
        hint.setStyleSheet("color: #7a8a9a; font-size: 12px;")
        hint.setWordWrap(True)
        body.addWidget(hint)

    # ------------------------------------------------------------------
    # 消息渲染
    # ------------------------------------------------------------------
    def _append_system_welcome(self):
        """显示欢迎消息"""
        self._fragments = []
        self._append_bubble(
            "assistant",
            "你好，我是机器狗。输入文字指令即可控制我，"
            "例如「先坐下再站起来」「前进两秒然后左转」，"
            "也可以问我「你能看到什么」。")

    def _append_bubble(self, role: str, text: str, actions=None,
                       vision: bool = False):
        """追加一条对话气泡并整体重绘

        :param role:     user / assistant
        :param text:     消息正文（自动 HTML 转义）
        :param actions:  动作序列 [{'action':..,'duration':..}]
        :param vision:   是否视觉问答回复
        """
        escaped = html.escape(text).replace("\n", "<br>")
        prefix = ""
        if vision:
            prefix = '<span style="color:#ffaa00;">[视觉]</span> '
        if role == "user":
            bubble = (
                f'<div style="margin:6px 0;text-align:right;">'
                f'<span style="display:inline-block;background:#1a2a3a;'
                f'color:#58a6ff;border:1px solid #264a6b;border-radius:8px;'
                f'padding:6px 10px;max-width:80%;text-align:left;">{escaped}</span></div>')
        else:
            bubble = (
                f'<div style="margin:6px 0;">'
                f'<span style="display:inline-block;background:#21262d;'
                f'color:#c9d1d9;border:1px solid #30363d;border-radius:8px;'
                f'padding:6px 10px;max-width:85%;">{prefix}{escaped}</span>')
            if actions:
                parts = []
                for act in actions:
                    if isinstance(act, dict):
                        name = act.get("action", "")
                        duration = act.get("duration")
                        if isinstance(duration, (int, float)):
                            parts.append(f"{name} {duration}s")
                        else:
                            parts.append(str(name))
                if parts:
                    seq = " → ".join(html.escape(p) for p in parts)
                    bubble += (
                        f'<br><span style="color:#3fb950;font-size:12px;">'
                        f'[动作序列] {seq}</span>')
            bubble += "</div>"
        self._fragments.append(bubble)
        self._rerender()

    def _append_thinking(self):
        """显示"思考中"占位气泡"""
        self._thinking_active = True
        self._rerender()

    def _remove_thinking(self):
        """移除"思考中"占位气泡"""
        self._thinking_active = False

    def _rerender(self):
        """按片段列表整体重绘会话内容"""
        parts = list(self._fragments)
        if self._thinking_active:
            parts.append(_THINKING_HTML)
        self._view.setHtml("".join(parts))
        bar = self._view.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ------------------------------------------------------------------
    # 发送与回调
    # ------------------------------------------------------------------
    def _send_message(self):
        """发送用户消息并请求板端大模型"""
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._append_bubble("user", text)
        self._btn_send.setEnabled(False)
        self._append_thinking()

        speak = self._speak_check.isChecked()
        self._session.async_chat(
            text, speak,
            on_done=self._on_chat_done,
            on_error=self._on_chat_error)

    def _on_chat_done(self, result: dict):
        """对话成功回调：移除占位并渲染回复"""
        self._btn_send.setEnabled(True)
        self._remove_thinking()
        if result.get("ok"):
            reply = result.get("reply") or "(无回复)"
            actions = result.get("actions") or []
            vision = bool(result.get("vision"))
            self._append_bubble("assistant", reply, actions, vision)
        else:
            self._append_bubble("assistant",
                                "[请求失败] " + str(result.get("error", "")))
        self._input.setFocus()

    def _on_chat_error(self, error: str):
        """对话失败回调"""
        self._btn_send.setEnabled(True)
        self._remove_thinking()
        self._append_bubble("assistant", "[网络错误] " + html.escape(error))
        self._input.setFocus()

    def _clear_chat(self):
        """清空会话"""
        self._thinking_active = False
        self._append_system_welcome()
        self._input.setFocus()
