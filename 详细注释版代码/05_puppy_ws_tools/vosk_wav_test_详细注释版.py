#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vosk离线语音识别测试工具 - 详细注释版

功能概述:
    这是一个简单的WAV文件语音识别测试工具。
    用于测试Vosk离线语音识别模型对指定音频文件的识别效果。

使用场景:
    - 测试音频录制质量
    - 验证Vosk模型识别效果
    - 离线语音识别开发调试
    - 识别结果后处理开发

技术特点:
    - 完全离线: 无需网络连接
    - 简单易用: 只需指定WAV文件路径
    - 支持部分识别: 流式输出中间结果
    - 多语言支持: 中文模型vosk-model-small-cn-0.22

依赖环境:
    - vosk: 离线语音识别库
    - wave: WAV文件读取
    - json: 结果解析

硬件平台: 任何支持Python的设备

使用方法:
    # 使用默认测试文件
    python3 vosk_wav_test.py

    # 使用指定文件
    python3 vosk_wav_test.py /path/to/your/audio.wav

    # WAV文件要求:
    # - 采样率: 16000 Hz (必须)
    # - 通道数: 1 (单声道,必须)
    # - 样本宽度: 16位 (必须)
    # - 格式: PCM

    # 可以使用ffmpeg转换格式:
    # ffmpeg -i input.mp3 -ar 16000 -ac 1 -acodec pcm_s16le output.wav
"""

import json
import sys
import wave

from vosk import Model, KaldiRecognizer


# ===========================================
# 配置参数
# ===========================================

# Vosk语音识别模型路径
# 推荐使用vosk-model-small-cn-0.22(小模型,中文,约40MB)
# 模型下载: https://alphacephei.com/vosk/models
MODEL_PATH = "/app/puppy_ws/models/vosk-model-small-cn-0.22"

# 默认WAV文件路径
# 如果运行脚本时没有指定文件,则使用此默认路径
DEFAULT_WAV_PATH = "/tmp/usb_mic_test.wav"


def load_wav_info(wav_path: str) -> dict:
    """
    加载并验证WAV文件信息

    功能:
        打开WAV文件,检查音频格式是否符合要求

    参数:
        wav_path: WAV文件路径

    返回值:
        dict: 包含音频信息的字典
            - nchannels: 通道数
            - sampwidth: 样本宽度(字节)
            - framerate: 采样率
            - nframes: 总帧数
            - duration: 时长(秒)

    异常:
        RuntimeError: 当音频格式不符合要求时抛出

    WAV格式要求:
        - 采样率: 必须16000Hz
        - 通道数: 必须1(单声道)
        - 样本宽度: 必须2字节(16位)
    """
    with wave.open(wav_path, "rb") as wf:
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        nframes = wf.getnframes()
        duration = nframes / framerate

        return {
            "nchannels": nchannels,
            "sampwidth": sampwidth,
            "framerate": framerate,
            "nframes": nframes,
            "duration": duration
        }


def validate_wav_format(wav_path: str) -> tuple:
    """
    验证WAV文件格式是否符合Vosk要求

    功能:
        检查音频文件是否为:
        - 单声道
        - 16位采样
        - 16000Hz采样率

    参数:
        wav_path: WAV文件路径

    返回值:
        tuple: (is_valid, error_message)
            - is_valid: True表示格式正确
            - error_message: 如果错误,描述错误信息

    常见错误:
        - "音频不是单声道"
        - "音频不是16bit"
        - "音频不是16kHz"
    """
    try:
        with wave.open(wav_path, "rb") as wf:
            nchannels = wf.getnchannels()
            if nchannels != 1:
                return False, f"音频不是单声道: channels={nchannels}"

            sampwidth = wf.getsampwidth()
            if sampwidth != 2:
                return False, f"音频不是16bit: sampwidth={sampwidth}"

            framerate = wf.getframerate()
            if framerate != 16000:
                return False, f"音频不是16kHz: rate={framerate}"

            return True, None
    except Exception as e:
        return False, f"无法打开音频文件: {e}"


def recognize_wav(model_path: str, wav_path: str) -> str:
    """
    识别WAV文件中的语音内容

    功能:
        使用Vosk模型对WAV文件进行语音识别

    参数:
        model_path: Vosk模型路径
        wav_path: WAV文件路径

    返回值:
        str: 识别出的文字内容

    识别流程:
        1. 加载Vosk模型
        2. 创建Kaldi识别器
        3. 分帧读取WAV数据
        4. 流式识别,实时输出中间结果
        5. 收集所有片段并合并返回

    识别原理:
        Vosk使用流式识别:
        - AcceptWaveform() 接收一段音频
        - 返回True表示识别器认为一句话结束
        - Result() 获取当前识别结果
        - FinalResult() 获取最终结果
    """
    # 加载模型
    print(f"[INFO] 加载模型: {model_path}")
    model = Model(model_path)

    # 打开WAV文件
    wf = wave.open(wav_path, "rb")

    # 创建识别器
    # 参数为模型和采样率
    rec = KaldiRecognizer(model, wf.getframerate())

    # 收集所有识别片段
    final_text_parts = []

    print(f"[INFO] 开始识别...")
    print("-" * 50)

    # 分帧读取并识别
    # 每次读取4000帧,约250ms(16000Hz * 0.25s)
    while True:
        # 读取音频数据
        data = wf.readframes(4000)

        # 空数据表示文件结束
        if len(data) == 0:
            break

        # 喂入识别器
        if rec.AcceptWaveform(data):
            # 识别器认为一句话结束
            result = json.loads(rec.Result())
            text = result.get("text", "").strip()

            if text:
                # 打印中间结果(带标签)
                print(f"[partial-final] {text}")
                final_text_parts.append(text)

    # 获取最终识别结果
    final_result = json.loads(rec.FinalResult())
    final_text = final_result.get("text", "").strip()

    if final_text:
        print(f"[final-tail] {final_text}")
        final_text_parts.append(final_text)

    print("-" * 50)

    # 合并所有片段
    merged = "".join(final_text_parts).strip()

    return merged


def print_wav_info(wav_path: str, info: dict):
    """
    打印WAV文件信息

    参数:
        wav_path: 文件路径
        info: 音频信息字典
    """
    print(f"WAV文件: {wav_path}")
    print(f"  采样率: {info['framerate']} Hz")
    print(f"  通道数: {info['nchannels']}")
    print(f"  样本宽度: {info['sampwidth'] * 8} 位")
    print(f"  总帧数: {info['nframes']}")
    print(f"  时长: {info['duration']:.2f} 秒")


def main():
    """
    主函数

    执行流程:
        1. 解析命令行参数,获取WAV文件路径
        2. 验证WAV文件格式
        3. 打印WAV文件信息
        4. 调用识别函数
        5. 打印最终结果

    命令行参数:
        sys.argv[1]: WAV文件路径(可选)
        如果不提供,使用默认路径DEFAULT_WAV_PATH
    """
    # 获取WAV文件路径
    # 如果运行时指定了参数,使用参数;否则使用默认值
    wav_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_WAV_PATH

    print("=" * 60)
    print("Vosk 离线语音识别测试工具")
    print("=" * 60)

    # 打印配置信息
    print(f"模型路径: {MODEL_PATH}")
    print(f"音频路径: {wav_path}")
    print()

    # 验证WAV格式
    print("[INFO] 验证音频格式...")
    is_valid, error = validate_wav_format(wav_path)

    if not is_valid:
        print(f"[ERROR] {error}")
        print()
        print("WAV文件要求:")
        print("  - 采样率: 16000 Hz")
        print("  - 通道数: 1 (单声道)")
        print("  - 样本宽度: 16位")
        print()
        print("可以使用ffmpeg转换:")
        print(f"  ffmpeg -i input.wav -ar 16000 -ac 1 -acodec pcm_s16le {wav_path}")
        sys.exit(1)

    # 打印WAV信息
    try:
        info = load_wav_info(wav_path)
        print_wav_info(wav_path, info)
        print()
    except Exception as e:
        print(f"[ERROR] 无法读取音频文件: {e}")
        sys.exit(1)

    # 执行识别
    try:
        result = recognize_wav(MODEL_PATH, wav_path)

        # 打印最终结果
        print()
        print("=" * 60)
        print("最终识别结果")
        print("=" * 60)
        print(result if result else "<空>")
        print("=" * 60)

    except Exception as e:
        print(f"[ERROR] 识别失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
