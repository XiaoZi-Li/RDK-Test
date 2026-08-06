#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
voice_control_node.py - I2C语音控制节点
================================================================================

【程序功能】
本程序通过I2C接口与ASR（语音识别）模块通信，采集语音命令并发布控制指令。
支持站立、坐下、停止等基本语音命令。

【硬件连接】
- ASR模块通过I2C连接到机器人
- I2C地址: 0x79
- I2C总线: 5

【支持命令】
| ID | 命令 | 中文 |
|----|------|------|
| 1 | stand | 站立 |
| 2 | sit | 坐下 |
| 3 | stop | 停下 |

【ROS2接口】
发布话题：/voice/result_json (std_msgs/String)
  - JSON格式，包含source、command、text、timestamp

【参数配置】
- i2c_bus: I2C总线号（默认5）
- i2c_addr: I2C地址（默认0x79）
- mode: ASR工作模式（默认1）
- poll_interval: 轮询间隔（默认0.1秒）
- cooldown_sec: 命令冷却时间（默认1.5秒）

【运行方式】
ros2 run puppy_brain voice_control_node

================================================================================
"""

import json
import time
from typing import Dict

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from smbus import SMBus


class ASR:
    """
    ASR语音识别模块驱动类

    【功能】
        通过I2C与ASR硬件模块通信
        支持查询结果、擦除词条、设置模式、添加词条
    """

    # ASR模块寄存器地址
    ASR_RESULT_ADDR = 100       # 结果读取地址
    ASR_WORDS_ERASE_ADDR = 101  # 词条擦除地址
    ASR_MODE_ADDR = 102         # 模式设置地址
    ASR_ADD_WORDS_ADDR = 160   # 添加词条地址

    def __init__(self, address: int, bus_id: int):
        """
        初始化ASR模块

        【参数】
            address: I2C从机地址
            bus_id: I2C总线号
        """
        self.address = address
        self.bus = SMBus(bus_id)


    def close(self):
        """关闭I2C总线"""
        try:
            self.bus.close()
        except Exception:
            pass


    def write_byte(self, val: int) -> bool:
        """
        写入一个字节

        【参数】
            val: 要写入的值

        【返回值】
            成功返回True，失败返回False
        """
        try:
            self.bus.write_byte(self.address, val)
            return True
        except Exception:
            return False


    def get_result(self) -> int:
        """
        获取识别结果

        【返回值】
            识别到的词条ID（1-255）
            -1表示获取失败
            0表示无识别结果
        """
        try:
            ok = self.write_byte(self.ASR_RESULT_ADDR)
            if not ok:
                return -1
            value = self.bus.read_byte(self.address)
            return int(value)
        except Exception:
            return -1


    def erase_words(self) -> bool:
        """
        擦除所有词条

        【返回值】
            成功返回True，失败返回False
        """
        try:
            self.bus.write_byte_data(self.address, self.ASR_WORDS_ERASE_ADDR, 0)
            time.sleep(0.06)  # 等待擦除完成
            return True
        except Exception:
            return False


    def set_mode(self, mode: int) -> bool:
        """
        设置ASR工作模式

        【参数】
            mode: 模式值（1=识别模式）

        【返回值】
            成功返回True，失败返回False
        """
        try:
            self.bus.write_byte_data(self.address, self.ASR_MODE_ADDR, mode)
            time.sleep(0.05)  # 等待模式切换
            return True
        except Exception:
            return False


    def add_words(self, id_num: int, words: str) -> bool:
        """
        添加词条

        【参数】
            id_num: 词条ID（1-255）
            words: 词条文本（拼音格式）

        【返回值】
            成功返回True，失败返回False
        """
        try:
            buf = [id_num]
            for ch in words:
                buf.append(ord(ch))
            self.bus.write_i2c_block_data(self.address, self.ASR_ADD_WORDS_ADDR, buf)
            time.sleep(0.05)  # 等待写入完成
            return True
        except Exception:
            return False



class VoiceControlNode(Node):
    """
    语音控制节点

    【功能】
        1. 初始化I2C ASR模块
        2. 轮询查询识别结果
        3. 发布控制命令
    """

    def __init__(self):
        """节点初始化"""
        super().__init__('voice_control_node')

        # 声明参数
        self.declare_parameter('i2c_bus', 5)
        self.declare_parameter('i2c_addr', 0x79)
        self.declare_parameter('mode', 1)
        self.declare_parameter('init_words', True)
        self.declare_parameter('poll_interval', 0.10)
        self.declare_parameter('cooldown_sec', 1.5)
        self.declare_parameter('debug_log_interval_sec', 1.0)

        # 获取参数
        self.i2c_bus = int(self.get_parameter('i2c_bus').value)
        self.i2c_addr = int(self.get_parameter('i2c_addr').value)
        self.mode = int(self.get_parameter('mode').value)
        self.init_words = bool(self.get_parameter('init_words').value)
        self.poll_interval = float(self.get_parameter('poll_interval').value)
        self.cooldown_sec = float(self.get_parameter('cooldown_sec').value)
        self.debug_log_interval_sec = float(self.get_parameter('debug_log_interval_sec').value)

        # 创建发布者
        self.pub = self.create_publisher(String, '/voice/result_json', 10)

        # 命令ID映射表
        self.id_to_command: Dict[int, Dict[str, str]] = {
            1: {'command': 'stand', 'text': '站立'},
            2: {'command': 'sit', 'text': '坐下'},
            3: {'command': 'stop', 'text': '停下'},
        }

        # 状态变量
        self.last_publish_time = 0.0
        self.last_result_id = None
        self.last_debug_time = 0.0

        # 初始化ASR模块
        self.asr = ASR(self.i2c_addr, self.i2c_bus)

        self.get_logger().info(
            f'voice_control_node start: bus={self.i2c_bus}, addr=0x{self.i2c_addr:02X}, mode={self.mode}'
        )

        # 初始化词条
        if self.init_words:
            self.init_asr_words()

        # 创建定时器：轮询ASR结果
        self.timer = self.create_timer(self.poll_interval, self.poll_asr)


    def init_asr_words(self):
        """
        初始化ASR词条

        【工作】
            1. 擦除现有词条
            2. 设置工作模式
            3. 添加新的词条
        """
        self.get_logger().info('Initializing ASR words...')

        ok1 = self.asr.erase_words()    # 擦除词条
        ok2 = self.asr.set_mode(self.mode)  # 设置模式
        ok3 = self.asr.add_words(1, 'zhan li')  # 站立
        ok4 = self.asr.add_words(2, 'zuo xia')  # 坐下
        ok5 = self.asr.add_words(3, 'ting xia')  # 停下

        self.get_logger().info(
            f'ASR init result: erase={ok1}, set_mode={ok2}, add1={ok3}, add2={ok4}, add3={ok5}'
        )

        self.get_logger().info('ASR words initialized: 1=zhan li, 2=zuo xia, 3=ting xia')


    def publish_result(self, result_id: int, command: str, text: str):
        """
        发布识别结果

        【参数】
            result_id: 词条ID
            command: 命令名称
            text: 文本内容
        """
        now = time.time()
        payload = {
            'source': 'voice',
            'result_id': result_id,
            'command': command,
            'text': text,
            'timestamp': now,
        }

        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.pub.publish(msg)

        self.get_logger().info(f'publish voice: {msg.data}')


    def poll_asr(self):
        """
        轮询ASR模块

        【工作流程】
            1. 查询识别结果
            2. 验证结果有效性
            3. 防抖过滤
            4. 发布命令
        """
        result = self.asr.get_result()
        now = time.time()

        # 定期打印调试信息
        if (now - self.last_debug_time) >= self.debug_log_interval_sec:
            self.get_logger().info(f'ASR raw result={result}')
            self.last_debug_time = now

        # 无效结果
        if result is None or result <= 0:
            return

        # 防抖：同一结果在冷却时间内忽略
        if self.last_result_id == result and (now - self.last_publish_time) < self.cooldown_sec:
            return

        # 未知ID
        if result not in self.id_to_command:
            self.get_logger().warn(f'Unknown ASR result id: {result}')
            self.last_result_id = result
            self.last_publish_time = now
            return

        # 发布命令
        command = self.id_to_command[result]['command']
        text = self.id_to_command[result]['text']

        self.publish_result(result, command, text)
        self.last_result_id = result
        self.last_publish_time = now


    def destroy_node(self):
        """节点销毁"""
        try:
            self.asr.close()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    """主函数"""
    rclpy.init(args=args)
    node = VoiceControlNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

# ================================================================================
# 【I2C通信协议】
# ================================================================================
# ASR模块通过I2C接口通信：
#
# 寄存器地址：
# - 100 (0x64): 读取识别结果
# - 101 (0x65): 擦除词条
# - 102 (0x66): 设置模式
# - 160 (0xA0): 添加词条
#
# 添加词条格式：
# - 第一个字节: 词条ID
# - 后续字节: 拼音字符串（ASCII）
#
# 【注意】
# - 词条使用拼音格式
# - 需要先擦除再添加新词条
