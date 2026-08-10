#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vision_assistant.py - 视觉问答模块（硅基流动 VLM）

流程：gesture_control.py 的 /snapshot 接口取当前 USB 摄像头帧
     → base64 → SiliconFlow（OpenAI 兼容）视觉模型 → 中文描述

被 voice_assistant.py 调用，处理 "你现在能看到什么" 类语音指令。
取帧走 gesture_control 已持有的摄像头画面，不重复打开 /dev/video0，零冲突。

独立测试：
  python3 vision_assistant.py "你看到了什么"
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

# ============ 视觉类问句识别 ============
# 命中任意一个短语即认为是视觉请求（在快速指令之后、LLM 之前拦截）
VISION_PHRASES = [
    '看到什么', '看见什么', '看到了什么', '看没看到',
    '能看到', '可以看见', '在看什么', '看得到',
    '看看周围', '看看前面', '看看四周', '看看这儿', '看看这里',
    '看一下周围', '看一看周围', '看下周围', '看下前面', '看一下前面',
    '周围有什么', '附近有什么', '前面有什么', '面前有什么',
    '面前是什么', '前面是什么', '眼前是什么', '眼前有什么',
    '观察一下', '观察下',
    '拍张照', '拍个照', '拍一张照片',
    '你眼前', '视野里', '你看到了', '你看到什么',
    '描述一下你看到', '描述你看到', '你在看',
    # ---- 2026-08-10 扩充: 覆盖自然说法 ----
    '你看到了吗', '你能看见', '你看得见', '看得见吗',
    '你眼里', '眼中的', '眼里有什么',
    '识别一下', '识别下', '辨认一下', '辨认下',
    '你面前的', '镜头里', '画面里', '摄像头里',
    '看到了吗', '看见了吗', '看得到吗',
    '看一下我', '看看我', '看我一眼',
]

# 正则兜底: 疑问式视觉问句, 如 "你现在能看到我吗" "前面看得见东西吗"
_VISION_REGEX = re.compile(r'(看|瞧|瞅).{0,8}(吗|么|啥|什么|东西|人|到)[？?]?$')

# 误伤保护: 含运动词的句子优先当运动指令, 不判视觉 (如 "看着我向左转")
_MOTION_WORDS = ('走', '转', '坐', '趴', '停', '站', '前进', '后退',
                 '过来', '过去', '别动', '动一下')


def match_vision_query(text: str) -> str:
    """判断是否为视觉类问句, 返回命中的触发词/规则名, 未命中返回空串"""
    t = text.strip()
    for p in VISION_PHRASES:
        if p in t:
            return p
    # 正则兜底 (带运动词误伤保护)
    if _VISION_REGEX.search(t) and not any(m in t for m in _MOTION_WORDS):
        return 'regex:疑问式看'
    return ''


def is_vision_query(text: str) -> bool:
    """判断是否为视觉类问句"""
    return bool(match_vision_query(text))


class VisionClient:
    """硅基流动视觉模型客户端（OpenAI 兼容格式）"""

    def __init__(self, config: dict):
        v_cfg = config.get("vision", {})
        self.api_key = v_cfg.get("api_key", "")
        self.base_url = v_cfg.get("base_url", "https://api.siliconflow.cn/v1")
        self.model = v_cfg.get("model", "Pro/moonshotai/Kimi-K2.6")
        self.max_tokens = v_cfg.get("max_tokens", 256)
        self.snapshot_url = v_cfg.get("snapshot_url", "http://127.0.0.1:8094/snapshot")
        self.timeout = v_cfg.get("timeout_sec", 30)

        if not self.api_key:
            raise ValueError("config.json 中 vision.api_key 未配置")

        print(f"[VISION] 视觉模型初始化: {self.model}, 取帧: {self.snapshot_url}")

    def fetch_frame(self) -> bytes:
        """从 gesture_control 的快照接口取当前摄像头 JPEG 帧"""
        req = urllib.request.Request(self.snapshot_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
        if len(data) < 1000:
            raise RuntimeError(f"快照数据异常 ({len(data)} 字节), 手势推流可能未运行")
        return data

    def describe(self, question: str, jpeg: bytes) -> str:
        """把图像 + 用户问题发给 VLM，返回中文描述"""
        b64 = base64.b64encode(jpeg).decode()
        prompt = (
            '你是机器狗"小狗"的视觉模块，照片来自它胸前的 USB 摄像头。'
            '请根据照片用简短口语化的中文（一两句话）回答用户的问题，'
            '忽略画面角落叠加的绿色文字和识别框线。'
            f'用户的问题：{question}'
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": prompt},
            ]}],
            "max_tokens": self.max_tokens,
            "temperature": 0.4,
            "stream": False,
            # 关闭思维链, 延迟从 ~11s 降到 ~6s (硅基流动扩展参数)
            "enable_thinking": False,
        }

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")[:200]
            raise RuntimeError(f"VLM API HTTP {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"网络错误: {e.reason}") from e

    def look(self, question: str) -> str:
        """取帧 + 提问，一步完成"""
        t0 = time.time()
        jpeg = self.fetch_frame()
        print(f"[VISION] 取帧成功 ({len(jpeg)} 字节), 调用 VLM...")
        answer = self.describe(question, jpeg)
        print(f"[VISION] VLM 回答完成, 总耗时 {time.time() - t0:.1f}s")
        return answer


# ============ 独立测试 ============
def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "你现在能看到什么？"
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    client = VisionClient(config)

    print("=== 视觉问句识别测试 ===")
    for t in ["你现在能看到什么", "坐下", "看看周围有什么", "往前走", "拍张照片看看",
              "你看到了吗", "你能看见我吗", "看得见东西吗", "看着我向左转",
              "镜头里有什么", "你眼里有什么"]:
        print(f"  '{t}' → {match_vision_query(t) or '(未命中)'}")

    print(f"\n=== VLM 问答测试: {question} ===")
    import time
    t0 = time.time()
    answer = client.look(question)
    print(f"耗时 {time.time()-t0:.1f}s")
    print(f"回答: {answer}")


if __name__ == "__main__":
    main()
