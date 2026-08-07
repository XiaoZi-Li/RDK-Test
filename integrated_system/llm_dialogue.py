#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llm_dialogue.py - 云端大模型语音对话与意图识别

通过 DeepSeek API（OpenAI 兼容）实现：
1. 多轮语音对话（保持上下文）
2. 意图识别：从用户语句中提取运动控制指令
3. 自然语言回复生成

设计思路（类似 ESP32 小智项目）：
- 端侧只做语音采集 (VAD) + 识别 (Vosk ASR) + 播报 (TTS)
- LLM 推理走云端 API，不占板载算力
- LLM 用 system prompt 约束输出 JSON: {"reply": "...", "action": "..."}
- action 为空表示纯聊天，有值则同时触发运动控制
"""
import json
import os
import time
import urllib.request
import urllib.error
from typing import Optional, Tuple


# ============ System Prompt ============
SYSTEM_PROMPT = """你是一个名叫"小狗"的机器狗语音助手，运行在 RDK X5 开发板上。

你的职责：
1. 和用户自然对话，回答问题、聊天
2. 识别用户的运动控制意图，并输出对应的动作指令

你可以控制以下动作（action字段）：
- "forward"   : 前进
- "backward"  : 后退
- "turn_left"  : 左转
- "turn_right" : 右转
- "sit"       : 坐下
- "stand"     : 站立
- "stop"      : 停止
- null        : 纯聊天，不触发动作

规则：
- 当用户明确要求移动（如"前进"、"走两步"、"往前走"），设置 action 为对应动作
- 当用户要求停止或停下，设置 action 为 "stop"
- 当用户要求坐下/站起来，设置 action 为 "sit"/"stand"
- 纯聊天、问问题、闲聊时，action 设为 null
- 回复要简短口语化，像对话一样，不要超过两三句
- 如果用户说的话含糊不清，可以追问

你必须严格以 JSON 格式回复，不要输出任何其他内容：
{"reply": "你的语音回复", "action": "动作名或null"}

示例：
用户："你好啊" → {"reply": "你好！我是小狗，有什么可以帮你的吗？", "action": null}
用户："向前走" → {"reply": "好的，我往前走了！", "action": "forward"}
用户："停下" → {"reply": "好的，我停下来了。", "action": "stop"}
用户："坐下来" → {"reply": "好的，我坐下了。", "action": "sit"}
用户："介绍一下你自己" → {"reply": "我是小狗，一只智能机器狗。我能听懂你的话，会走路、坐下，还能陪你聊天！", "action": null}
"""


class LlmDialogue:
    """云端 LLM 对话管理器"""

    def __init__(self, config: dict):
        llm_cfg = config.get("llm", {})
        self.api_key = llm_cfg.get("api_key", "")
        self.base_url = llm_cfg.get("base_url", "https://api.deepseek.com/v1")
        self.model = llm_cfg.get("model", "deepseek-chat")
        self.max_tokens = llm_cfg.get("max_tokens", 512)
        self.temperature = llm_cfg.get("temperature", 0.7)

        if not self.api_key:
            raise ValueError("config.json 中 llm.api_key 未配置")

        # 多轮对话历史
        self.history: list = []
        self.max_history = 10  # 保留最近 10 轮（user+assistant 各算一轮）

        print(f"[LLM] DeepSeek 对话初始化: model={self.model}")

    def _call_api(self, messages: list) -> str:
        """调用 DeepSeek API（OpenAI 兼容格式）"""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": False,
        }

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"DeepSeek API HTTP {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"网络错误: {e.reason}") from e

    def _parse_response(self, raw: str) -> Tuple[str, Optional[str]]:
        """解析 LLM 返回的 JSON，提取 reply 和 action

        Returns:
            (reply_text, action_or_None)
        """
        # 尝试直接解析
        try:
            data = json.loads(raw)
            reply = data.get("reply", raw).strip()
            action = data.get("action")
            if isinstance(action, str):
                action = action.strip().lower()
                if action in ("null", "none", ""):
                    action = None
            return reply, action
        except json.JSONDecodeError:
            pass

        # 如果不是 JSON，尝试从 markdown 代码块中提取
        if "```json" in raw:
            start = raw.index("```json") + 7
            end = raw.index("```", start)
            try:
                data = json.loads(raw[start:end].strip())
                reply = data.get("reply", "").strip()
                action = data.get("action")
                if isinstance(action, str):
                    action = action.strip().lower()
                    if action in ("null", "none", ""):
                        action = None
                return reply or raw, action
            except (json.JSONDecodeError, ValueError):
                pass

        # 兜底：整段当 reply，无 action
        return raw.strip(), None

    def chat(self, user_text: str) -> Tuple[str, Optional[str]]:
        """一轮对话

        Args:
            user_text: ASR 识别到的用户文本

        Returns:
            (reply_text, action_or_None)
            - reply_text: LLM 生成的回复文本（用于 TTS 播报）
            - action: 运动控制指令（forward/sit/stop/...），纯聊天时为 None
        """
        # 构造消息列表
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_text})

        # 调用 API
        raw = self._call_api(messages)

        # 解析
        reply, action = self._parse_response(raw)

        # 更新历史
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": raw})
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-(self.max_history * 2):]

        return reply, action

    def reset(self):
        """清空对话历史"""
        self.history.clear()
        print("[LLM] 对话历史已清空")


# ============ 测试 ============
def main():
    """独立测试：验证 LLM 对话和意图提取"""
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if not os.path.exists(config_path):
        print(f"[ERROR] 配置文件不存在: {config_path}")
        print("请复制 config.example.json 为 config.json 并填入 API Key")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    llm = LlmDialogue(config)

    test_cases = [
        "你好啊",
        "向前走",
        "介绍一下你自己",
        "坐下",
        "停下",
        "你叫什么名字？",
        "往左转",
    ]

    print("\n=== LLM 对话测试 ===\n")
    for text in test_cases:
        print(f"用户: {text}")
        try:
            reply, action = llm.chat(text)
            print(f"回复: {reply}")
            print(f"动作: {action}")
        except Exception as e:
            print(f"错误: {e}")
        print("-" * 40)
        time.sleep(1)


if __name__ == "__main__":
    main()
