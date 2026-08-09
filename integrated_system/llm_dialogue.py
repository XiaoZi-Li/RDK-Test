#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llm_dialogue.py - 云端大模型语音对话与意图识别

通过 DeepSeek API（OpenAI 兼容）实现：
1. 多轮语音对话（保持上下文）
2. 意图识别：从用户语句中提取运动控制指令（支持多指令序列 + 每动作时长）
3. 自然语言回复生成

设计思路（类似 ESP32 小智项目）：
- 端侧只做语音采集 (VAD) + 识别 (Vosk ASR) + 播报 (TTS)
- LLM 推理走云端 API，不占板载算力
- LLM 用 system prompt 约束输出 JSON: {"reply": "...", "actions": [...]}
- actions 为空数组表示纯聊天，有值则按顺序依次执行
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
2. 识别用户的运动控制意图，输出对应的动作序列

你可以控制以下动作（action字段）：
- "forward"   : 前进（持续型，需指定时长）
- "backward"  : 后退（持续型，需指定时长）
- "turn_left"  : 左转（持续型，需指定时长）
- "turn_right" : 右转（持续型，需指定时长）
- "sit"       : 坐下（离散动作）
- "stand"     : 站立（离散动作）
- "crouch"    : 趴下（离散动作）
- "stop"      : 停止

输出规则：
- 必须严格输出 JSON，不要输出任何其他内容：
  {"reply": "你的语音回复", "actions": [{"action": "动作名", "duration": 秒数}, ...]}
- actions 按用户要求的先后顺序排列，会依次执行
- duration 单位是秒，表示该动作执行/保持多久：
  * 持续型动作（前进/后退/转向）：实际运动时长，用户没说明就填 2.5
  * 离散动作（坐下/站立/趴下）：做完后保持等待的时长，用户没说明就填 2
  * 停止：填 0
- 如果用户说了时长（如"前进三秒"），按用户说的填
- 如果用户只要求一个动作，actions 里只有一个元素
- 纯聊天、问问题、闲聊时，actions 为空数组 []
- 回复要简短口语化，像对话一样，不要超过两三句
- 如果用户说的话含糊不清，可以追问

示例：
用户："你好啊" → {"reply": "你好！我是小狗，有什么可以帮你的吗？", "actions": []}
用户："向前走" → {"reply": "好的，我往前走了！", "actions": [{"action": "forward", "duration": 2.5}]}
用户："前进三秒" → {"reply": "好的，前进三秒！", "actions": [{"action": "forward", "duration": 3}]}
用户："停下" → {"reply": "好的，我停下来了。", "actions": [{"action": "stop", "duration": 0}]}
用户："坐下" → {"reply": "好的，我坐下了。", "actions": [{"action": "sit", "duration": 2}]}
用户："先坐下再站起来" → {"reply": "好的，我先坐下，再站起来！", "actions": [{"action": "sit", "duration": 2}, {"action": "stand", "duration": 0}]}
用户："坐下，五秒钟之后站起来" → {"reply": "好的，我坐下五秒后站起来。", "actions": [{"action": "sit", "duration": 5}, {"action": "stand", "duration": 0}]}
用户："前进两秒然后左转" → {"reply": "好的，先前进两秒，再左转。", "actions": [{"action": "forward", "duration": 2}, {"action": "turn_left", "duration": 2.5}]}
用户："介绍一下你自己" → {"reply": "我是小狗，一只智能机器狗。我能听懂你的话，会走路、坐下，还能陪你聊天！", "actions": []}
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

    @staticmethod
    def _normalize_actions(data: dict) -> list:
        """把 LLM 返回的 JSON 归一化为动作列表 [{action, duration}, ...]

        兼容三种格式:
        1) {"actions": [{"action": "sit", "duration": 2}, ...]}  新格式
        2) {"actions": ["sit", "stand"]}                          简写
        3) {"action": "sit"}                                      旧单动作格式
        """
        valid = {"forward", "backward", "turn_left", "turn_right",
                 "sit", "stand", "stop", "crouch"}
        actions = []

        raw_actions = data.get("actions")
        if isinstance(raw_actions, list):
            for item in raw_actions:
                if isinstance(item, str):
                    name = item.strip().lower()
                    duration = None
                elif isinstance(item, dict):
                    name = str(item.get("action", "")).strip().lower()
                    duration = item.get("duration")
                else:
                    continue
                if name in ("null", "none", ""):
                    continue
                if name not in valid:
                    continue
                # duration 数值化与范围保护
                dur_val = None
                if duration is not None:
                    try:
                        dur_val = max(0.0, min(30.0, float(duration)))
                    except (TypeError, ValueError):
                        dur_val = None
                actions.append({"action": name, "duration": dur_val})
            return actions

        # 旧格式兼容: {"action": "sit"}
        single = data.get("action")
        if isinstance(single, str):
            name = single.strip().lower()
            if name in valid:
                actions.append({"action": name, "duration": None})
        return actions

    def _parse_response(self, raw: str) -> Tuple[str, list]:
        """解析 LLM 返回的 JSON，提取 reply 和动作序列

        Returns:
            (reply_text, actions)  actions 为 [{action, duration}, ...]，纯聊天为空列表
        """
        # 尝试直接解析
        try:
            data = json.loads(raw)
            reply = str(data.get("reply", raw)).strip()
            return reply, self._normalize_actions(data)
        except json.JSONDecodeError:
            pass

        # 如果不是 JSON，尝试从 markdown 代码块中提取
        if "```json" in raw:
            try:
                start = raw.index("```json") + 7
                end = raw.index("```", start)
                data = json.loads(raw[start:end].strip())
                reply = str(data.get("reply", "")).strip()
                return reply or raw, self._normalize_actions(data)
            except (json.JSONDecodeError, ValueError):
                pass

        # 兜底：整段当 reply，无动作
        return raw.strip(), []

    def chat(self, user_text: str) -> Tuple[str, list]:
        """一轮对话

        Args:
            user_text: ASR 识别到的用户文本

        Returns:
            (reply_text, actions)
            - reply_text: LLM 生成的回复文本（用于 TTS 播报）
            - actions: 动作序列 [{action, duration}, ...]，按顺序执行，纯聊天为空列表
        """
        # 构造消息列表
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_text})

        # 调用 API
        raw = self._call_api(messages)

        # 解析
        reply, actions = self._parse_response(raw)

        # 更新历史
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": raw})
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-(self.max_history * 2):]

        return reply, actions

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
        "前进三秒",
        "介绍一下你自己",
        "坐下",
        "先坐下再站起来",
        "站起来然后再坐下",
        "前进两秒然后左转",
        "你叫什么名字？",
    ]

    print("\n=== LLM 对话测试 ===\n")
    for text in test_cases:
        print(f"用户: {text}")
        try:
            reply, actions = llm.chat(text)
            print(f"回复: {reply}")
            print(f"动作序列: {actions}")
        except Exception as e:
            print(f"错误: {e}")
        print("-" * 40)
        time.sleep(1)


if __name__ == "__main__":
    main()
