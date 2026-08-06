#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
usb_asr_text_node.py - USB声卡ASR语音识别节点
================================================================================

【程序功能】
本程序使用Vosk离线语音识别引擎，通过USB声卡采集音频并进行实时语音识别。
识别结果以JSON格式发布到ROS2话题，供其他节点使用。

【技术特点】
1. 离线识别：使用Vosk轻量级模型，无需联网
2. 实时处理：边录音边识别，低延迟输出
3. 中文支持：使用中文模型（vosk-model-small-cn）
4. 循环采集：定时采集音频并识别

【依赖】
- Vosk语音识别库
- arecord音频录制工具
- USB声卡（plughw:0,0）

【ROS2接口】
发布话题：/asr/text (std_msgs/String)
  - JSON格式，包含source、text、timestamp

【参数配置】
- device: 音频设备（默认 plughw:0,0）
- record_seconds: 每次录制时长（默认3秒）
- sample_rate: 采样率（默认16000Hz）
- model_path: Vosk模型路径
- min_text_length: 最小文本长度（默认1）

【运行方式】
ros2 run puppy_brain usb_asr_text_node

================================================================================
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


class UsbAsrTextNode(Node):
    """
    USB声卡ASR语音识别节点

    【功能】
        1. 初始化Vosk模型
        2. 定时采集音频
        3. 实时语音识别
        4. 发布识别结果
    """

    def __init__(self):
        """节点初始化"""
        super().__init__('usb_asr_text_node')

        # 声明参数
        self.declare_parameter('device', 'plughw:0,0')
        self.declare_parameter('record_seconds', 3)
        self.declare_parameter('sample_rate', 16000)
        self.declare_parameter('channels', 1)
        self.declare_parameter('model_path', '/app/puppy_ws/models/vosk-model-small-cn-0.22')
        self.declare_parameter('loop_sleep_sec', 0.5)
        self.declare_parameter('min_text_length', 1)

        # 获取参数
        self.device = str(self.get_parameter('device').value)
        self.record_seconds = int(self.get_parameter('record_seconds').value)
        self.sample_rate = int(self.get_parameter('sample_rate').value)
        self.channels = int(self.get_parameter('channels').value)
        self.model_path = str(self.get_parameter('model_path').value)
        self.loop_sleep_sec = float(self.get_parameter('loop_sleep_sec').value)
        self.min_text_length = int(self.get_parameter('min_text_length').value)

        # 创建发布者
        self.pub = self.create_publisher(String, '/asr/text', 10)

        # 加载Vosk模型
        self.get_logger().info(f'Loading Vosk model: {self.model_path}')
        self.model = Model(self.model_path)
        self.get_logger().info(
            f'usb_asr_text_node started: device={self.device}, '
            f'record_seconds={self.record_seconds}, sample_rate={self.sample_rate}'
        )

        # 状态变量
        self.busy = False

        # 创建定时器：每0.1秒执行一次循环
        self.timer = self.create_timer(0.1, self.loop_once)


    def loop_once(self):
        """
        定时循环：录制并识别一次音频

        【处理流程】
            1. 检查是否忙碌（防止重叠处理）
            2. 录制音频到临时文件
            3. 识别音频
            4. 发布结果
        """
        if self.busy:
            return

        self.busy = True
        try:
            # 录制并识别
            text = self.record_and_recognize_once().strip()
            self.get_logger().info(f'ASR text: "{text}"')

            # 过滤短文本
            if len(text.replace(' ', '')) < self.min_text_length:
                time.sleep(self.loop_sleep_sec)
                return

            # 构建并发布消息
            payload = {
                'source': 'usb_asr',      # 来源标识
                'text': text,              # 识别文本
                'timestamp': time.time(),   # 时间戳
            }

            msg = String()
            msg.data = json.dumps(payload, ensure_ascii=False)
            self.pub.publish(msg)

            self.get_logger().info(f'publish /asr/text: {msg.data}')
            time.sleep(self.loop_sleep_sec)

        except Exception as e:
            self.get_logger().error(f'usb_asr_text_node failed: {repr(e)}')
            time.sleep(1.0)
        finally:
            self.busy = False


    def record_and_recognize_once(self) -> str:
        """
        录制并识别一次音频

        【处理流程】
            1. 创建临时WAV文件
            2. 调用arecord录制音频
            3. 识别WAV文件
            4. 清理临时文件

        【arecord参数】
            -D: 音频设备
            -d: 录制时长
            -f: 采样格式 S16_LE=有符号16位小端
            -r: 采样率
            -c: 声道数
            -t: 文件类型
        """
        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            wav_path = f.name

        try:
            # 构建arecord命令
            cmd = [
                'arecord',
                '-D', self.device,
                '-d', str(self.record_seconds),
                '-f', 'S16_LE',          # 有符号16位小端格式
                '-r', str(self.sample_rate),
                '-c', str(self.channels),
                '-t', 'wav',
                wav_path,
            ]

            self.get_logger().info(f'start recording {self.record_seconds}s...')
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # 识别音频
            return self.recognize_wav(wav_path)

        finally:
            # 清理临时文件
            try:
                os.remove(wav_path)
            except Exception:
                pass


    def recognize_wav(self, wav_path: str) -> str:
        """
        识别WAV音频文件

        【参数】
            wav_path: WAV文件路径

        【返回值】
            识别的文本字符串

        【Vosk识别流程】
            1. 打开WAV文件
            2. 创建Kaldi识别器
            3. 分帧识别
            4. 合并结果
        """
        wf = wave.open(wav_path, 'rb')

        # 验证音频格式
        if wf.getnchannels() != 1:
            raise RuntimeError(f'音频不是单声道: {wf.getnchannels()}')
        if wf.getsampwidth() != 2:
            raise RuntimeError(f'音频不是16bit: {wf.getsampwidth()}')
        if wf.getframerate() != self.sample_rate:
            raise RuntimeError(f'音频采样率不对: {wf.getframerate()}')

        # 创建识别器
        rec = KaldiRecognizer(self.model, wf.getframerate())
        text_parts = []

        # 分帧识别
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break

            # 部分结果识别
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                part = result.get('text', '').strip()
                if part:
                    text_parts.append(part)

        # 最终结果
        final_result = json.loads(rec.FinalResult())
        final_text = final_result.get('text', '').strip()
        if final_text:
            text_parts.append(final_text)

        # 合并所有文本
        return ''.join(text_parts).strip()


def main(args=None):
    """主函数"""
    rclpy.init(args=args)
    node = UsbAsrTextNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
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


if __name__ == '__main__':
    main()

# ================================================================================
# 【Vosk语音识别原理】
# ================================================================================
# Vosk是基于Kaldi的开源语音识别引擎，具有以下特点：
#
# 1. 轻量级模型
#    - vosk-model-small-cn: 约45MB
#    - 适合嵌入式和移动设备
#
# 2. 流式识别
#    - 边录音边识别，低延迟
#    - 无需等待整段录音结束
#
# 3. 中文支持
#    - vosk-model-small-cn 支持中文普通话
#    - 识别率约85-90%（取决于音频质量）
#
# 4. 实时性能
#    - 16kHz采样率
#    - 实时率(RTF) < 0.1
