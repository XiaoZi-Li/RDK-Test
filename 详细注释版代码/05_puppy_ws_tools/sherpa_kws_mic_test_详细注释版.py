#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sherpa-onnx关键词检测麦克风测试工具 - 详细注释版

功能概述:
    这是一个简单的麦克风实时监听测试工具。
    使用sherpa-onnx进行关键词检测,监听"小狗"唤醒词。
    当检测到唤醒词时,会打印出检测结果。

使用场景:
    - 测试sherpa-onnx关键词检测模型是否正常工作
    - 验证麦克风是否能正常采集音频
    - 测试唤醒词识别效果和灵敏度
    - 开发调试唤醒功能时的辅助工具

技术原理:
    sherpa-onnx是一个高性能的离在线语音识别框架:
    - 基于Transformer编码器-解码器架构
    - 支持关键词检测任务
    - 模型文件小,适合嵌入式设备
    - 使用ONNX格式,跨平台支持

    关键词检测流程:
    1. 音频流持续采集(16kHz,单声道)
    2. 分帧处理(每帧约100ms)
    3. 提取音频特征
    4. 神经网络前向传播
    5. 输出每个关键词的置信度
    6. 超过阈值则判定为检测到

音频参数:
    - 采样率: 16000 Hz
    - 通道数: 1 (单声道)
    - 数据类型: float32
    - 块大小: 1600 samples (约100ms)

依赖环境:
    - sounddevice: 跨平台音频捕获
    - sherpa_onnx: 关键词检测框架

硬件平台: 任何支持Python的设备 + 麦克风

使用方法:
    # 直接运行
    python3 sherpa_kws_mic_test.py

    # 运行后
    # 1. 程序会打印"真唤醒开始监听,直接说:小狗"
    # 2. 对着麦克风说"小狗"
    # 3. 如果检测到,会打印"WAKE DETECTED: ..."
    # 4. 按Ctrl+C退出

唤醒词:
    默认支持检测"小狗"(以及其他预定义关键词)
    可以修改KEYWORDS_FILE来添加自定义唤醒词
"""

import sounddevice as sd
import sherpa_onnx


# ===========================================
# 模型路径配置
# ===========================================

# sherpa-onnx模型基础路径
# 包含编码器、解码器、连接器模型文件
BASE = "/app/puppy_ws/models/sherpa_kws/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"

# 各模型文件路径
# tokens.txt: 词表文件,包含所有可能的识别单元
TOKENS = f"{BASE}/tokens.txt"

# encoder.onnx: 编码器模型,处理输入音频特征
ENCODER = f"{BASE}/encoder-epoch-13-avg-2-chunk-16-left-64.onnx"

# decoder.onnx: 解码器模型,自回归生成关键词序列
DECODER = f"{BASE}/decoder-epoch-13-avg-2-chunk-16-left-64.onnx"

# joiner.onnx: 连接器模型,融合编码器和解码器输出
JOINER = f"{BASE}/joiner-epoch-13-avg-2-chunk-16-left-64.onnx"

# keywords_tokenized.txt: 关键词列表文件
# 每行一个关键词,格式为"关键词\t分数"
KEYWORDS_FILE = "/app/puppy_ws/models/sherpa_kws/keywords_tokenized.txt"

# 音频采样率(Hz)
# sherpa-onnx模型要求16kHz采样率
SAMPLE_RATE = 16000


def main():
    """
    主函数 - 启动关键词检测监听

    执行流程:
        1. 创建关键词检测器(KeywordSpotter)
        2. 创建音频流
        3. 进入无限循环,持续监听

    关键词检测器参数说明:
        - tokens: 词表文件路径
        - encoder/decoder/joiner: 模型文件路径
        - keywords_file: 关键词列表
        - num_threads: CPU线程数
        - provider: 计算设备("cpu"或"cuda")
        - max_active_paths: 解码最大路径数
        - num_trailing_blanks: 结尾空白帧数
        - keywords_score: 关键词默认分数
        - keywords_threshold: 检测阈值(0.0-1.0)

    阈值说明:
        - 值越高,误触发越少,但可能漏检
        - 值越低,灵敏度越高,但误触发增多
        - 默认0.35是经验值
    """
    # 创建关键词检测器
    kws = sherpa_onnx.KeywordSpotter(
        tokens=TOKENS,
        encoder=ENCODER,
        decoder=DECODER,
        joiner=JOINER,
        keywords_file=KEYWORDS_FILE,
        num_threads=1,           # 单线程CPU推理
        provider="cpu",          # 使用CPU计算
        max_active_paths=4,      # 解码路径数
        num_trailing_blanks=1,   # 结尾处理
        keywords_score=1.0,       # 关键词默认分数
        keywords_threshold=0.35,  # 检测阈值
    )

    # 创建流式识别器
    # 每个流维护独立状态,用于连续识别
    stream = kws.create_stream()

    # 打印使用说明
    print("=" * 60)
    print("sherpa-onnx 关键词检测测试工具")
    print("=" * 60)
    print("真唤醒开始监听，直接说：小狗")
    print("按 Ctrl+C 退出")
    print("=" * 60)

    def callback(indata, frames, time_info, status):
        """
        音频流回调函数

        功能:
            当音频块准备好时被调用
            处理音频数据并检测关键词

        参数:
            indata: 输入音频数据,shape=(frames, channels)
            frames: 本次回调的帧数(1600)
            time_info: 时间信息
            status: 状态信息(如overflow)

        处理流程:
            1. 提取第一个通道的音频数据
            2. 将数据送入流式识别器
            3. 如果识别器准备好了,就解码
            4. 获取并打印检测结果
        """
        # 处理状态错误
        if status:
            print(f"[Status] {status}")

        # 提取第一个通道(单声道)
        samples = indata[:, 0]

        # 将音频数据送入流式识别器
        stream.accept_waveform(SAMPLE_RATE, samples)

        # 如果识别器准备好了(有足够数据),就解码
        while kws.is_ready(stream):
            kws.decode_stream(stream)

        # 获取检测结果
        result = kws.get_result(stream)
        if result:
            # 检测到唤醒词
            print(f"WAKE DETECTED: {result}")

    # 创建输入音频流
    # 使用上下文管理器确保正确清理
    with sd.InputStream(
        channels=1,              # 单声道
        samplerate=SAMPLE_RATE,  # 16kHz采样率
        dtype="float32",         # 32位浮点数
        callback=callback,        # 回调函数
        blocksize=1600,          # 每次回调约100ms数据
    ):
        # 无限循环保持程序运行
        # sleep参数为毫秒
        while True:
            sd.sleep(1000)


if __name__ == "__main__":
    main()
