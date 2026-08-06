#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_vision_node.py - AI视觉感知节点（人脸检测与追踪）
================================================================================

【程序功能】
本程序是Puppy机器人ROS2系统中的AI视觉感知节点，核心功能：
1. 通过MIPI摄像头实时捕获视频流
2. 使用YOLOv5s模型进行实时目标检测（主要检测人）
3. 根据人像位置和面积做出追踪决策（停止、左转、右转、行走）
4. 通过ROS2话题发布动作指令给下位机

【系统架构】
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│  MIPI Camera   │────▶│  YOLOv5s BPU  │────▶│  决策逻辑     │
│  (1080x1920)  │     │  (672x672)    │     │  (距离判断)   │
└────────────────┘     └────────────────┘     └───────────────┘
                                                        │
                                                        ▼
                                              ┌────────────────┐
                                              │ /puppy_action  │
                                              │  (ROS2 Topic)  │
                                              └────────────────┘

【"幽灵记忆"机制】
当人突然消失时，机器人会"记住"最后看到人的位置和面积，
在3秒内如果人重新出现且距离很近，仍然会"刹车"，
防止机器人撞到突然出现的人。

【追踪策略】
- 面积比 > 35%: 目标太近，强制停止
- 面积比 < 15%: 目标太远，向目标方向行走
- 面积比 15%-35%:
  - 目标在左侧(中心<700): 左转
  - 目标在右侧(中心>1220): 右转
  - 目标在中间: 停止

【ROS2接口】
- 发布话题：/puppy_action (std_msgs/String)
  - "stop": 停止
  - "walk": 前进
  - "turn_left": 左转
  - "turn_right": 右转

【运行方式】
# 启动ROS2核心
ros2 run puppy_brain ai_vision_node

# 或通过launch文件启动完整系统
ros2 launch puppy_brain full_system.launch.py

================================================================================
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

import threading
import queue
import time
import numpy as np
import json
import ctypes

try:
    from hobot_vio import libsrcampy as srcampy
except:
    from hobot_vio_rdkx5 import libsrcampy as srcampy

try:
    from hobot_dnn import pyeasy_dnn as dnn
except:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn


# ================================================================================
# C结构体定义 - 与BPU驱动和YOLOv5后处理库交互
# ================================================================================

class hbSysMem_t(ctypes.Structure):
    """BPU系统内存结构体"""
    _fields_ = [("phyAddr",ctypes.c_double), ("virAddr",ctypes.c_void_p), ("memSize",ctypes.c_int)]

class hbDNNQuantiShift_yt(ctypes.Structure):
    """量化位移参数"""
    _fields_ = [("shiftLen",ctypes.c_int), ("shiftData",ctypes.c_char_p)]

class hbDNNQuantiScale_t(ctypes.Structure):
    """量化比例参数"""
    _fields_ = [("scaleLen",ctypes.c_int), ("scaleData",ctypes.POINTER(ctypes.c_float)), ("zeroPointLen",ctypes.c_int), ("zeroPointData",ctypes.c_char_p)]

class hbDNNTensorShape_t(ctypes.Structure):
    """张量形状"""
    _fields_ = [("dimensionSize",ctypes.c_int * 8), ("numDimensions",ctypes.c_int)]

class hbDNNTensorProperties_t(ctypes.Structure):
    """张量属性"""
    _fields_ = [
        ("validShape",hbDNNTensorShape_t), ("alignedShape",hbDNNTensorShape_t),
        ("tensorLayout",ctypes.c_int), ("tensorType",ctypes.c_int),
        ("shift",hbDNNQuantiShift_yt), ("scale",hbDNNQuantiScale_t),
        ("quantiType",ctypes.c_int), ("quantizeAxis", ctypes.c_int),
        ("alignedByteSize",ctypes.c_int), ("stride",ctypes.c_int * 8)
    ]

class hbDNNTensor_t(ctypes.Structure):
    """BPU张量"""
    _fields_ = [("sysMem",hbSysMem_t * 4), ("properties",hbDNNTensorProperties_t)]

class Yolov5PostProcessInfo_t(ctypes.Structure):
    """YOLOv5后处理参数"""
    _fields_ = [
        ("height",ctypes.c_int), ("width",ctypes.c_int),
        ("ori_height",ctypes.c_int), ("ori_width",ctypes.c_int),
        ("score_threshold",ctypes.c_float), ("nms_threshold",ctypes.c_float),
        ("nms_top_k",ctypes.c_int), ("is_pad_resize",ctypes.c_int)
    ]


# ================================================================================
# 加载YOLOv5后处理库
# ================================================================================

libpostprocess = ctypes.CDLL('/usr/lib/libpostprocess.so')
get_Postprocess_result = libpostprocess.Yolov5PostProcess
get_Postprocess_result.argtypes = [ctypes.POINTER(Yolov5PostProcessInfo_t)]
get_Postprocess_result.restype = ctypes.c_char_p

def get_TensorLayout(Layout):
    """Layout转换"""
    return int(2) if Layout == "NCHW" else int(0)


# ================================================================================
# VisionNode - 视觉感知节点类
# ================================================================================

class VisionNode(Node):
    """
    视觉感知节点

    【功能】
        1. 初始化摄像头和AI模型
        2. 启动三个工作线程（摄像头、AI推理、决策）
        3. 通过ROS2发布动作指令
    """

    def __init__(self):
        """节点初始化"""
        super().__init__('ai_vision_node')

        # 创建发布者：发布动作指令到/puppy_action话题
        self.publisher = self.create_publisher(String, '/puppy_action', 10)
        self.get_logger().info("AI Vision Node Started")

        # 创建队列：用于线程间数据传递
        self.frame_queue = queue.Queue(maxsize=3)    # 原始帧队列
        self.result_queue = queue.Queue(maxsize=3)  # 检测结果队列

        # 动作状态管理
        self.last_action = "none"      # 上一次执行的动作
        self.last_send_time = 0       # 上次发送时间（用于防抖）
        self.last_log_time = 0        # 上次日志时间（控制日志频率）

        # 幽灵记忆机制参数
        self.last_person_time = 0.0      # 最后一次看到人的时间
        self.last_person_area = 0.0      # 最后一次看到人时的面积比
        self.ghost_memory_time = 3.0    # 幽灵记忆持续时间（秒）

        # 加载YOLOv5s模型
        self.get_logger().info("Loading YOLO model")
        self.models = dnn.load('/app/model/basic/yolov5s_672x672_nv12.bin')

        # 初始化MIPI摄像头
        self.cam = srcampy.Camera()
        self.cam.open_cam(0, -1, -1, [672,1920], [672,1080],1080,1920)

        # 配置YOLOv5后处理参数
        self.post_info = Yolov5PostProcessInfo_t()
        self.post_info.height = 672
        self.post_info.width = 672
        self.post_info.ori_height = 1080
        self.post_info.ori_width = 1920
        self.post_info.score_threshold = 0.25   # 置信度阈值25%
        self.post_info.nms_threshold = 0.45     # NMS阈值45%
        self.post_info.nms_top_k = 20           # 最多20个检测框
        self.post_info.is_pad_resize = 1        # 使用填充方式resize

        # 启动三个工作线程
        threading.Thread(target=self.camera_thread, daemon=True).start()
        threading.Thread(target=self.ai_thread, daemon=True).start()
        threading.Thread(target=self.decision_thread, daemon=True).start()


    def camera_thread(self):
        """
        摄像头线程

        【功能】
            持续从MIPI摄像头获取图像帧
            将帧数据放入frame_queue供AI推理使用

        【技术要点】
            - 使用np.frombuffer读取原始图像数据
            - .copy()防止底层内存撕裂
            - 队列满时丢弃旧帧
        """
        while True:
            img = self.cam.get_img(2, 672, 672)
            if img is None:
                continue

            # 防止底层内存撕裂，必须保留.copy()
            frame = np.frombuffer(img, dtype=np.uint8).copy()
            if not self.frame_queue.full():
                self.frame_queue.put(frame)


    def ai_thread(self):
        """
        AI推理线程

        【功能】
            从frame_queue获取帧
            执行YOLOv5s推理
            调用C库进行后处理
            将结果放入result_queue

        【BPU推理流程】
            1. 构建hbDNNTensor_t数组
            2. 根据量化类型设置正确的指针
            3. 调用Yolov5doProcess后处理
        """
        while True:
            frame = self.frame_queue.get()
            outputs = self.models[0].forward(frame)

            # 构建输出Tensor数组
            output_tensors = (hbDNNTensor_t * len(outputs))()
            for i in range(len(outputs)):
                output_tensors[i].properties.tensorLayout = get_TensorLayout(outputs[i].properties.layout)

                # 根据量化类型设置指针
                if (len(outputs[i].properties.scale_data) == 0):
                    # FLOAT32模型
                    output_tensors[i].properties.quantiType = 0
                    output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                        outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                        ctypes.c_void_p)
                else:
                    # INT8量化模型
                    output_tensors[i].properties.quantiType = 2
                    output_tensors[i].properties.scale.scaleData = outputs[i].properties.scale_data.ctypes.data_as(
                        ctypes.POINTER(ctypes.c_float))
                    output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                        outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                        ctypes.c_void_p)

                for j in range(len(outputs[i].properties.shape)):
                    output_tensors[i].properties.validShape.dimensionSize[j] = outputs[i].properties.shape[j]

                # 调用YOLOv5后处理
                libpostprocess.Yolov5doProcess(output_tensors[i], ctypes.pointer(self.post_info), i)

            # 获取并解析结果
            result_str = get_Postprocess_result(ctypes.pointer(self.post_info)).decode('utf-8')
            data = json.loads(result_str[16:])

            if not self.result_queue.full():
                self.result_queue.put(data)


    def decision_thread(self):
        """
        决策线程

        【功能】
            从result_queue获取检测结果
            根据人像位置和面积做出追踪决策
            发布动作指令到/puppy_action话题

        【追踪策略】
            - 面积比 > 35%: 目标太近，停止
            - 面积比 < 15%: 目标太远，向目标方向行走
            - 面积比 15%-35%:
              - 中心x < 700: 左转
              - 中心x > 1220: 右转
              - 其他: 停止
        """
        while True:
            data = self.result_queue.get()

            action = "stop"
            person_detected_this_frame = False

            for result in data:
                name = result['name']

                # 只关注"person"类别
                if name != "person":
                    continue

                person_detected_this_frame = True
                bbox = result['bbox']

                # 确保坐标在有效范围内
                x1 = max(0, int(bbox[0]))
                y1 = max(2, int(bbox[1]))
                x2 = min(1920, int(bbox[2]))
                y2 = min(1080, int(bbox[3]))

                # 计算目标中心点和面积比
                x_center = (x1 + x2) / 2
                box_area = (x2 - x1) * (y2 - y1)
                area_ratio = box_area / (1920 * 1080)

                # 更新幽灵记忆状态
                self.last_person_time = time.time()
                self.last_person_area = area_ratio

                # 根据面积比和位置决策
                if area_ratio > 0.35:
                    action = "stop"  # 太近了，刹车
                elif area_ratio < 0.15:
                    # 比较远，向目标方向行走
                    if x_center < 700:
                        action = "turn_left"
                    elif x_center > 1220:
                        action = "turn_right"
                    else:
                        action = "walk"
                else:
                    # 距离合适，根据左右位置调整方向
                    if x_center < 700:
                        action = "turn_left"
                    elif x_center > 1220:
                        action = "turn_right"
                    else:
                        action = "stop"

                # 控制日志打印频率（每0.2秒一次）
                current_time = time.time()
                if current_time - self.last_log_time > 0.2:
                    self.get_logger().info(f"X={x_center:.0f} | 面积比={area_ratio:.2f} | 动作: {action}")
                    self.last_log_time = current_time

                break  # 只处理第一个检测到的人

            # ==========================================
            # 幽灵记忆防撞逻辑
            # ==========================================
            if not person_detected_this_frame:
                time_since_last_seen = time.time() - self.last_person_time
                # 如果3秒内曾看到过很近的人，仍然停止
                if time_since_last_seen < self.ghost_memory_time and self.last_person_area > 0.35:
                    current_time = time.time()
                    if current_time - self.last_log_time > 0.3:
                        self.get_logger().info(f"幽灵触发: 目标消失前距离很近，强制刹车")
                        self.last_log_time = current_time
                    action = "stop"
                else:
                    action = "stop"

            # ==========================================
            # 防抖发布逻辑
            # ==========================================
            if action != self.last_action and time.time()-self.last_send_time > 0.3:
                msg = String()
                msg.data = action
                self.publisher.publish(msg)
                self.get_logger().info(f"动作下发: 【{action}】")
                self.last_action = action
                self.last_send_time = time.time()


# ================================================================================
# 主函数
# ================================================================================

def main():
    """ROS2节点主入口"""
    rclpy.init()
    node = VisionNode()
    try:
        rclpy.spin(node)
    finally:
        node.cam.close_cam()
        rclpy.shutdown()

if __name__=="__main__":
    main()

# ================================================================================
# 【幽灵记忆机制详解】
# ================================================================================
# 这是一个防止机器人撞到突然出现的人的安全机制
#
# 场景示例：
# 1. 机器人正在追踪一个人，距离适中（面积比约25%）
# 2. 这个人突然蹲下或躲到障碍物后面，消失在摄像头视野中
# 3. 没有幽灵记忆：机器人会继续前进或转向，可能撞到突然起身的人
# 4. 有幽灵记忆：机器人会"记住"最后看到时距离很近，3秒内仍会保持停止
#
# 核心变量：
# - last_person_time: 最后看到人的时间戳
# - last_person_area: 最后看到人时的面积比
# - ghost_memory_time: 记忆持续时间（3秒）
#
# 判断逻辑：
# if (当前没看到人) and (距离上次看到人<3秒) and (上次距离很近):
#     保持停止
# else:
#     正常决策
