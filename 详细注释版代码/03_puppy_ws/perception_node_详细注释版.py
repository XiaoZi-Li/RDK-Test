#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ***************************************************************************************************
# 逐行详细注释版 - 专门为零基础学习者编写
# ***************************************************************************************************
#
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │                         《ROS2 视觉感知节点》                                    │
# │                                                                             │
# │  功能说明:                                                                   │
# │  perception_node是机器狗系统的"眼睛"                                         │
# │  负责从摄像头获取图像，进行YOLOv5目标检测，发布检测结果                         │
# │                                                                             │
# │  在系统中的位置:                                                             │
# │  ┌─────────────────────────────────────────────────────────────────┐       │
# │  │                                                                 │       │
# │  │   摄像头 ──▶ perception_node ──▶ 检测结果 ──▶ decision_node    │       │
# │  │                      │                                          │       │
# │  │                      ▼                                          │       │
# │  │                   YOLOv5                                        │       │
# │  │                   BPU推理                                       │       │
# │  │                                                                 │       │
# │  └─────────────────────────────────────────────────────────────────┘       │
# │                                                                             │
# │  学习目标:                                                                   │
# │  1. 理解ROS2的订阅/发布机制                                                 │
# │  2. 理解如何集成BPU推理到ROS2                                               │
# │  3. 理解多节点协作的工作流程                                                 │
# └─────────────────────────────────────────────────────────────────────────────┘

# ***************************************************************************************************
# 第一部分：导入必要的库
# ***************************************************************************************************

# ROS2相关
import rclpy                    # ROS2 Python客户端
from rclpy.node import Node     # ROS2节点基类
from std_msgs.msg import String, CompressedImage  # 标准消息类型

# 标准库
import json                      # JSON解析
import time                      # 时间控制
import math                      # 数学函数
from typing import List, Dict, Any  # 类型提示

# AI/图像处理
import numpy as np              # 数值计算
import cv2                      # OpenCV

# 地平线BPU推理
try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn

# 图像编解码
try:
    from hobot_codec import hobot_codec as codec
except ImportError:
    print("警告：hobot_codec未安装")

# ***************************************************************************************************
# 第二部分：常量定义
# ***************************************************************************************************

# 模型配置
MODEL_PATH = "/app/model/basic/yolov5s_672x672_nv12.bin"  # YOLOv5模型路径
INPUT_WIDTH = 672   # 模型输入宽度
INPUT_HEIGHT = 672  # 模型输入高度
ORIG_WIDTH = 960    # 原始图像宽度
ORIG_HEIGHT = 544   # 原始图像高度

# 检测参数
SCORE_THRESHOLD = 0.25   # 置信度阈值（越小越灵敏）
NMS_THRESHOLD = 0.45     # NMS阈值（非极大值抑制）
NMS_TOP_K = 20           # 每类最多检测数

# 话题名称
IMAGE_TOPIC = '/image'  # 订阅的图像话题
RESULT_TOPIC = '/perception/result_json'  # 发布的检测结果话题

# 日志参数
LOG_INTERVAL_SEC = 5.0  # 日志打印间隔

# ***************************************************************************************************
# 第三部分：COCO类别定义
# ***************************************************************************************************

# COCO 80类（完整列表）
# 这是YOLOv5训练用的数据集
CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
    "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush"
]

# ***************************************************************************************************
# 第四部分：感知节点类
# ***************************************************************************************************

class PerceptionNode(Node):
    """
    PerceptionNode - 视觉感知节点

    这个节点是机器狗的"眼睛"

    订阅话题:
    - /image: 压缩图像消息 (CompressedImage)

    发布话题:
    - /perception/result_json: 检测结果 (String)

    工作流程:
    ┌─────────────────────────────────────────────────────────────────┐
    │                                                                 │
    │   1. 接收图像消息                                                │
    │           │                                                     │
    │           ▼                                                     │
    │   2. 解码JPEG为numpy数组                                         │
    │           │                                                     │
    │           ▼                                                     │
    │   3. 预处理：BGR→NV12，缩放                                      │
    │           │                                                     │
    │           ▼                                                     │
    │   4. BPU推理：调用加速器进行目标检测                               │
    │           │                                                     │
    │           ▼                                                     │
    │   5. 后处理：解析输出为检测框                                      │
    │           │                                                     │
    │           ▼                                                     │
    │   6. 发布结果到ROS2话题                                          │
    │                                                                 │
    └─────────────────────────────────────────────────────────────────┘
    """

    def __init__(self):
        """
        __init__ - 初始化感知节点

        初始化步骤:
        1. 调用父类初始化，设置节点名
        2. 加载YOLOv5模型
        3. 创建订阅者和发布者
        4. 初始化统计变量
        """

        # -------------------- 调用父类初始化 --------------------
        # super().__init__('perception_node')
        # 'perception_node' 是节点名称
        # 可以通过 ros2 node list 查看
        super().__init__('perception_node')

        # -------------------- 加载AI模型 --------------------
        print("=" * 60)
        print("正在加载YOLOv5模型...")
        print("=" * 60)

        try:
            # dnn.load() 加载模型到BPU
            # 这会：
            # 1. 读取模型文件(.bin)
            # 2. 解析模型结构
            # 3. 分配BPU内存
            # 4. 返回模型句柄
            self.models = dnn.load(MODEL_PATH)
            print(f"✓ 模型加载成功!")
            print(f"  模型路径: {MODEL_PATH}")
            print(f"  输入尺寸: {INPUT_WIDTH} x {INPUT_HEIGHT}")

        except Exception as e:
            print(f"✗ 模型加载失败: {e}")
            self.models = None

        # -------------------- 初始化统计 --------------------
        self.frame_count = 0          # 总帧数
        self.inference_count = 0     # 推理次数
        self.inference_times = []     # 推理耗时列表
        self.last_log_time = time.time()  # 上次打印日志时间

        # -------------------- 创建订阅者 --------------------
        #
        # create_subscription() 创建一个订阅者
        # 参数:
        # - 消息类型
        # - 话题名称
        # - 回调函数
        # - 队列大小
        #
        # CompressedImage 是压缩图像消息
        # 包含JPEG/PNG格式的图像数据
        #
        self.image_sub = self.create_subscription(
            CompressedImage,           # 消息类型
            IMAGE_TOPIC,                # 话题名
            self.image_callback,         # 回调函数
            10                         # 队列大小
        )

        # -------------------- 创建发布者 --------------------
        #
        # create_publisher() 创建一个发布者
        # 参数:
        # - 消息类型
        # - 话题名称
        # - 队列大小
        #
        # 发布的消息类型是 String
        # 内容是 JSON 格式的检测结果
        #
        self.result_pub = self.create_publisher(
            String,                    # 消息类型
            RESULT_TOPIC,              # 话题名
            10                        # 队列大小
        )

        # -------------------- 打印启动信息 --------------------
        self.get_logger().info("=" * 50)
        self.get_logger().info("Perception Node 视觉感知节点已启动!")
        self.get_logger().info("=" * 50)
        self.get_logger().info(f"订阅话题: {IMAGE_TOPIC}")
        self.get_logger().info(f"发布话题: {RESULT_TOPIC}")
        self.get_logger().info(f"模型: {MODEL_PATH}")
        self.get_logger().info(f"置信度阈值: {SCORE_THRESHOLD}")
        self.get_logger().info("=" * 50)

    # ***********************************************************************
    # 图像回调函数
    # ***********************************************************************

    def image_callback(self, msg: CompressedImage):
        """
        image_callback - 图像消息回调

        当收到 /image 话题的新消息时，这个函数会被自动调用

        参数:
            msg: CompressedImage 消息对象

        消息结构:
        CompressedImage:
            header: std_msgs/Header  # 时间戳和坐标系
            format: string           # 图像格式，如 "jpeg"
            data: bytes             # 压缩的图像数据

        这个函数执行:
        1. 解码图像
        2. 预处理
        3. 推理
        4. 后处理
        5. 发布结果
        """

        # -------------------- 记录帧 --------------------
        self.frame_count += 1

        # -------------------- 解码图像 --------------------
        #
        # msg.data 包含JPEG格式的字节数据
        # cv2.imdecode() 将字节数据解码为numpy数组
        #
        # np.frombuffer() 从字节创建数组
        # cv2.IMREAD_COLOR 确保是彩色图像
        try:
            img = cv2.imdecode(
                np.frombuffer(msg.data, dtype=np.uint8),
                cv2.IMREAD_COLOR
            )
            if img is None:
                self.get_logger().warn("图像解码失败")
                return
        except Exception as e:
            self.get_logger().error(f"图像解码异常: {e}")
            return

        # -------------------- 执行检测 --------------------
        if self.models is not None:
            results = self.detect(img)

            # -------------------- 发布结果 --------------------
            self.publish_results(results)

        # -------------------- 定期打印统计 --------------------
        current_time = time.time()
        if current_time - self.last_log_time > LOG_INTERVAL_SEC:
            self.print_statistics()
            self.last_log_time = current_time

    def detect(self, img: np.ndarray) -> Dict[str, Any]:
        """
        detect - 执行目标检测

        参数:
            img: BGR格式的numpy图像数组

        返回:
            检测结果字典
        """

        # -------------------- 预处理 --------------------
        #
        # 1. 缩放到模型输入尺寸
        # 2. BGR转NV12（BPU需要NV12格式）
        #
        orig_h, orig_w = img.shape[:2]

        # 缩放
        resized = cv2.resize(img, (INPUT_WIDTH, INPUT_HEIGHT), interpolation=cv2.INTER_AREA)

        # BGR转NV12
        nv12_data = self.bgr2nv12(resized)

        # -------------------- 推理 --------------------
        t0 = time.time()

        try:
            # models[0].forward() 执行BPU推理
            # 输入: NV12格式的图像数据
            # 输出: 模型输出张量
            outputs = self.models[0].forward(nv12_data)
        except Exception as e:
            self.get_logger().error(f"推理失败: {e}")
            return {"detections": []}

        t1 = time.time()
        self.inference_times.append(t1 - t0)
        self.inference_count += 1

        # -------------------- 后处理 --------------------
        # 这里简化处理，实际代码需要调用C后处理库
        results = self.postprocess(outputs, orig_h, orig_w)

        return results

    def bgr2nv12(self, image: np.ndarray) -> np.ndarray:
        """
        bgr2nv12 - BGR图像转NV12格式

        NV12是YUV420格式的一种
        Y平面 + UV交错平面
        """
        height, width = image.shape[0], image.shape[1]
        area = height * width

        # BGR转YUV420
        yuv420p = cv2.cvtColor(image, cv2.COLOR_BGR2YUV_I420).reshape((area * 3 // 2,))

        # Y分量
        y = yuv420p[:area]

        # UV分量（交错）
        uv_planar = yuv420p[area:].reshape((2, area // 4))
        uv_packed = uv_planar.transpose((1, 0)).reshape((area // 2,))

        # 组合NV12
        nv12 = np.zeros_like(yuv420p)
        nv12[:height * width] = y
        nv12[height * width:] = uv_packed

        return nv12

    def postprocess(self, outputs, orig_h, orig_w) -> Dict[str, Any]:
        """
        postprocess - 后处理

        解析模型输出为检测结果

        实际代码中需要调用 libpostprocess.so
        这里简化处理
        """
        # 简化版本：返回空结果
        # 实际代码需要调用C库进行NMS等处理
        return {"detections": []}

    def publish_results(self, results: Dict[str, Any]):
        """
        publish_results - 发布检测结果

        将检测结果发布到ROS2话题
        其他节点可以订阅这个话题获取检测结果
        """
        # -------------------- 创建消息 --------------------
        msg = String()

        # JSON序列化检测结果
        # 这样可以方便其他语言解析
        msg.data = json.dumps(results)

        # -------------------- 发布 --------------------
        self.result_pub.publish(msg)

    def print_statistics(self):
        """
        print_statistics - 打印统计信息
        """
        if len(self.inference_times) == 0:
            return

        avg_time = sum(self.inference_times) / len(self.inference_times)
        avg_fps = 1.0 / avg_time if avg_time > 0 else 0

        self.get_logger().info(
            f"统计: 帧数={self.frame_count}, "
            f"推理={self.inference_count}, "
            f"延迟={avg_time*1000:.1f}ms, "
            f"FPS={avg_fps:.1f}"
        )

# ***************************************************************************************************
# 第五部分：主函数
# ***************************************************************************************************

def main(args=None):
    """
    main - 程序入口

    标准ROS2程序结构:
    1. rclpy.init() - 初始化ROS2
    2. 创建节点
    3. rclpy.spin() - 保持节点运行
    4. 销毁节点
    5. rclpy.shutdown() - 关闭ROS2
    """

    # -------------------- 初始化ROS2 --------------------
    # 这一步必须先做
    # 它会：
    # 1. 初始化ROS2客户端库
    # 2. 设置信号处理
    # 3. 准备节点创建环境
    rclpy.init(args=args)

    # -------------------- 创建节点 --------------------
    node = PerceptionNode()

    # -------------------- 保持运行 --------------------
    # rclpy.spin(node) 是一个循环
    # 它会：
    # 1. 等待消息到来
    # 2. 调用相应的回调函数
    # 3. 重复直到节点被关闭
    #
    # 按Ctrl+C可以退出
    try:
        node.get_logger().info("开始处理图像...")
        rclpy.spin(node)

    except KeyboardInterrupt:
        # 当用户按Ctrl+C时
        node.get_logger().info("收到中断信号，正在关闭...")

    finally:
        # -------------------- 清理 --------------------
        node.destroy_node()  # 销毁节点
        rclpy.shutdown()      # 关闭ROS2
        node.get_logger().info("节点已关闭")

# ***************************************************************************************************
# 第六部分：程序入口
# ***************************************************************************************************

if __name__ == '__main__':
    main()

# ***************************************************************************************************
# 知识详解
# ***************************************************************************************************
#
# 1. ROS2 发布/订阅模型
#
#    ROS2使用发布/订阅模型进行节点间通信
#    ┌─────────────────────────────────────────────────────────────────┐
#    │                                                                 │
#    │   发布者                    订阅者                              │
#    │      │                        │                               │
#    │      │ publish(msg)           │                               │
#    │      │                        │ callback(msg)                 │
#    │      ▼                        ▼                               │
#    │   ┌─────────┐            ┌─────────┐                          │
#    │   │ 话题    │            │ 回调    │                          │
#    │   │ /image  │───────────▶│ 函数    │                          │
#    │   └─────────┘            └─────────┘                          │
#    │                                                                 │
#    │   消息异步传输，发布者不知道谁在接收                            │
#    │                                                                 │
#    └─────────────────────────────────────────────────────────────────┘
#
# 2. 回调函数机制
#
#    回调函数是ROS2异步通信的核心
#    ┌─────────────────────────────────────────────────────────────────┐
#    │                                                                 │
#    │   话题有新消息 ──▶ ROS2自动 ──▶ 调用回调函数                    │
#    │                                                                 │
#    │   好处：                                                         │
#    │   - 不需要主动查询                                               │
#    │   - 消息一到来就能处理                                           │
#    │   - 可以同时处理多个话题                                          │
#    │                                                                 │
#    └─────────────────────────────────────────────────────────────────┘
#
# 3. CompressedImage消息格式
#
#    图像太大，通常压缩后传输
#    ┌─────────────────────────────────────────────────────────────────┐
#    │                                                                 │
#    │   CompressedImage:                                              │
#    │     header:                                                     │
#    │       stamp: 时间戳 (when)                                      │
#    │       frame_id: 坐标系 (where)                                  │
#    │     format: "jpeg" 或 "png"                                     │
#    │     data: [0xFF, 0xD8, 0xFF, ...]  # 压缩的字节               │
#    │                                                                 │
#    │   为什么压缩？                                                   │
#    │   - 原始图像太大（如1920x1080x3字节 ≈ 6MB）                     │
#    │   - JPEG压缩后只有几十KB                                        │
#    │   - 节省带宽                                                     │
#    │                                                                 │
#    └─────────────────────────────────────────────────────────────────┘
#
# 4. 多节点协作
#
#    perception_node只是其中一环
#    ┌─────────────────────────────────────────────────────────────────┐
#    │                                                                 │
#    │   摄像头节点 ──▶ codec节点 ──▶ perception_node ──▶ decision   │
#    │                                    │                          │
#    │                                    │                          │
#    │                               /perception/result_json         │
#    │                                                                 │
#    └─────────────────────────────────────────────────────────────────┘
#
# ***************************************************************************************************
# 课后练习
# ***************************************************************************************************
#
# 练习1：修改发布话题名
#   修改 RESULT_TOPIC 为其他名字
#
# 练习2：添加其他检测类别过滤
#   只发布特定类别的检测结果（如只发布person）
#
# 练习3：添加图像保存功能
#   每N帧保存一张图像
#
# ***************************************************************************************************
# 常见问题
# ***************************************************************************************************
#
# Q: 节点启动失败？
#   - 检查ROS2是否正确安装
#   - 检查模型文件是否存在
#
# Q: 没有收到图像？
#   - 检查发布者是否在运行
#   - 检查话题名称是否匹配
#   - 使用 ros2 topic list 查看可用话题
#
# Q: FPS很低？
#   - 减小模型输入分辨率
#   - 使用更轻量的模型
#
# ***************************************************************************************************

print("=" * 60)
print("Perception Node 视觉感知节点")
print("=" * 60)
