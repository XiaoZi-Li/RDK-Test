#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
循环唤醒式语音识别路由模块 - 详细注释版

功能概述:
    这是一个持续运行的语音识别路由程序,采用"唤醒词+命令"的模式。
    程序会持续监听音频,检测到唤醒词(如"小狗")后才开始处理后续语音。

工作原理:
    1. 持续循环录制短音频(3秒)
    2. 每次录制后检测是否包含唤醒词
    3. 检测到唤醒词后,提取后续内容
    4. 判断是控制命令还是聊天内容
    5. 通过ROS2话题发布识别结果

与一次性版本(asr_once_router)的区别:
    - asr_once_router: 录一句就结束,适合单独调用
    - asr_wakeup_loop_router: 持续运行,适合作为后台服务

唤醒词机制:
    - 为什么要唤醒词: 避免把日常对话误识别为命令
    - 唤醒词列表: 小狗、小狗狗、晓狗、小够、小苟、小古等
    - 使用方式: 先说唤醒词,再说具体命令或问题

适用场景:
    - 智能音箱风格的语音交互
    - 机器人语音控制后台服务
    - 需要持续监听的语音应用

技术特点:
    - 完全离线: Vosk开源语音识别,无需联网
    - 唤醒检测: 支持多种唤醒词变体
    - 采样率转换: 支持44.1kHz到16kHz的转换
    - 过滤控制词: USB侧过滤纯控制指令,避免干扰

依赖环境:
    - Vosk语音识别库
    - ROS2环境
    - ALSA音频驱动

硬件平台: 树莓派/嵌入式Linux设备 + USB麦克风
"""

import audioop
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
MODEL_PATH = "/app/puppy_ws/models/vosk-model-small-cn-0.22"

# ALSA音频设备标识
DEVICE = "plughw:0,0"

# 原始录音采样率(Hz)
# USB麦克风通常使用44.1kHz
RECORD_RATE = 44100

# Vosk模型要求的采样率(Hz)
# Vosk模型需要16kHz
VOSK_RATE = 16000

# 音频通道数
CHANNELS = 1

# 音频采样宽度(字节)
SAMPLE_WIDTH = 2

# 一句式模式: 每轮录一整句的时长(秒)
# 设置为3秒,适合说出"小狗+命令"
RECORD_SECONDS = 3

# 循环间隔(秒)
# 每次录完后等待一段时间再录下一轮
LOOP_SLEEP_SEC = 0.15

# USB只做对话,不做控制的关键词列表
# 当检测到这些纯控制词时,不转发给聊天系统
# 这样可以避免用户说"坐下"时被当作聊天处理
CONTROL_ONLY_PHRASES = [
    "坐下", "坐下来",
    "站立", "站起来", "起来",
    "停下", "停止", "别动", "不要动",
]

# 唤醒词列表
# 用户需要先说这些词之一,程序才会处理后续内容
# 支持多种发音变体,提高唤醒成功率
WAKEUP_KEYWORDS = [
    "小狗", "小狗狗", "晓狗", "小够", "小苟", "小古"
]


def record_wav(device: str, wav_path: str, seconds: int, rate: int, channels: int):
    """
    录制音频并保存为WAV文件

    参数说明:
        device: ALSA设备标识,如"plughw:0,0"
        wav_path: 保存的WAV文件路径
        seconds: 录音时长(秒)
        rate: 采样率(Hz)
        channels: 通道数

    arecord参数:
        -D: 指定设备
        -d: 时长
        -f: 格式(S16_LE=16位小端)
        -r: 采样率
        -c: 通道数
        -t: 文件类型
    """
    cmd = [
        "arecord",
        "-D", device,
        "-d", str(seconds),
        "-f", "S16_LE",
        "-r", str(rate),
        "-c", str(channels),
        "-t", "wav",
        wav_path,
    ]
    # 静默执行,不输出arecord的调试信息
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def read_wav_pcm(wav_path: str):
    """
    读取WAV文件的PCM原始数据

    参数:
        wav_path: WAV文件路径

    返回值:
        tuple: (pcm_bytes, framerate)
            - pcm_bytes: PCM原始数据
            - framerate: 采样率

    注意:
        只读取第一个通道的数据
        其他通道数据会被丢弃
    """
    with wave.open(wav_path, "rb") as wf:
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    # 格式校验
    if nchannels != 1:
        raise RuntimeError(f"音频不是单声道: {nchannels}")
    if sampwidth != 2:
        raise RuntimeError(f"音频不是16bit: {sampwidth}")

    return frames, framerate


def resample_pcm_44100_to_16000(pcm_bytes: bytes) -> bytes:
    """
    PCM采样率转换: 44100Hz -> 16000Hz

    功能:
        将44.1kHz的PCM数据转换为16kHz
        这是因为Vosk模型要求16kHz输入

    参数:
        pcm_bytes: 44.1kHz的PCM数据

    返回值:
        bytes: 16kHz的PCM数据

    原理:
        使用audioop.ratecv进行重采样
        该函数会丢弃部分样本以达到目标采样率

    注意:
        重采样会损失部分音频质量
        但对于语音识别影响不大
    """
    converted, _ = audioop.ratecv(
        pcm_bytes,
        SAMPLE_WIDTH,
        CHANNELS,
        RECORD_RATE,   # 源采样率
        VOSK_RATE,     # 目标采样率
        None
    )
    return converted


def recognize_wav(model: Model, wav_path: str) -> str:
    """
    识别WAV文件中的语音内容

    参数:
        model: Vosk模型
        wav_path: WAV文件路径

    返回值:
        str: 识别出的文字

    流程:
        1. 读取WAV的PCM数据
        2. 如果采样率不是16kHz,进行转换
        3. 分帧喂入Kaldi识别器
        4. 收集所有识别结果并合并
    """
    pcm_bytes, src_rate = read_wav_pcm(wav_path)

    # 采样率转换
    if src_rate == VOSK_RATE:
        # 已经是16kHz,直接使用
        pcm_16k = pcm_bytes
    elif src_rate == RECORD_RATE:
        # 需要从44.1kHz转换到16kHz
        pcm_16k = resample_pcm_44100_to_16000(pcm_bytes)
    else:
        raise RuntimeError(f"不支持的音频采样率: {src_rate}")

    # 创建识别器
    rec = KaldiRecognizer(model, VOSK_RATE)
    parts = []

    # 分帧识别
    # 每次处理约250ms的数据(4000 frames * 2 bytes * 1 channel / 16000Hz = 0.5s)
    # 这里step设为4000*2=8000字节
    step = 4000 * 2
    for i in range(0, len(pcm_16k), step):
        data = pcm_16k[i:i + step]
        if not data:
            break

        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            text = result.get("text", "").strip()
            if text:
                parts.append(text)

    # 获取最终结果
    final_result = json.loads(rec.FinalResult())
    final_text = final_result.get("text", "").strip()
    if final_text:
        parts.append(final_text)

    return "".join(parts).strip()


def normalize_text(text: str) -> str:
    """
    文本规范化

    功能:
        去除文本中的空格,统一匹配格式

    参数:
        text: 原始文本

    返回值:
        str: 去除空格后的文本
    """
    return text.replace(" ", "").strip()


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
        "今天天气怎么样" -> (False, "今天天气怎么样")
        "小狗狗你在吗" -> (True, "你在吗")
    """
    compact = normalize_text(text)
    for kw in WAKEUP_KEYWORDS:
        idx = compact.find(kw)
        if idx != -1:
            # 找到唤醒词,提取后续内容
            remain = compact[idx + len(kw):].strip()
            return True, remain
    return False, compact


def is_control_only_text(text: str) -> bool:
    """
    判断是否为纯控制命令

    功能:
        检测文本是否只包含控制命令
        如果是,则不应该转发给聊天系统

    参数:
        text: 文本

    返回值:
        bool: True表示是纯控制命令

    用途:
        USB侧过滤纯控制词,避免干扰主控制链
        比如用户说"坐下",可能只是想测试,不想触发聊天
    """
    compact = normalize_text(text)
    if not compact:
        return False
    return any(kw in compact for kw in CONTROL_ONLY_PHRASES)


class AsrWakeupLoopRouterNode(Node):
    """
    循环唤醒式语音路由ROS2节点

    功能:
        - 持续监听音频输入
        - 检测唤醒词
        - 路由语音命令或聊天内容

    话题发布:
        - /chat/input_text: 聊天内容
        - /voice/raw_asr_text: 原始识别文字
    """

    def __init__(self):
        """
        初始化ROS2节点
        """
        super().__init__("asr_wakeup_loop_router_node")

        # 创建发布者
        self.chat_pub = self.create_publisher(String, "/chat/input_text", 10)
        self.raw_pub = self.create_publisher(String, "/voice/raw_asr_text", 10)

        # 加载语音识别模型
        self.model = Model(MODEL_PATH)

        # 打印启动信息
        self.get_logger().info("asr_wakeup_loop_router_node started")
        self.get_logger().info(f"model={MODEL_PATH}")
        self.get_logger().info(f"device={DEVICE}")
        self.get_logger().info(f"record_rate={RECORD_RATE}, vosk_rate={VOSK_RATE}")
        self.get_logger().info("USB语音链仅做对话入口,不走控制链")
        self.get_logger().info("当前模式:一句式唤醒。请直接说:小狗 + 问题")

        # 状态标志
        self.busy = False  # 防止重入

        # 创建定时器,每0.1秒执行一次loop_once
        self.timer = self.create_timer(0.1, self.loop_once)

    def publish_raw_asr(self, text: str):
        """
        发布原始识别文字

        参数:
            text: 识别出的文字
        """
        msg = String()
        msg.data = text
        self.raw_pub.publish(msg)
        self.get_logger().info(f'publish /voice/raw_asr_text: "{text}"')

    def publish_chat_text(self, text: str):
        """
        发布聊天文本

        参数:
            text: 聊天内容
        """
        msg = String()
        msg.data = text
        self.chat_pub.publish(msg)
        self.get_logger().info(f'publish /chat/input_text: "{text}"')

    def record_and_asr(self, seconds: int) -> str:
        """
        录制并识别音频

        参数:
            seconds: 录音时长

        返回值:
            str: 识别出的文字
        """
        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name

        try:
            # 录制
            self.get_logger().info(f"record: start recording {seconds}s")
            record_wav(DEVICE, wav_path, seconds, RECORD_RATE, CHANNELS)

            # 识别
            text = recognize_wav(self.model, wav_path)
            self.get_logger().info(f'record: text="{text}"')
            return text
        finally:
            # 清理临时文件
            try:
                os.remove(wav_path)
            except Exception:
                pass

    def loop_once(self):
        """
        循环执行一次: 录音 -> 检测唤醒词 -> 路由

        这是定时器回调函数,每0.1秒执行一次

        处理流程:
            1. 如果上一轮还没完成,跳过
            2. 录制音频
            3. 检测唤醒词
            4. 如果没有唤醒词,休眠后返回
            5. 如果唤醒词后没有有效内容,休眠后返回
            6. 如果是纯控制词,过滤掉
            7. 发布到聊天话题
        """
        if self.busy:
            # 上一轮还在执行,跳过
            return

        self.busy = True
        try:
            # 1. 录制并识别
            text = self.record_and_asr(RECORD_SECONDS)

            # 2. 空文本检查
            if not normalize_text(text):
                time.sleep(LOOP_SLEEP_SEC)
                return

            # 3. 唤醒词检测
            matched, remain = extract_after_wakeup(text)
            self.get_logger().info(f'matched={matched}, remain="{remain}"')

            # 4. 没有唤醒词,不处理
            if not matched:
                time.sleep(LOOP_SLEEP_SEC)
                return

            # 5. 唤醒词后没有有效内容,不处理
            if not normalize_text(remain):
                self.get_logger().info("检测到唤醒词,但后面没有有效问题,忽略")
                time.sleep(LOOP_SLEEP_SEC)
                return

            # 6. 纯控制词过滤
            if is_control_only_text(remain):
                self.get_logger().info(f'USB侧过滤固定控制词,不转聊天: "{remain}"')
                time.sleep(LOOP_SLEEP_SEC)
                return

            # 7. 发布到聊天话题
            self.publish_raw_asr(remain)
            self.publish_chat_text(remain)
            time.sleep(0.2)

        except Exception as e:
            self.get_logger().error(f"asr_wakeup_loop_router_node failed: {repr(e)}")
            time.sleep(1.0)
        finally:
            self.busy = False


def main(args=None):
    """
    主函数入口

    功能:
        初始化并启动ROS2节点
        进入事件循环,持续处理语音
    """
    rclpy.init(args=args)
    node = AsrWakeupLoopRouterNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        # Ctrl+C优雅退出
        pass
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
