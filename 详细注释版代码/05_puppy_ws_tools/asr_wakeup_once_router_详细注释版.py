#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
唤醒式一次性语音识别路由模块 - 详细注释版

功能概述:
    这是一个结合了唤醒词检测的一次性语音识别路由程序。
    用户需要先说出唤醒词(如"小狗"),然后再说出具体的命令或问题。
    程序识别后会将内容路由到控制或聊天系统。

工作原理:
    1. 录制一段固定时长(4秒)的音频
    2. 使用Vosk离线语音识别模型将音频转为文字
    3. 检测文字中是否包含唤醒词
    4. 如果包含唤醒词,提取唤醒词后的内容
    5. 对提取的内容进行意图分析
    6. 通过ROS2话题发布识别结果

与相关模块的区别:
    ┌─────────────────────┬───────────┬──────────┬───────────┐
    │ 模块                 │ 唤醒词    │ 循环     │ 典型用途  │
    ├─────────────────────┼───────────┼──────────┼───────────┤
    │ asr_once_router     │ 无        │ 否       │ 按钮触发  │
    │ asr_wakeup_once_router │ 有      │ 否       │ 一次性唤醒 │
    │ asr_wakeup_loop_router │ 有      │ 是       │ 持续监听  │
    └─────────────────────┴───────────┴──────────┴───────────┘

唤醒词机制:
    - 为什么要唤醒词: 避免把日常对话误识别为命令
    - 支持的唤醒词: "小狗"、"你好小狗"
    - 使用方式: 先说唤醒词,再说具体命令或问题
    - 示例: "小狗坐下" -> 唤醒词"小狗" + 命令"坐下"

适用场景:
    - 智能音箱风格的语音交互(按需唤醒)
    - 机器人语音控制(需要确认唤醒后再响应)
    - 低功耗语音应用(不需要持续监听)

技术特点:
    - 完全离线: Vosk开源语音识别,无需联网
    - 唤醒检测: 支持多种唤醒词变体
    - 意图路由: 控制命令和聊天内容分开处理

依赖环境:
    - Vosk语音识别库
    - ROS2环境(用于话题发布)
    - ALSA音频驱动(arecord命令)

硬件平台: 树莓派/嵌入式Linux设备 + USB麦克风

使用方法:
    直接运行脚本:
    python3 asr_wakeup_once_router.py

    程序会:
    1. 打印使用提示"请直接说：小狗 + 指令/问题"
    2. 录制4秒音频
    3. 识别并检测唤醒词
    4. 路由结果到ROS2话题
    5. 自动退出
"""

import json
import os
import subprocess
import tempfile
import time
import wave

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from vosk import Model, KaldiRecognizer


# ===========================================
# 配置参数
# ===========================================

# Vosk语音识别模型路径
# 推荐使用vosk-model-small-cn-0.22(小模型,中文,约40MB)
MODEL_PATH = "/app/puppy_ws/models/vosk-model-small-cn-0.22"

# ALSA音频设备标识
DEVICE = "plughw:0,0"

# 录音时长(秒)
# 设置为4秒,适合说出"小狗+命令"
RECORD_SECONDS = 4

# 音频采样率(Hz)
# Vosk模型要求16kHz采样率
SAMPLE_RATE = 16000

# 音频通道数
# 1表示单声道,Vosk要求单声道
CHANNELS = 1

# 唤醒词列表
# 用户需要先说这些词之一,程序才会处理后续内容
WAKEUP_KEYWORDS = [
    "小狗",      # 最简单的唤醒词
    "你好小狗",  # 带礼貌前缀的唤醒词
]


def record_wav(wav_path: str, seconds: int):
    """
    录制音频并保存为WAV文件

    功能:
        使用arecord命令从麦克风录制音频

    参数:
        wav_path: 保存的WAV文件路径
        seconds: 录音时长(秒)

    arecord参数说明:
        -D DEVICE: 指定音频设备
        -d SECONDS: 录音时长
        -f FORMAT: 音频格式,S16_LE表示16位小端格式
        -r RATE: 采样率
        -c CHANNELS: 通道数
        -t TYPE: 文件类型,wav
    """
    cmd = [
        "arecord",
        "-D", DEVICE,
        "-d", str(seconds),
        "-f", "S16_LE",
        "-r", str(SAMPLE_RATE),
        "-c", str(CHANNELS),
        "-t", "wav",
        wav_path,
    ]
    subprocess.run(cmd, check=True)


def recognize_wav(model: Model, wav_path: str) -> str:
    """
    识别WAV文件中的语音内容

    功能:
        加载WAV音频文件,使用Vosk模型进行语音识别

    参数:
        model: 加载好的Vosk语音识别模型
        wav_path: WAV文件路径

    返回值:
        str: 识别出的文字内容(已去除空格)

    识别流程:
        1. 打开WAV文件
        2. 验证音频格式(单声道、16位、16kHz)
        3. 创建Kaldi识别器
        4. 分帧读取音频数据
        5. 每帧识别并收集中间结果
        6. 最终结果合并返回
    """
    wf = wave.open(wav_path, "rb")

    # 音频格式校验
    if wf.getnchannels() != 1:
        raise RuntimeError(f"音频不是单声道: {wf.getnchannels()}")
    if wf.getsampwidth() != 2:
        raise RuntimeError(f"音频不是16bit: {wf.getsampwidth()}")
    if wf.getframerate() != SAMPLE_RATE:
        raise RuntimeError(f"音频采样率不对: {wf.getframerate()}")

    # 创建Kaldi识别器
    rec = KaldiRecognizer(model, wf.getframerate())
    parts = []

    # 分帧读取并识别
    while True:
        # 每次读取约250ms的音频数据
        data = wf.readframes(4000)
        if len(data) == 0:
            break

        # 喂入识别器
        if rec.AcceptWaveform(data):
            # 识别器认为一句话结束,获取中间结果
            result = json.loads(rec.Result())
            text = result.get("text", "").strip()
            if text:
                parts.append(text)

    # 获取最终识别结果
    final_result = json.loads(rec.FinalResult())
    final_text = final_result.get("text", "").strip()
    if final_text:
        parts.append(final_text)

    # 合并所有识别片段
    return "".join(parts).strip()


def extract_after_wakeup(text: str):
    """
    从识别文本中提取唤醒词后的内容

    功能:
        检测文本中是否包含唤醒词
        如果包含,则返回唤醒词之后的内容

    参数:
        text: 原始识别文本

    返回值:
        tuple: (matched, remain)
            - matched: 是否检测到唤醒词
            - remain: 唤醒词之后的内容(如果有)

    示例:
        "小狗今天天气怎么样" -> (True, "今天天气怎么样")
        "你好小狗你在吗" -> (True, "你在吗")
        "今天天气怎么样" -> (False, "今天天气怎么样")
    """
    # 去除空格,统一匹配
    compact = text.replace(" ", "")
    for kw in WAKEUP_KEYWORDS:
        idx = compact.find(kw)
        if idx != -1:
            # 找到唤醒词,提取后续内容
            remain = compact[idx + len(kw):].strip()
            return True, remain
    return False, compact


def route_intent(text: str):
    """
    意图路由函数 - 判断语音命令类型

    功能:
        分析识别出的文字,判断用户意图是控制命令还是聊天内容

    参数:
        text: 识别出的文字

    返回值:
        dict: 包含type和command/text字段
            - type="control": 控制命令,command字段指定具体命令
            - type="chat": 聊天内容

    支持的控制命令:
        - stop: 停止/别动
        - sit: 坐下
        - stand: 站立
        - follow_start: 开始跟随
        - follow_stop: 停止跟随

    示例:
        "坐下" -> {"type": "control", "command": "sit"}
        "今天天气怎么样" -> {"type": "chat"}
    """
    # 去除空格,统一匹配
    compact = text.replace(" ", "")

    # 停止命令检测
    if any(kw in compact for kw in ["停下", "停止", "别动", "不要动"]):
        return {"type": "control", "command": "stop"}

    # 坐下命令检测
    if any(kw in compact for kw in ["坐下", "坐下来", "请坐下"]):
        return {"type": "control", "command": "sit"}

    # 站立命令检测
    if any(kw in compact for kw in ["站立", "站起来", "起来", "请站起来"]):
        return {"type": "control", "command": "stand"}

    # 开始跟随命令检测
    if any(kw in compact for kw in ["开始跟随", "跟着我", "跟随我"]):
        return {"type": "control", "command": "follow_start"}

    # 停止跟随命令检测
    if any(kw in compact for kw in ["停止跟随", "不要跟了", "别跟了"]):
        return {"type": "control", "command": "follow_stop"}

    # 非控制命令,归类为聊天
    return {"type": "chat"}


class WakeupRouterNode(Node):
    """
    唤醒式语音路由ROS2节点

    功能:
        - 发布控制命令到/voice/result_json话题
        - 发布聊天内容到/chat/input_text话题

    话题消息格式:
        /voice/result_json: JSON格式控制命令
            {
                "source": "voice",
                "sub_source": "usb_asr_wakeup_once",
                "command": "sit",
                "text": "小狗坐下",
                "timestamp": 1234567890.123
            }

        /chat/input_text: 纯文本聊天内容
    """

    def __init__(self):
        """
        初始化ROS2节点

        创建两个发布者:
        - voice_pub: 发布控制命令
        - chat_pub: 发布聊天内容
        """
        super().__init__("asr_wakeup_once_router_node")
        self.voice_pub = self.create_publisher(String, "/voice/result_json", 10)
        self.chat_pub = self.create_publisher(String, "/chat/input_text", 10)

    def publish_control(self, text: str, command: str):
        """
        发布控制命令

        参数:
            text: 原始识别文字
            command: 命令标识符(如"sit"、"stand"等)
        """
        payload = {
            "source": "voice",              # 语音来源标识
            "sub_source": "usb_asr_wakeup_once",  # 子来源(唤醒一次性识别)
            "command": command,             # 具体命令
            "text": text,                  # 原始文字
            "timestamp": time.time(),       # 时间戳
        }
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.voice_pub.publish(msg)
        print(f"[ROUTE] control -> {msg.data}")

    def publish_chat(self, text: str):
        """
        发布聊天内容

        参数:
            text: 识别出的文字内容
        """
        payload = {
            "source": "usb_asr_wakeup_once",  # 来源标识
            "text": text,                     # 文字内容
            "timestamp": time.time(),         # 时间戳
        }
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.chat_pub.publish(msg)
        print(f"[ROUTE] chat -> {msg.data}")


def main():
    """
    主函数 - 唤醒式语音识别路由程序入口

    执行流程:
        1. 加载Vosk语音识别模型
        2. 创建临时文件用于存储录音
        3. 打印使用提示
        4. 录制音频
        5. 识别音频内容
        6. 检测唤醒词
        7. 如果检测到唤醒词,路由意图并发布结果
        8. 清理临时文件

    使用注意:
        - 这是唤醒式版本,需要先说唤醒词再说命令
        - 这是一次性程序,运行一次识别一句后退出
        - 如需持续监听,应使用asr_wakeup_loop_router.py
    """
    print(f"[INFO] loading model: {MODEL_PATH}")
    model = Model(MODEL_PATH)

    # 创建临时WAV文件
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name

    try:
        # 打印使用提示
        print(f"[INFO] start recording {RECORD_SECONDS}s ...")
        print("[INFO] 请直接说：小狗 + 指令/问题，例如：小狗坐下 / 小狗你叫什么名字")

        # 1. 录制音频
        record_wav(wav_path, RECORD_SECONDS)

        # 2. 识别音频
        text = recognize_wav(model, wav_path)
        print(f'[ASR] full_text="{text}"')

        # 空文本检查
        if not text.strip():
            print("[INFO] empty text, exit")
            return

        # 3. 唤醒词检测
        matched, remain = extract_after_wakeup(text)
        print(f'[WAKEUP] matched={matched}, remain="{remain}"')

        # 没有检测到唤醒词
        if not matched:
            print("[INFO] wakeup keyword not matched, exit")
            return

        # 唤醒词后没有有效内容
        if not remain:
            print("[INFO] wakeup matched but no command/chat content, exit")
            return

        # 4. 初始化ROS2
        rclpy.init()
        node = WakeupRouterNode()

        # 5. 意图路由
        intent = route_intent(remain)

        # 6. 发布结果
        if intent["type"] == "control":
            node.publish_control(remain, intent["command"])
        else:
            node.publish_chat(remain)

        # 给ROS一点时间把消息发出去
        rclpy.spin_once(node, timeout_sec=0.3)
        node.destroy_node()
        rclpy.shutdown()

    finally:
        # 清理临时文件
        try:
            os.remove(wav_path)
        except Exception:
            pass


if __name__ == "__main__":
    main()
