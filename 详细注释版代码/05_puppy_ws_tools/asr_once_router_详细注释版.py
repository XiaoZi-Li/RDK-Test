#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性语音识别路由模块 - 详细注释版

功能概述:
    这是一个一次性语音识别路由程序,用于接收用户的语音命令,
    识别后将其路由到相应的控制或聊天系统。

工作原理:
    1. 录制一段固定时长(4秒)的音频
    2. 使用Vosk离线语音识别模型将音频转为文字
    3. 对文字进行意图分析,判断是控制命令还是聊天内容
    4. 通过ROS2话题发布识别结果

适用场景:
    - 语音控制机器人(站立、坐下、停止等)
    - 语音对话交互
    - 离线环境下的语音识别(无需联网)

技术特点:
    - 完全离线: 使用Vosk开源离线语音识别引擎
    - 中文支持: 使用中文识别模型(vosk-model-small-cn-0.22)
    - 轻量高效: 小模型,适合嵌入式设备

依赖环境:
    - Vosk语音识别库
    - ROS2环境(用于话题发布)
    - ALSA音频驱动(arecord命令)

硬件平台: 树莓派/嵌入式Linux设备 + USB麦克风

使用方法:
    直接运行脚本:
    python3 asr_once_router.py

    程序会:
    1. 加载语音识别模型(约40MB)
    2. 录制4秒音频
    3. 识别并路由结果
    4. 自动退出
"""

import json
import os
import subprocess
import sys
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
# 该模型需要提前下载并放置到此路径
# 下载地址: https://alphacephei.com/vosk/models
# 推荐使用vosk-model-small-cn-0.22(小模型,中文,约40MB)
MODEL_PATH = "/app/puppy_ws/models/vosk-model-small-cn-0.22"

# ALSA音频设备标识
# plughw:0,0 表示第一个声卡的第一个设备
# 可以通过arecord -l命令查看可用设备
DEVICE = "plughw:0,0"

# 录音时长(秒)
# 设置为4秒,适合说出短命令或问题
RECORD_SECONDS = 4

# 音频采样率(Hz)
# Vosk模型要求16kHz采样率
SAMPLE_RATE = 16000

# 音频通道数
# 1表示单声道,Vosk要求单声道
CHANNELS = 1


def record_wav(wav_path: str):
    """
    录制音频并保存为WAV文件

    功能:
        使用arecord命令从麦克风录制音频

    参数:
        wav_path: 保存的WAV文件路径

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
        "-d", str(RECORD_SECONDS),
        "-f", "S16_LE",
        "-r", str(SAMPLE_RATE),
        "-c", str(CHANNELS),
        "-t", "wav",
        wav_path,
    ]
    print(f"[INFO] start recording {RECORD_SECONDS}s ...")
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

    注意:
        Vosk使用流式识别方式,需要分多次喂入数据
        AcceptWaveform返回True表示识别器认为一句话结束
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

    命令词匹配:
        使用"或"逻辑,只要包含任一关键词即匹配
        匹配前会去除空格,避免用户口音或断句问题

    示例:
        "停下" -> {"type": "control", "command": "stop"}
        "小狗狗你在吗" -> {"type": "chat"}
        "我想让你站起来" -> {"type": "control", "command": "stand"}
    """
    # 去除空格,统一匹配
    compact = text.replace(" ", "")

    # 停止命令检测
    # 支持: 停下、停止、别动、不要动
    if any(kw in compact for kw in ["停下", "停止", "别动", "不要动"]):
        return {"type": "control", "command": "stop"}

    # 坐下命令检测
    # 支持: 坐下、坐下来、请坐下
    if any(kw in compact for kw in ["坐下", "坐下来", "请坐下"]):
        return {"type": "control", "command": "sit"}

    # 站立命令检测
    # 支持: 站立、站起来、起来、请站起来
    if any(kw in compact for kw in ["站立", "站起来", "起来", "请站起来"]):
        return {"type": "control", "command": "stand"}

    # 开始跟随命令检测
    # 支持: 开始跟随、跟着我、跟随我
    if any(kw in compact for kw in ["开始跟随", "跟着我", "跟随我"]):
        return {"type": "control", "command": "follow_start"}

    # 停止跟随命令检测
    # 支持: 停止跟随、不要跟了、别跟了
    if any(kw in compact for kw in ["停止跟随", "不要跟了", "别跟了"]):
        return {"type": "control", "command": "follow_stop"}

    # 非控制命令,归类为聊天
    return {"type": "chat"}


class OnceRouterNode(Node):
    """
    一次性语音路由ROS2节点

    功能:
        - 发布控制命令到/voice/result_json话题
        - 发布聊天内容到/chat/input_text话题

    话题消息格式:
        /voice/result_json: JSON格式控制命令
            {
                "source": "voice",
                "sub_source": "usb_asr_once",
                "command": "sit",
                "text": "坐下",
                "timestamp": 1234567890.123
            }

        /chat/input_text: 纯文本聊天内容
            用户说的话语原文
    """

    def __init__(self):
        """
        初始化ROS2节点

        创建两个发布者:
        - voice_pub: 发布控制命令
        - chat_pub: 发布聊天内容
        """
        super().__init__("asr_once_router_node")
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
            "source": "voice",            # 语音来源标识
            "sub_source": "usb_asr_once", # 子来源(一次性识别)
            "command": command,           # 具体命令
            "text": text,                # 原始文字
            "timestamp": time.time(),     # 时间戳
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
            "source": "usb_asr_once",  # 来源标识
            "text": text,              # 文字内容
            "timestamp": time.time(),  # 时间戳
        }
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.chat_pub.publish(msg)
        print(f"[ROUTE] chat -> {msg.data}")


def main():
    """
    主函数 - 一次性语音识别路由程序入口

    执行流程:
        1. 加载Vosk语音识别模型
        2. 创建临时文件用于存储录音
        3. 录制音频
        4. 识别音频内容
        5. 路由意图(控制/聊天)
        6. 发布结果到ROS2话题
        7. 清理临时文件

    使用注意:
        - 这是一次性程序,运行一次识别一句后退出
        - 如需持续监听,应使用循环版本(asr_wakeup_loop_router.py)
    """
    print(f"[INFO] loading model: {MODEL_PATH}")
    model = Model(MODEL_PATH)

    # 创建临时WAV文件
    # delete=False保持文件,供后续读取
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name

    try:
        # 1. 录制音频
        record_wav(wav_path)

        # 2. 识别音频
        text = recognize_wav(model, wav_path)
        print(f'[ASR] text="{text}"')

        # 空文本检查
        if not text.strip():
            print("[INFO] empty text, nothing published")
            return

        # 3. 初始化ROS2
        rclpy.init()
        node = OnceRouterNode()

        # 4. 意图路由
        intent = route_intent(text)

        # 5. 发布结果
        if intent["type"] == "control":
            node.publish_control(text, intent["command"])
        else:
            node.publish_chat(text)

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
