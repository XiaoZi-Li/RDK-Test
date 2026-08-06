#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式语音唤醒+识别路由模块 - 详细注释版

功能概述:
    这是一个高性能的流式语音识别模块,采用"唤醒词检测+语音识别"的架构。
    使用sherpa-onnx进行实时关键词检测,使用Vosk进行语音识别。
    支持VAD(语音活动检测)来自动检测语音的结束。

技术架构:
    ┌─────────────────────────────────────────────────────────────────────┐
    │                      音频流处理架构                                    │
    ├─────────────────────────────────────────────────────────────────────┤
    │                                                                      │
    │   ┌──────────┐     ┌─────────────┐     ┌────────────┐               │
    │   │ 麦克风    │────▶│ 音频队列    │────▶│ 主循环     │               │
    │   │ 44.1kHz  │     │ (流式缓冲)  │     │            │               │
    │   └──────────┘     └─────────────┘     └──────┬─────┘               │
    │                                                  │                     │
    │           状态机:                                  │                     │
    │   ┌────────────┐    ┌────────────┐    ┌─────────┴──────┐            │
    │   │ WAKE_LISTEN│───▶│ RECORDING  │───▶│ ASR_BUSY       │            │
    │   │ 监听唤醒词  │    │ 录制音频   │    │ 识别并路由     │            │
    │   └────────────┘    └────────────┘    └────────┬───────┘            │
    │                                                  │                     │
    │                    ┌────────────┐               │                     │
    │                    │ COOLDOWN   │◀──────────────┘                     │
    │                    │ 冷却期     │                                    │
    │                    └────────────┘                                    │
    └─────────────────────────────────────────────────────────────────────┘

状态机说明:
    1. WAKE_LISTEN (待命监听):
       - 持续监听音频流
       - 使用sherpa-onnx关键词检测器检测唤醒词
       - 检测到唤醒词后进入RECORDING状态

    2. RECORDING (录制中):
       - 继续从同一音频流录制
       - 使用RMS检测语音活动(VAD)
       - 当检测到静音且达到最小时长时,进入ASR_BUSY
       - 或达到最大录制时长时进入ASR_BUSY

    3. ASR_BUSY (识别中):
       - 将录制的PCM数据转为16kHz
       - 使用Vosk进行离线识别
       - 识别完成后发布结果到ROS2话题
       - 进入COOLDOWN状态

    4. COOLDOWN (冷却期):
       - 防止频繁触发
       - 冷却期间忽略所有音频
       - 冷却结束后回到WAKE_LISTEN状态

技术特点:
    - 流式处理: 音频块(block)方式处理,低延迟
    - 预录缓冲: 保留唤醒词前的音频,避免截断
    - VAD检测: 自动检测语音结束,无需手动控制
    - 实时重采样: 44.1kHz转16kHz
    - 重复命令过滤: 短时间内相同命令会被忽略

依赖环境:
    - sherpa-onnx: 高性能关键词检测
    - vosk: 离线语音识别
    - sounddevice: 音频流捕获
    - ROS2: 消息发布

硬件平台: 树莓派/嵌入式Linux设备 + USB麦克风
"""

import audioop
import json
import queue
import time
from collections import deque

import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

import sounddevice as sd
import sherpa_onnx
from vosk import Model, KaldiRecognizer


# ===========================================
# 模型路径配置
# ===========================================

# sherpa-onnx关键词检测模型路径
# 这是一个中文+英文的关键词检测模型,参数量3M
# 模型来源: Hugging Face sherpa-onnx-kws-zipformer-zh-en-3M
KWS_BASE = "/app/puppy_ws/models/sherpa_kws/sherpa-onnx-kzipformer-zh-en-3M-2025-12-20"
KWS_TOKENS = f"{KWS_BASE}/tokens.txt"
KWS_ENCODER = f"{KWS_BASE}/encoder-epoch-13-avg-2-chunk-16-left-64.onnx"
KWS_DECODER = f"{KWS_BASE}/decoder-epoch-13-avg-2-chunk-16-left-64.onnx"
KWS_JOINER = f"{KWS_BASE}/joiner-epoch-13-avg-2-chunk-16-left-64.onnx"
KWS_KEYWORDS_FILE = "/app/puppy_ws/models/sherpa_kws/keywords_tokenized.txt"

# Vosk语音识别模型路径
ASR_MODEL_PATH = "/app/puppy_ws/models/vosk-model-small-cn-0.22"


# ===========================================
# 音频参数配置
# ===========================================

# 麦克风原生采样率(Hz)
# 大多数USB麦克风支持44.1kHz或48kHz
MIC_SAMPLE_RATE = 44100

# 目标采样率(Hz)
# sherpa-onnx和Vosk都要求16kHz
TARGET_SAMPLE_RATE = 16000

# 音频通道数
CHANNELS = 1

# 音频块大小
# 原来2205(50ms)太紧,改成4410(100ms)
# 这个值影响:
# - 延迟: 越大延迟越高
# - 准确性: 越大可能越准确,但延迟增加
BLOCKSIZE = 4410

# 麦克风设备索引
# 0表示系统默认麦克风
SD_DEVICE_INDEX = 0


# ===========================================
# 状态机定义
# ===========================================

# 待命监听唤醒词状态
STATE_WAKE = "WAKE_LISTEN"

# 正式录制状态
STATE_RECORD = "RECORDING"

# ASR识别忙状态
STATE_ASR = "ASR_BUSY"

# 命令冷却状态
STATE_COOLDOWN = "COOLDOWN"


# ===========================================
# 时间参数配置(秒)
# ===========================================

# 预录缓冲时长
# 保留唤醒词前的音频,避免开头被截断
PRE_ROLL_SEC = 0.5

# 最大录音时长
# 超过此时长强制结束录音
MAX_RECORD_SEC = 5.0

# 最小录音时长
# 必须达到此时长后才检测静音结束
MIN_RECORD_SEC = 0.8

# 静音结束检测时长
# 检测到静音后,等待此时长确认语音已结束
END_SILENCE_SEC = 0.9

# 状态转换冷却时间
COOLDOWN_SEC = 1.5


# ===========================================
# 语音检测阈值
# ===========================================

# RMS语音检测阈值
# 用于VAD(语音活动检测)
# 值越大越严格,需要更大的声音才能触发
RMS_SPEECH_THRESHOLD = 700

# 控制命令重复过滤冷却时间
# 相同命令在此时间内不会重复触发
CONTROL_COOLDOWN_SEC = 2.0


class WakeThenAsrRouterNode(Node):
    """
    流式语音唤醒+识别路由节点

    功能:
        - 实时监听麦克风音频流
        - 使用sherpa-onnx检测唤醒词
        - VAD检测语音开始和结束
        - 使用Vosk进行语音识别
        - 意图路由到控制或聊天系统
    """

    def __init__(self):
        """
        初始化ROS2节点

        初始化流程:
            1. 创建ROS2发布者
            2. 加载sherpa-onnx关键词检测模型
            3. 加载Vosk语音识别模型
            4. 初始化音频队列和状态机
            5. 启动音频流
            6. 启动主循环定时器
        """
        super().__init__('wake_then_asr_router_node')

        # 创建ROS2发布者
        self.voice_pub = self.create_publisher(String, '/voice/result_json', 10)
        self.raw_asr_pub = self.create_publisher(String, '/voice/raw_asr_text', 10)
        self.chat_pub = self.create_publisher(String, '/chat/input_text', 10)

        # 加载sherpa-onnx关键词检测模型
        self.get_logger().info('loading sherpa-onnx keyword spotter...')
        self.kws = sherpa_onnx.KeywordSpotter(
            tokens=KWS_TOKENS,
            encoder=KWS_ENCODER,
            decoder=KWS_DECODER,
            joiner=KWS_JOINER,
            keywords_file=KWS_KEYWORDS_FILE,
            num_threads=1,
            provider='cpu',
            max_active_paths=4,
            num_trailing_blanks=1,
            keywords_score=1.0,
            keywords_threshold=0.35,
        )
        self.kws_stream = self.kws.create_stream()

        # 加载Vosk语音识别模型
        self.get_logger().info(f'loading Vosk ASR model: {ASR_MODEL_PATH}')
        self.asr_model = Model(ASR_MODEL_PATH)

        # 音频队列(用于音频块传递)
        self.input_stream = None
        self.audio_queue = queue.Queue(maxsize=256)

        # 状态机状态
        self.state = STATE_WAKE
        self.cooldown_until = 0.0

        # 控制命令去重
        self.rate_state = None
        self.last_control_command = None
        self.last_control_time = 0.0

        # 警告时间戳
        self.overflow_warn_time = 0.0
        self.queue_full_warn_time = 0.0

        # 预录缓冲计算
        # 计算每个音频块多少秒
        self.chunk_sec = BLOCKSIZE / MIC_SAMPLE_RATE
        # 计算预录需要多少个音频块
        self.pre_roll_chunks = max(1, int(PRE_ROLL_SEC / self.chunk_sec))
        # 预录缓冲队列(FIFO)
        self.pre_roll_buffer = deque(maxlen=self.pre_roll_chunks)

        # 录制状态
        self.record_chunks = []
        self.record_start_time = 0.0
        self.voice_started = False  # 是否检测到语音开始
        self.silence_start_time = None  # 检测到静音的时间

        # 打印启动信息
        self.get_logger().info('wake_then_asr_router_node started')
        self.get_logger().info(f'麦克风原生采样率={MIC_SAMPLE_RATE}, 算法采样率={TARGET_SAMPLE_RATE}')
        self.get_logger().info(f'BLOCKSIZE={BLOCKSIZE}, chunk_sec={self.chunk_sec:.3f}s')
        self.get_logger().info('当前状态:待命监听唤醒词"小狗"')

        # 启动音频流
        self.start_stream()

        # 启动主循环定时器(50Hz)
        self.timer = self.create_timer(0.02, self.main_loop)

    def start_stream(self):
        """
        启动音频流

        使用sounddevice的InputStream建立持续音频采集
        音频通过回调函数传入,避免阻塞
        """
        if self.input_stream is not None:
            return

        # 重新创建音频队列
        self.audio_queue = queue.Queue(maxsize=256)

        # 创建输入流
        self.input_stream = sd.InputStream(
            device=SD_DEVICE_INDEX,  # 麦克风设备索引
            channels=1,              # 单声道
            samplerate=MIC_SAMPLE_RATE,  # 原始采样率44.1kHz
            dtype='int16',           # 16位有符号整数
            callback=self.audio_callback,  # 音频回调函数
            blocksize=BLOCKSIZE,      # 每次回调的采样数
            latency='high',           # 高延迟模式,更稳定
        )
        self.input_stream.start()
        self.get_logger().info('麦克风监听已启动(单流常开模式)')

    def stop_stream(self):
        """
        停止音频流

        安全停止并关闭音频流
        """
        if self.input_stream is None:
            return
        try:
            self.input_stream.stop()
            self.input_stream.close()
        finally:
            self.input_stream = None
        self.get_logger().info('麦克风监听已停止')

    def audio_callback(self, indata, frames, time_info, status):
        """
        音频回调函数

        功能:
            当音频块准备好时被调用
            将音频数据放入队列,供主循环处理

        参数:
            indata: 输入音频数据,shape=(frames, channels)
            frames: 本次回调的帧数
            time_info: 时间信息
            status: 状态信息(如overflow)

        注意:
            - 这个函数在单独的音频线程中运行
            - 必须快速返回,避免阻塞音频
            - 使用put_nowait避免阻塞
        """
        now = time.time()

        # 处理状态错误
        if status:
            if 'overflow' in str(status).lower():
                if now - self.overflow_warn_time > 1.0:
                    self.get_logger().warn(f'input status: {status}')
                    self.overflow_warn_time = now

        # ASR和COOLDOWN状态不处理音频
        if self.state in (STATE_ASR, STATE_COOLDOWN):
            return

        try:
            # 提取第一个通道
            chunk = indata[:, 0].copy()
            # 非阻塞放入队列
            self.audio_queue.put_nowait(chunk)
        except queue.Full:
            # 队列满了,丢弃音频块
            if now - self.queue_full_warn_time > 1.0:
                self.get_logger().warn('audio_queue full, dropping audio chunks')
                self.queue_full_warn_time = now

    def reset_kws(self):
        """
        重置关键词检测器

        在进入冷却状态后调用
        创建新的检测流,避免残留状态
        """
        self.kws_stream = self.kws.create_stream()
        self.rate_state = None

    def reset_record_state(self):
        """
        重置录制状态

        清空录制缓冲和相关变量
        """
        self.record_chunks = []
        self.record_start_time = 0.0
        self.voice_started = False
        self.silence_start_time = None

    def resample_bytes_to_16k(self, pcm_bytes: bytes):
        """
        将PCM字节流从44.1kHz重采样到16kHz

        参数:
            pcm_bytes: 44.1kHz的PCM字节数据

        返回值:
            bytes: 16kHz的PCM字节数据

        注意:
            使用状态ful重采样,保持连续性
        """
        converted, self.rate_state = audioop.ratecv(
            pcm_bytes, 2, 1,  # 样本宽2字节,1通道
            MIC_SAMPLE_RATE, TARGET_SAMPLE_RATE,
            self.rate_state
        )
        return converted

    def resample_full_to_16k(self, pcm_bytes: bytes) -> bytes:
        """
        将PCM字节流从44.1kHz重采样到16kHz(无状态版本)

        参数:
            pcm_bytes: 44.1kHz的PCM字节数据

        返回值:
            bytes: 16kHz的PCM字节数据

        用于:
            录制结束后的一次性重采样
        """
        converted, _ = audioop.ratecv(
            pcm_bytes, 2, 1,
            MIC_SAMPLE_RATE, TARGET_SAMPLE_RATE,
            None  # 无状态
        )
        return converted

    def rms_of_chunk(self, chunk: np.ndarray) -> int:
        """
        计算音频块的RMS(均方根)值

        功能:
            用于VAD(语音活动检测)
            RMS越大表示声音越大

        参数:
            chunk: 音频数据,numpy数组

        返回值:
            int: RMS值
        """
        return audioop.rms(chunk.astype(np.int16).tobytes(), 2)

    def route_intent(self, text: str):
        """
        意图路由函数

        功能:
            分析文字,判断是控制命令还是聊天内容

        参数:
            text: 识别出的文字

        返回值:
            dict: 包含type和command字段
        """
        compact = text.replace(' ', '')

        # 停止命令
        if any(kw in compact for kw in ['停下', '停止', '别动', '不要动']):
            return {'type': 'control', 'command': 'stop'}

        # 坐下命令
        if any(kw in compact for kw in ['坐下', '坐下来', '请坐下']):
            return {'type': 'control', 'command': 'sit'}

        # 站立命令
        if any(kw in compact for kw in ['站立', '站起来', '起来', '请站起来']):
            return {'type': 'control', 'command': 'stand'}

        # 开始跟随命令
        if any(kw in compact for kw in ['开始跟随', '跟着我', '跟随我']):
            return {'type': 'control', 'command': 'follow_start'}

        # 停止跟随命令
        if any(kw in compact for kw in ['停止跟随', '不要跟了', '别跟了']):
            return {'type': 'control', 'command': 'follow_stop'}

        # 默认归类为聊天
        return {'type': 'chat'}

    def publish_control(self, text: str, command: str):
        """
        发布控制命令

        功能:
            - 检查命令冷却期
            - 发布控制命令到ROS2话题

        参数:
            text: 原始识别文字
            command: 命令标识符
        """
        now = time.time()

        # 检查是否在冷却期内
        if self.last_control_command == command and (now - self.last_control_time) < CONTROL_COOLDOWN_SEC:
            self.get_logger().info(f'ignore repeated control command within cooldown: {command}')
            return

        # 构建消息
        payload = {
            'source': 'voice',
            'sub_source': 'usb_wake_asr',
            'result_id': int(now * 1000),
            'command': command,
            'text': text,
            'timestamp': now,
        }

        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.voice_pub.publish(msg)

        # 更新最后命令时间
        self.last_control_command = command
        self.last_control_time = now

        self.get_logger().info(f'route to control: {msg.data}')

    def publish_raw_asr(self, text: str):
        """
        发布原始ASR识别文字

        参数:
            text: 识别出的文字
        """
        msg = String()
        msg.data = text
        self.raw_asr_pub.publish(msg)
        self.get_logger().info(f'publish /voice/raw_asr_text: {text}')

    def publish_chat(self, text: str):
        """
        发布聊天内容

        参数:
            text: 聊天文字
        """
        msg = String()
        msg.data = text
        self.chat_pub.publish(msg)
        self.get_logger().info(f'publish /chat/input_text: {text}')

    def process_wake_chunk(self, chunk: np.ndarray):
        """
        处理待命监听状态的音频块

        功能:
            1. 将音频块加入预录缓冲
            2. 重采样到16kHz
            3. 送入关键词检测器
            4. 如果检测到唤醒词,进入录制状态

        参数:
            chunk: 音频数据块
        """
        # 加入预录缓冲
        self.pre_roll_buffer.append(chunk.copy())

        # 重采样到16kHz
        pcm_44k = chunk.astype(np.int16).tobytes()
        pcm_16k = self.resample_bytes_to_16k(pcm_44k)
        samples = np.frombuffer(pcm_16k, dtype=np.int16).astype(np.float32) / 32768.0

        # 喂入关键词检测器
        self.kws_stream.accept_waveform(TARGET_SAMPLE_RATE, samples)

        # 如果检测器准备好了,就解码
        while self.kws.is_ready(self.kws_stream):
            self.kws.decode_stream(self.kws_stream)

        # 获取检测结果
        result = self.kws.get_result(self.kws_stream)
        if result:
            self.get_logger().info(f'WAKE DETECTED: {result}')
            self.enter_recording()

    def enter_recording(self):
        """
        进入录制状态

        将预录缓冲的内容作为录制开始
        重置录制相关变量
        """
        self.state = STATE_RECORD
        self.record_start_time = time.time()
        self.voice_started = False
        self.silence_start_time = None
        # 预录缓冲作为录制的开始
        self.record_chunks = list(self.pre_roll_buffer)
        self.get_logger().info('进入正式收音态(同一条流,不重开麦克风)')

    def process_record_chunk(self, chunk: np.ndarray):
        """
        处理录制状态的音频块

        功能:
            1. 加入录制缓冲
            2. RMS检测语音活动
            3. 检测是否应该结束录制

        结束条件:
            - 达到最大录制时长
            - 达到最小时长 + 静音检测结束

        参数:
            chunk: 音频数据块
        """
        now = time.time()
        elapsed = now - self.record_start_time

        # 加入录制缓冲
        self.record_chunks.append(chunk.copy())

        # RMS语音活动检测
        rms = self.rms_of_chunk(chunk)

        if rms >= RMS_SPEECH_THRESHOLD:
            # 检测到语音
            self.voice_started = True
            self.silence_start_time = None
        else:
            # 检测到静音
            if self.voice_started and self.silence_start_time is None:
                # 第一次检测到静音后的语音结束
                self.silence_start_time = now

        # 检查是否应该结束录制
        if elapsed >= MAX_RECORD_SEC:
            # 达到最大时长,强制结束
            self.get_logger().info('到达最大录音时长,结束本轮收音')
            self.finish_recording_and_asr()
            return

        if elapsed >= MIN_RECORD_SEC and self.voice_started and self.silence_start_time is not None:
            # 达到最小时长,并且检测到静音结束
            if (now - self.silence_start_time) >= END_SILENCE_SEC:
                self.get_logger().info('检测到尾部静音,结束本轮收音')
                self.finish_recording_and_asr()
                return

    def recognize_pcm_bytes(self, pcm_16k_bytes: bytes) -> str:
        """
        识别PCM字节数据

        功能:
            使用Vosk进行语音识别

        参数:
            pcm_16k_bytes: 16kHz的PCM字节数据

        返回值:
            str: 识别出的文字
        """
        rec = KaldiRecognizer(self.asr_model, TARGET_SAMPLE_RATE)
        parts = []

        # 分块处理
        step = 4000 * 2  # 约500ms
        for i in range(0, len(pcm_16k_bytes), step):
            data = pcm_16k_bytes[i:i + step]
            if not data:
                break
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = result.get('text', '').strip()
                if text:
                    parts.append(text)

        # 获取最终结果
        final_result = json.loads(rec.FinalResult())
        final_text = final_result.get('text', '').strip()
        if final_text:
            parts.append(final_text)

        return ''.join(parts).strip()

    def finish_recording_and_asr(self):
        """
        完成录制并进行ASR识别

        功能:
            1. 将录制的音频拼接
            2. 重采样到16kHz
            3. 调用ASR识别
            4. 路由意图
            5. 进入冷却状态
        """
        self.state = STATE_ASR

        try:
            # 检查录制缓冲是否为空
            if not self.record_chunks:
                self.get_logger().info('record_chunks 为空,返回待命')
                self.enter_cooldown()
                return

            # 拼接所有音频块
            raw_44k = b''.join([c.astype(np.int16).tobytes() for c in self.record_chunks])
            # 重采样到16kHz
            raw_16k = self.resample_full_to_16k(raw_44k)

            # ASR识别
            text = self.recognize_pcm_bytes(raw_16k).strip()
            self.get_logger().info(f'ASR text: "{text}"')

            if text:
                # 发布原始识别结果
                self.publish_raw_asr(text)

                # 意图路由
                intent = self.route_intent(text)
                if intent['type'] == 'control':
                    self.publish_control(text, intent['command'])
                else:
                    self.publish_chat(text)
            else:
                self.get_logger().info('本轮 ASR 为空')

        except Exception as e:
            self.get_logger().error(f'finish_recording_and_asr failed: {repr(e)}')
        finally:
            self.enter_cooldown()

    def enter_cooldown(self):
        """
        进入冷却状态

        功能:
            - 重置录制状态
            - 清空预录缓冲
            - 重置关键词检测器
            - 设置冷却结束时间
        """
        self.reset_record_state()
        self.pre_roll_buffer.clear()
        self.reset_kws()
        self.cooldown_until = time.time() + COOLDOWN_SEC
        self.state = STATE_COOLDOWN
        self.get_logger().info(f'进入冷却态 {COOLDOWN_SEC}s')

    def leave_cooldown_if_needed(self):
        """
        检查是否应该离开冷却状态

        如果当前时间已超过冷却结束时间,
        则回到待命监听状态
        """
        if self.state == STATE_COOLDOWN and time.time() >= self.cooldown_until:
            self.state = STATE_WAKE
            self.get_logger().info('回到待命监听唤醒词"小狗"')

    def main_loop(self):
        """
        主循环

        功能:
            定时器触发,从音频队列取出音频块处理

        处理逻辑:
            1. 检查并更新冷却状态
            2. 如果是ASR或COOLDOWN状态,跳过
            3. 从队列取出音频块
            4. 根据当前状态分发处理
        """
        # 检查是否应该离开冷却状态
        self.leave_cooldown_if_needed()

        # ASR和COOLDOWN状态不处理
        if self.state in (STATE_ASR, STATE_COOLDOWN):
            return

        # 处理队列中的音频块
        processed = 0
        while (not self.audio_queue.empty()) and processed < 24:
            chunk = self.audio_queue.get_nowait()
            processed += 1

            if self.state == STATE_WAKE:
                # 待命监听状态 -> 检测唤醒词
                self.process_wake_chunk(chunk)
            elif self.state == STATE_RECORD:
                # 录制状态 -> VAD检测
                self.process_record_chunk(chunk)

def main(args=None):
    """
    主函数入口
    """
    rclpy.init(args=args)
    node = WakeThenAsrRouterNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.stop_stream()
        except Exception:
            pass
        try:
            node.destroy_node()
        except Exception:
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass

if __name__ == '__main__':
    main()
