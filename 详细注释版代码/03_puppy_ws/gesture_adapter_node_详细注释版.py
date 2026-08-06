#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gesture_adapter_node.py - 手势识别适配器节点
================================================================================

【程序功能】
本程序是Puppy机器人ROS2系统中的手势识别适配器节点。
负责将手势检测节点发布的消息转换为JSON格式，方便其他节点使用。

【消息转换】
输入消息 (ai_msgs/PerceptionTargets):
  - 包含手势类型和跟踪ID
  - 来自 /hobot_hand_gesture_detection 话题

输出消息 (std_msgs/String):
  - JSON格式字符串
  - 发布到 /gesture/result_json 话题

【ROS2话题通信】
┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│  手势检测节点        │────▶│  gesture_adapter    │────▶│  决策/控制节点     │
│  /hobot_hand_...     │     │  格式转换           │     │  /gesture/result    │
└──────────────────────┘     └──────────────────────┘     └──────────────────────┘

【支持的手势类型】
- open_palm: 张开手掌
- fist: 握拳
- index_finger_up: 食指向上
- index_finger_down: 食指向下
- ok_sign: OK手势
- etc.

【参数配置】
- input_topic: 输入话题名（默认 /hobot_hand_gesture_detection）
- output_topic: 输出话题名（默认 /gesture/result_json）

【运行方式】
# 默认参数启动
ros2 run puppy_brain gesture_adapter_node

# 自定义话题名
ros2 run puppy_brain gesture_adapter_node --ros-args -p input_topic:=/my_gesture -p output_topic:=/my_output

================================================================================
"""

import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from ai_msgs.msg import PerceptionTargets


class GestureAdapterNode(Node):
    """
    手势识别适配器节点

    【功能】
        订阅手势检测话题
        提取手势类型和跟踪ID
        转换为JSON格式并发布
    """

    def __init__(self):
        """
        节点初始化

        【工作】
            1. 声明和获取参数
            2. 创建订阅者和发布者
            3. 打印启动信息
        """
        super().__init__('gesture_adapter_node')

        # 声明参数
        self.declare_parameter('input_topic', '/hobot_hand_gesture_detection')
        self.declare_parameter('output_topic', '/gesture/result_json')

        # 获取参数值
        self.input_topic = self.get_parameter('input_topic').get_parameter_value().string_value
        self.output_topic = self.get_parameter('output_topic').get_parameter_value().string_value

        # 创建发布者
        self.pub = self.create_publisher(String, self.output_topic, 10)

        # 创建订阅者
        self.sub = self.create_subscription(
            PerceptionTargets,
            self.input_topic,
            self.callback,
            10
        )

        self.get_logger().info(
            f'gesture_adapter_node started. input={self.input_topic}, output={self.output_topic}'
        )


    def callback(self, msg: PerceptionTargets):
        """
        消息回调函数

        【参数】
            msg: PerceptionTargets类型的手势检测消息

        【处理流程】
            1. 遍历消息中的所有目标
            2. 查找手势类型的属性
            3. 提取手势值和跟踪ID
            4. 构建JSON并发布
        """
        gesture_value = None
        track_id = None

        # 遍历所有检测到的目标
        for target in msg.targets:
            # 遍历目标的属性列表
            for attr in target.attributes:
                # 查找手势类型的属性
                if attr.type == 'gesture':
                    gesture_value = attr.value  # 手势值（如 "open_palm"）
                    track_id = target.track_id   # 跟踪ID
                    break
            # 找到手势后退出循环
            if gesture_value is not None:
                break

        # 如果没有检测到手势，不发布消息
        if gesture_value is None:
            return

        # 构建输出JSON
        out = {
            'gesture': str(gesture_value),      # 手势名称字符串
            'gesture_value': gesture_value,     # 手势原始值
            'track_id': track_id,               # 跟踪ID
            'source_topic': self.input_topic,   # 源话题（用于调试）
        }

        # 发布JSON字符串消息
        out_msg = String()
        out_msg.data = json.dumps(out, ensure_ascii=False)
        self.pub.publish(out_msg)


def main(args=None):
    """
    主函数

    【工作流程】
        1. 初始化ROS2
        2. 创建节点
        3. 进入主循环
        4. 清理退出
    """
    rclpy.init(args=args)
    node = GestureAdapterNode()
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
# 【ai_msgs/PerceptionTargets 消息格式】
# ================================================================================
# PerceptionTargets 消息包含：
#
# Header header
# Target[] targets          # 检测到的目标列表
#   int32 track_id          # 目标跟踪ID
#   Attribute[] attributes  # 目标属性列表
#     string type           # 属性类型（如 "gesture"）
#     string value           # 属性值（如 "open_palm"）
#
# 本节点只关注 type=="gesture" 的属性，提取其value作为手势识别结果
