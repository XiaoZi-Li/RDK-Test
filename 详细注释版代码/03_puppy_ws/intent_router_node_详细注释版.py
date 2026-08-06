#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
intent_router_node.py - 语音意图路由节点
================================================================================

【程序功能】
本程序是Puppy机器人的语音意图路由节点，负责：
1. 接收ASR（自动语音识别）文本
2. 根据关键词匹配判断是控制命令还是聊天内容
3. 将控制命令发往动作控制，将聊天内容发往对话系统

【路由策略】
- 控制类命令（优先）：包含"停下"、"坐下"、"站立"、"跟随"等关键词
- 聊天类内容（默认）：除控制命令外的所有文本

【ROS2接口】
订阅话题：/asr/text (std_msgs/String)
  - 接收ASR识别的文本消息（JSON格式）

发布话题：
  - /voice/result_json: 控制命令输出
  - /chat/input_text: 聊天内容输入

【控制命令关键词】
| 关键词 | 命令 | 说明 |
|--------|------|------|
| 停下、停止、别动、不要动 | stop | 立即停止 |
| 坐下、坐下来、请坐下 | sit | 坐下 |
| 站立、站起来、起来、请站起来 | stand | 站立 |
| 开始跟随、跟着我、跟随我 | follow_start | 开始跟随 |
| 停止跟随、不要跟了、别跟了 | follow_stop | 停止跟随 |

【防抖机制】
同一命令在2秒内重复识别会被忽略，防止误触发

【运行方式】
ros2 run puppy_brain intent_router_node

================================================================================
"""

import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class IntentRouterNode(Node):
    """
    意图路由节点

    【功能】
        1. 接收ASR文本
        2. 关键词匹配判断意图类型
        3. 分发到对应话题
    """

    def __init__(self):
        """节点初始化"""
        super().__init__('intent_router_node')

        # 声明参数：控制命令冷却时间
        self.declare_parameter('control_cooldown_sec', 2.0)
        self.control_cooldown_sec = float(self.get_parameter('control_cooldown_sec').value)

        # 创建订阅者：接收ASR文本
        self.asr_sub = self.create_subscription(
            String,
            '/asr/text',
            self.asr_callback,
            10
        )

        # 创建发布者
        self.voice_pub = self.create_publisher(String, '/voice/result_json', 10)  # 控制命令
        self.chat_pub = self.create_publisher(String, '/chat/input_text', 10)    # 聊天输入

        # 状态变量
        self.last_control_command = None      # 上一次控制命令
        self.last_control_time = 0.0        # 上次命令时间

        self.get_logger().info('intent_router_node started')


    def asr_callback(self, msg: String):
        """
        ASR文本回调函数

        【处理流程】
            1. 解析JSON消息
            2. 提取文本内容
            3. 路由意图判断
            4. 发布到对应话题
        """
        try:
            payload = json.loads(msg.data)
        except Exception:
            self.get_logger().warn('invalid /asr/text json')
            return

        # 提取文本并去除空格
        text = payload.get('text', '').strip()
        compact = text.replace(' ', '')

        if not compact:
            return

        # 路由判断
        intent = self.route_intent(compact)

        # 处理控制类命令
        if intent['type'] == 'control':
            command = intent['command']
            now = time.time()

            # 防抖：同一命令在冷却时间内忽略
            if self.last_control_command == command and (now - self.last_control_time) < self.control_cooldown_sec:
                self.get_logger().info(f'ignore repeated control command: {command}')
                return

            # 构建输出消息
            out = {
                'source': 'voice',
                'sub_source': 'usb_asr_router',
                'command': command,     # 控制命令
                'text': text,           # 原始文本
                'timestamp': now,
            }

            out_msg = String()
            out_msg.data = json.dumps(out, ensure_ascii=False)
            self.voice_pub.publish(out_msg)

            self.last_control_command = command
            self.last_control_time = now

            self.get_logger().info(f'route to control: {out_msg.data}')
            return

        # 处理聊天类内容
        if intent['type'] == 'chat':
            out = {
                'source': 'usb_asr_router',
                'text': text,
                'timestamp': time.time(),
            }

            out_msg = String()
            out_msg.data = json.dumps(out, ensure_ascii=False)
            self.chat_pub.publish(out_msg)

            self.get_logger().info(f'route to chat: {out_msg.data}')
            return


    def route_intent(self, text: str):
        """
        意图路由函数

        【参数】
            text: 压缩后的文本（去除了空格）

        【返回值】
            {'type': 'control', 'command': 'xxx'} 或 {'type': 'chat'}

        【匹配规则】
            遍历所有控制命令关键词列表
            只要文本中包含任一关键词，即判定为控制命令
        """
        # 停止命令
        if any(kw in text for kw in ['停下', '停止', '别动', '不要动']):
            return {'type': 'control', 'command': 'stop'}

        # 坐下命令
        if any(kw in text for kw in ['坐下', '坐下来', '请坐下']):
            return {'type': 'control', 'command': 'sit'}

        # 站立命令
        if any(kw in text for kw in ['站立', '站起来', '起来', '请站起来']):
            return {'type': 'control', 'command': 'stand'}

        # 开始跟随
        if any(kw in text for kw in ['开始跟随', '跟着我', '跟随我']):
            return {'type': 'control', 'command': 'follow_start'}

        # 停止跟随
        if any(kw in text for kw in ['停止跟随', '不要跟了', '别跟了']):
            return {'type': 'control', 'command': 'follow_stop'}

        # 默认进入聊天流程
        return {'type': 'chat'}


def main(args=None):
    """主函数"""
    rclpy.init(args=args)
    node = IntentRouterNode()
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
# 【语音交互流程】
# ================================================================================
# 用户说话
#    ↓
# ASR语音识别 → /asr/text
#    ↓
# intent_router_node 意图分析
#    ↓
# ┌────────────┴────────────┐
# ↓                          ↓
# 控制命令                  聊天内容
# ↓                          ↓
# /voice/result_json       /chat/input_text
# ↓                          ↓
# 动作执行                  对话系统
