#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ***************************************************************************************************
# 逐行详细注释版 - 专门为零基础学习者编写
# ***************************************************************************************************
#
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │                    《YOLOv5目标检测 - 实时摄像头检测》                         │
# │                                                                             │
# │  功能说明:                                                                   │
# │  这是一个完整的实时目标检测程序                                                │
# │  1. 从摄像头读取画面                                                         │
# │  2. 送入YOLOv5模型进行AI推理                                               │
# │  3. 在画面上绘制检测到的目标框和标签                                         │
# │  4. 实时显示结果                                                            │
# │                                                                             │
# │  什么是YOLOv5？                                                            │
# │  YOLOv5是一个极其流行的目标检测神经网络                                      │
# │  可以识别图片中的物体，并给出位置和类别                                       │
# │  "You Only Look Once" - 只需看一次就能检测                                   │
# │                                                                             │
# │  支持检测的物体类别（部分）:                                                  │
# │  人、车、狗、猫、杯子、椅子、手机、书、电脑等80种日常物体                        │
# │                                                                             │
# │  硬件需求:                                                                   │
# │  - 地平线RDK X3/X5开发板                                                   │
# │  - MIPI摄像头或USB摄像头                                                    │
# │  - BPU加速器（用于AI推理加速）                                              │
# │                                                                             │
# │  学习目标:                                                                   │
# │  1. 理解什么是目标检测                                                       │
# │  2. 学会使用Python调用BPU进行AI推理                                         │
# │  3. 理解图像预处理流程                                                       │
# │  4. 理解后处理（解析模型输出）                                              │
# └─────────────────────────────────────────────────────────────────────────────┘

# ***************************************************************************************************
# 第一部分：导入必要的库
# ***************************************************************************************************

# 标准库
import os           # 操作系统相关，如文件路径操作
import time          # 时间控制，如延时和计时
import json          # JSON数据解析，用于处理模型输出
import math          # 数学函数，如弧度转换
import ctypes        # C语言类型接口，用于调用C后处理库
from typing import List, Tuple, Any  # 类型提示，让代码更清晰

# 第三方库
import numpy as np           # 数值计算库，用于矩阵运算
import cv2                   # OpenCV，计算机视觉库，处理图像

# 地平线BPU推理库 - 这是最关键的库！
# 作用：加载AI模型并在BPU加速器上运行推理
try:
    # 尝试导入RDK X3版本
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    # 如果X3版本不存在，尝试RDK X5版本
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn

# 图像输入输出库 - 用于读取摄像头
try:
    from hobot_vio import libsrcampy as srcampy  # RDK X3版本
except ImportError:
    from hobot_vio_rdkx5 import libsrcampy as srcampy  # RDK X5版本

# ***************************************************************************************************
# 第二部分：定义C语言结构体（与后处理库交互）
# ***************************************************************************************************
"""
为什么需要定义C语言结构体？

这个程序需要调用地平线提供的后处理C库（libpostprocess.so）
Python和C是两种不同的语言，不能直接共享数据
ctypes模块允许我们在Python中定义C语言的结构体

这就像制作一个"转换器"：
Python数据 --> C结构体 --> C函数处理 --> 结果返回Python
"""

# 内存区域结构体
class hbSysMem_t(ctypes.Structure):
    """
    hbSysMem_t - 内存区域结构体

    属性说明：
    - phyAddr: 物理地址（硬件直接访问的地址）
    - virAddr: 虚拟地址（程序使用的内存地址）
    - memSize: 内存大小（字节）

    简单理解：
    就像一个仓库的物理位置（phyAddr）和在地图上的编号（virAddr）
    """
    _fields_ = [
        ("phyAddr", ctypes.c_double),
        ("virAddr", ctypes.c_void_p),  # void* 在Python中是 c_void_p
        ("memSize", ctypes.c_int)
    ]

# 量化偏移结构体
class hbDNNQuantiShift_yt(ctypes.Structure):
    """
    hbDNNQuantiShift_yt - 量化偏移结构体

    用于AI模型的量化处理
    量化是一种减小模型大小和加速推理的技术
    """
    _fields_ = [
        ("shiftLen", ctypes.c_int),
        ("shiftData", ctypes.c_char_p)  # char* 字符串指针
    ]

# 量化比例结构体
class hbDNNQuantiScale_t(ctypes.Structure):
    """
    hbDNNQuantiScale_t - 量化比例结构体
    """
    _fields_ = [
        ("scaleLen", ctypes.c_int),
        ("scaleData", ctypes.POINTER(ctypes.c_float)),  # float* 浮点数组
        ("zeroPointLen", ctypes.c_int),
        ("zeroPointData", ctypes.c_char_p)
    ]

# 张量形状结构体
class hbDNNTensorShape_t(ctypes.Structure):
    """
    hbDNNTensorShape_t - 张量形状结构体

    张量 = 多维数组
    AI模型处理的都是张量数据
    """
    _fields_ = [
        ("dimensionSize", ctypes.c_int * 8),  # 最多8维
        ("numDimensions", ctypes.c_int)        # 实际维度数
    ]

# 张量属性结构体
class hbDNNTensorProperties_t(ctypes.Structure):
    """
    hbDNNTensorProperties_t - 张量属性结构体
    """
    _fields_ = [
        ("validShape", hbDNNTensorShape_t),      # 有效形状
        ("alignedShape", hbDNNTensorShape_t),     # 对齐形状（内存对齐优化）
        ("tensorLayout", ctypes.c_int),           # 布局：NCHW/NHWC
        ("tensorType", ctypes.c_int),              # 数据类型
        ("shift", hbDNNQuantiShift_yt),          # 量化偏移
        ("scale", hbDNNQuantiScale_t),            # 量化比例
        ("quantiType", ctypes.c_int),             # 量化类型
        ("quantizeAxis", ctypes.c_int),            # 量化轴
        ("alignedByteSize", ctypes.c_int),         # 对齐字节大小
        ("stride", ctypes.c_int * 8)               # 步长
    ]

# DNN张量结构体
class hbDNNTensor_t(ctypes.Structure):
    """
    hbDNNTensor_t - DNN张量完整结构体

    这是最重要的结构体之一
    用于在Python和C之间传递AI模型的输入输出数据
    """
    _fields_ = [
        ("sysMem", hbSysMem_t * 4),              # 4个内存区域
        ("properties", hbDNNTensorProperties_t)  # 张量属性
    ]

# YOLOv5后处理信息结构体
class Yolov5PostProcessInfo_t(ctypes.Structure):
    """
    Yolov5PostProcessInfo_t - YOLOv5后处理参数结构体

    这个结构体包含了YOLOv5后处理需要的所有参数
    传递给C库进行解析
    """
    _fields_ = [
        ("height", ctypes.c_int),                 # 模型输入高度
        ("width", ctypes.c_int),                  # 模型输入宽度
        ("ori_height", ctypes.c_int),             # 原始图像高度
        ("ori_width", ctypes.c_int),             # 原始图像宽度
        ("score_threshold", ctypes.c_float),       # 置信度阈值
        ("nms_threshold", ctypes.c_float),        # NMS阈值（非极大值抑制）
        ("nms_top_k", ctypes.c_int),              # Top-K（每类最多检测数）
        ("is_pad_resize", ctypes.c_int)            # 是否带填充缩放
    ]

# ***************************************************************************************************
# 第三部分：加载后处理库
# ***************************************************************************************************

def load_postprocess_library():
    """
    load_postprocess_library - 加载后处理C共享库

    后处理库路径：/usr/lib/libpostprocess.so

    为什么需要后处理？
    AI模型的输出是一堆原始数字（张量）
    需要经过复杂的计算才能变成我们能理解的目标框信息
    这些计算在C库中实现，效率更高
    """
    try:
        lib = ctypes.CDLL('/usr/lib/libpostprocess.so')
        return lib
    except Exception as e:
        print(f"加载后处理库失败: {e}")
        print("请确保已正确安装 libpostprocess.so")
        return None

# 加载后处理库
libpostprocess = load_postprocess_library()

# 配置YOLOv5后处理函数
if libpostprocess:
    # Yolov5PostProcess - YOLOv5后处理主函数
    libpostprocess.Yolov5PostProcess.argtypes = [
        ctypes.POINTER(hbDNNTensor_t),  # 输出张量数组
        ctypes.POINTER(Yolov5PostProcessInfo_t),  # 后处理参数
        ctypes.c_int  # 张量数量
    ]
    libpostprocess.Yolov5PostProcess.restype = ctypes.c_char_p  # 返回字符串

    # Yolov5doProcess - 单层后处理函数
    libpostprocess.Yolov5doProcess.argtypes = [
        hbDNNTensor_t,  # 单个输出张量
        ctypes.POINTER(Yolov5PostProcessInfo_t),
        ctypes.c_int
    ]

# ***************************************************************************************************
# 第四部分：工具函数
# ***************************************************************************************************

def get_TensorLayout(layout_str: str) -> int:
    """
    get_TensorLayout - 将布局字符串转换为整数

    参数:
        layout_str: 布局字符串，如 "NCHW" 或 "NHWC"

    返回:
        整数形式的布局代码

    张量布局解释：
    - N: Batch数量（一次处理多少张图）
    - C: Channel（通道数，如RGB三通道）
    - H: Height（高度）
    - W: Width（宽度）

    NCHW = [N, C, H, W]  =  [批次, 通道, 高, 宽]
    NHWC = [N, H, W, C]  =  [批次, 高, 宽, 通道]

    地平线使用NCHW，OpenCV使用NHWC
    """
    if layout_str == "NCHW":
        return int(2)  # NCHW 的代码是2
    else:
        return int(0)  # 其他（NHWC）的代码是0

def get_hw(properties) -> Tuple[int, int]:
    """
    get_hw - 从张量属性中获取高度和宽度

    参数:
        properties: 张量属性对象

    返回:
        (高度, 宽度) 元组
    """
    if properties.layout == "NCHW":
        # NCHW布局: shape = [N, C, H, W]
        return properties.shape[2], properties.shape[3]
    else:
        # NHWC布局: shape = [N, H, W, C]
        return properties.shape[1], properties.shape[2]

def bgr2nv12_opencv(image: np.ndarray) -> np.ndarray:
    """
    bgr2nv12_opencv - 将BGR图像转换为NV12格式

    参数:
        image: OpenCV读取的BGR图像（numpy数组）

    返回:
        NV12格式的图像数据

    为什么需要转换？
    - 摄像头输出通常是YUV格式，不是RGB
    - YUV有很多种格式，NV12是其中一种
    - BPU加速器需要NV12格式的输入
    - NV12 = Y平面(完整) + UV交错(半分辨率)

    YUV解释：
    - Y: 亮度（Luminance），灰度信息
    - U/V: 色度（Chrominance），颜色信息

    人眼对亮度敏感，对色度不敏感
    所以色度信息可以少一些（半分辨率）
    这就是YUV压缩的基本原理
    """
    height, width = image.shape[0], image.shape[1]
    area = height * width

    # 步骤1：BGR转YUV420（使用OpenCV）
    # cv2.COLOR_BGR2YUV_I420 = BGR转YUV420平面格式
    yuv420p = cv2.cvtColor(image, cv2.COLOR_BGR2YUV_I420).reshape((area * 3 // 2,))

    # 步骤2：提取Y分量
    # Y分量是完整的亮度信息
    y = yuv420p[:area]

    # 步骤3：提取UV分量并交错
    # YUV420格式：Y是完整分辨率，UV是半分辨率
    # UV平面是交错的（interleaved），不是平面的（planar）
    uv_planar = yuv420p[area:].reshape((2, area // 4))
    uv_packed = uv_planar.transpose((1, 0)).reshape((area // 2,))

    # 步骤4：组合成NV12
    # NV12格式：Y平面 + UV交错平面
    nv12 = np.zeros_like(yuv420p)
    nv12[:height * width] = y
    nv12[height * width:] = uv_packed

    return nv12

def draw_detections(image: np.ndarray, results: dict, classes: List[str]) -> np.ndarray:
    """
    draw_detections - 在图像上绘制检测结果

    参数:
        image: 原始图像
        results: 检测结果字典
        classes: 类别名称列表

    返回:
        绘制了检测框的图像

    检测结果格式：
    {
        "detections": [
            {
                "name": "person",      # 类别名称
                "bbox": [x1, y1, x2, y2],  # 边界框（左上右下坐标）
                "score": 0.92          # 置信度
            },
            ...
        ]
    }
    """
    img_draw = image.copy()

    for det in results.get('detections', []):
        name = det.get('name', 'unknown')
        bbox = det.get('bbox', [])
        score = det.get('score', 0)

        if len(bbox) != 4:
            continue

        x1, y1, x2, y2 = map(int, bbox)

        # 绘制矩形框（绿色，线宽2）
        cv2.rectangle(img_draw, (x1, y1), (x2, y2), (0, 255, 0), 2)

        # 绘制标签背景（白色矩形）
        label = f"{name}: {score:.2f}"
        label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(img_draw, (x1, y1 - label_size[1] - 4), (x1 + label_size[0], y1), (255, 255, 255), -1)

        # 绘制标签文字
        cv2.putText(img_draw, label, (x1, y1 - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    return img_draw

# ***************************************************************************************************
# 第五部分：COCO类别定义
# ***************************************************************************************************

# COCO数据集的80个类别（YOLOv5训练用）
# 完整列表，涵盖了日常生活中常见的物体
classes = [
    "person",       # 人
    "bicycle",      # 自行车
    "car",          # 汽车
    "motorcycle",   # 摩托车
    "airplane",     # 飞机
    "bus",          # 公交车
    "train",        # 火车
    "truck",        # 卡车
    "boat",         # 船
    "traffic light",# 红绿灯
    "fire hydrant", # 消防栓
    "stop sign",    # 停车标志
    "parking meter",# 停车计时器
    "bench",        # 长凳
    "bird",         # 鸟
    "cat",          # 猫
    "dog",          # 狗
    "horse",        # 马
    "sheep",        # 羊
    "cow",          # 牛
    "elephant",     # 大象
    "bear",         # 熊
    "zebra",        # 斑马
    "giraffe",      # 长颈鹿
    "backpack",     # 背包
    "umbrella",     # 雨伞
    "handbag",      # 手提包
    "tie",          # 领带
    "suitcase",     # 行李箱
    "frisbee",      # 飞盘
    "skis",         # 滑雪板
    "snowboard",    # 单板滑雪
    "sports ball",  # 运动球
    "kite",         # 风筝
    "baseball bat", # 棒球棒
    "baseball glove",# 棒球手套
    "skateboard",   # 滑板
    "surfboard",    # 冲浪板
    "tennis racket",# 网球拍
    "bottle",       # 瓶子
    "wine glass",   # 酒杯
    "cup",          # 杯子
    "fork",         # 叉子
    "knife",        # 刀
    "spoon",        # 勺子
    "bowl",         # 碗
    "banana",       # 香蕉
    "apple",        # 苹果
    "sandwich",     # 三明治
    "orange",       # 橙子
    "broccoli",     # 西兰花
    "carrot",       # 胡萝卜
    "hot dog",      # 热狗
    "pizza",        # 披萨
    "donut",        # 甜甜圈
    "cake",         # 蛋糕
    "chair",        # 椅子
    "couch",        # 沙发
    "potted plant", # 盆栽
    "bed",          # 床
    "dining table", # 餐桌
    "toilet",       # 马桶
    "tv",           # 电视
    "laptop",       # 笔记本电脑
    "mouse",        # 鼠标
    "remote",       # 遥控器
    "keyboard",     # 键盘
    "cell phone",   # 手机
    "microwave",    # 微波炉
    "oven",         # 烤箱
    "toaster",      # 烤面包机
    "sink",         # 水槽
    "refrigerator", # 冰箱
    "book",         # 书
    "clock",        # 钟
    "vase",         # 花瓶
    "scissors",     # 剪刀
    "teddy bear",   # 泰迪熊
    "hair drier",   # 吹风机
    "toothbrush"    # 牙刷
]

# ***************************************************************************************************
# 第六部分：YOLOv5检测器类
# ***************************************************************************************************

class YOLOv5Detector:
    """
    YOLOv5Detector - YOLOv5目标检测器封装类

    这个类封装了YOLOv5模型加载、推理和后处理的完整流程
    使用面向对象的方式组织代码，更清晰易维护
    """

    def __init__(self, model_path: str, score_threshold: float = 0.4,
                 nms_threshold: float = 0.45, nms_top_k: int = 20):
        """
        __init__ - 初始化检测器

        参数:
            model_path: 模型文件路径（.bin格式）
            score_threshold: 置信度阈值（小于这个值的结果会被丢弃）
            nms_threshold: NMS阈值（非极大值抑制阈值）
            nms_top_k: 每类最多保留的检测数量

        置信度阈值说明：
        - 值越高：只保留高置信度的检测，误检少但可能漏检
        - 值越低：保留更多检测，漏检少但可能误检
        - 推荐：0.25-0.4
        """
        self.model_path = model_path
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self.nms_top_k = nms_top_k

        # 加载模型
        print(f"正在加载模型: {model_path}")
        self.models = dnn.load(model_path)
        print(f"模型加载成功！")

        # 获取输入输出信息
        self.input_h, self.input_w = get_hw(self.models[0].inputs[0].properties)
        print(f"模型输入尺寸: {self.input_w} x {self.input_h}")

        # 用于计时
        self.inference_times = []

    def preprocess(self, image: np.ndarray) -> np.ndarray:
        """
        preprocess - 图像预处理

        参数:
            image: OpenCV读取的BGR图像

        返回:
            预处理后的NV12格式数据

        预处理步骤：
        1. 缩放到模型输入尺寸
        2. 转换为NV12格式
        """
        # 缩放图像到模型输入尺寸
        # cv2.resize() 参数：
        # - 图像, 目标尺寸, 插值方法
        # 插值方法: INTER_AREA适合缩小, INTER_LINEAR适合放大
        resized = cv2.resize(image, (self.input_w, self.input_h),
                             interpolation=cv2.INTER_AREA)

        # BGR转NV12
        nv12_data = bgr2nv12_opencv(resized)

        return nv12_data

    def postprocess(self, outputs: List[Any], orig_h: int, orig_w: int) -> dict:
        """
        postprocess - 后处理，解析模型输出

        参数:
            outputs: 模型输出列表
            orig_h: 原始图像高度
            orig_w: 原始图像宽度

        返回:
            检测结果字典
        """
        # 创建后处理参数
        yolov5_postprocess_info = Yolov5PostProcessInfo_t()
        yolov5_postprocess_info.height = self.input_h
        yolov5_postprocess_info.width = self.input_w
        yolov5_postprocess_info.ori_height = orig_h
        yolov5_postprocess_info.ori_width = orig_w
        yolov5_postprocess_info.score_threshold = self.score_threshold
        yolov5_postprocess_info.nms_threshold = self.nms_threshold
        yolov5_postprocess_info.nms_top_k = self.nms_top_k
        yolov5_postprocess_info.is_pad_resize = 0

        # 准备输出张量
        output_tensors = (hbDNNTensor_t * len(outputs))()

        for i, output in enumerate(outputs):
            # 设置张量布局
            output_tensors[i].properties.tensorLayout = get_TensorLayout(
                output.properties.layout)

            # 根据量化类型设置
            if len(output.properties.scale_data) == 0:
                # 无量化，使用浮点数
                output_tensors[i].properties.quantiType = 0
                output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                    output.buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    ctypes.c_void_p)
            else:
                # 量化类型，使用整数
                output_tensors[i].properties.quantiType = 2
                output_tensors[i].properties.scale.scaleData = output.properties.scale_data.ctypes.data_as(
                    ctypes.POINTER(ctypes.c_float))
                output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                    output.buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                    ctypes.c_void_p)

            # 设置形状
            for j in range(len(output.properties.shape)):
                output_tensors[i].properties.validShape.numDimensions = len(output.properties.shape)
                output_tensors[i].properties.validShape.dimensionSize[j] = output.properties.shape[j]

            # 调用后处理
            libpostprocess.Yolov5doProcess(output_tensors[i],
                                           ctypes.pointer(yolov5_postprocess_info),
                                           i)

        # 获取最终结果
        result_str = libpostprocess.Yolov5PostProcess(
            ctypes.pointer(output_tensors[0]),
            ctypes.pointer(yolov5_postprocess_info),
            len(outputs))

        # 解析JSON结果
        result_str = result_str.decode('utf-8')

        # 跳过开头的元数据，解析JSON部分
        # 格式通常是 "YOLOV5 results:\n{...}"
        if "{" in result_str:
            json_str = result_str[result_str.index("{"):]
            return json.loads(json_str)

        return {"detections": []}

    def detect(self, image: np.ndarray) -> dict:
        """
        detect - 执行完整检测流程

        参数:
            image: BGR图像

        返回:
            检测结果字典
        """
        orig_h, orig_w = image.shape[:2]

        # 预处理
        nv12_data = self.preprocess(image)

        # 推理
        t0 = time.time()
        outputs = self.models[0].forward(nv12_data)
        t1 = time.time()

        # 记录推理时间
        self.inference_times.append(t1 - t0)

        # 后处理
        results = self.postprocess(outputs, orig_h, orig_w)

        return results

    def get_fps(self) -> float:
        """
        get_fps - 计算平均FPS
        """
        if len(self.inference_times) == 0:
            return 0.0
        avg_time = sum(self.inference_times) / len(self.inference_times)
        return 1.0 / avg_time if avg_time > 0 else 0.0

# ***************************************************************************************************
# 第七部分：摄像头处理函数
# ***************************************************************************************************

def handle_cam(detector: YOLOv5Detector, model_h: int, model_w: int,
               disp_w: int, disp_h: int):
    """
    handle_cam - 摄像头处理主循环

    参数:
        detector: YOLOv5检测器实例
        model_h: 模型输入高度
        model_w: 模型输入宽度
        disp_w: 显示宽度
        disp_h: 显示高度
    """
    print("=" * 60)
    print("摄像头检测模式")
    print("=" * 60)
    print("按 Ctrl+C 退出")
    print("=" * 60)

    # -------------------- 打开摄像头 --------------------
    # Camera类的参数：
    # - 设备ID（0=第一个摄像头）
    # - 模式（-1=自动）
    # - 标志（-1=默认）
    # - 宽度列表（支持多种分辨率）
    # - 高度列表
    # - 传感器高度和宽度
    cam = srcampy.Camera()

    # sensor configs
    sensor_width = 960
    sensor_height = 544

    # 打开摄像头
    # 这里设置分辨率为 960x544
    ret = cam.open_cam(0, -1, -1,
                       [model_w, disp_w],
                       [model_h, disp_h],
                       sensor_height, sensor_width)

    if not ret:
        print("摄像头打开失败！")
        return

    print(f"摄像头已打开，分辨率: {sensor_width} x {sensor_height}")

    # -------------------- 创建显示对象 --------------------
    disp = srcampy.Display()

    # -------------------- 绑定摄像头到显示 --------------------
    # 这样摄像头捕获的图像可以直接显示
    srcampy.bind(cam, disp)

    print("开始实时检测...")

    # -------------------- 主循环 --------------------
    frame_count = 0
    fps_update_interval = 30  # 每30帧更新一次FPS

    try:
        while True:
            # -------- 获取摄像头图像 --------
            # get_img() 返回NV12格式的图像数据
            # 参数是超时时间（毫秒）
            img = cam.get_img(2, model_w, model_h)

            if img is None:
                print("获取图像失败，跳过...")
                continue

            # -------- 转换为numpy数组 --------
            img = np.frombuffer(img, dtype=np.uint8)

            # -------- BGR转换 --------
            # NV12转BGR，这样才能用OpenCV绘制
            # 注意：这里只是模拟，因为实际显示可能不需要转换
            frame = img.reshape((model_h * 3 // 2, model_w))
            frame = cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_NV12)

            # -------- 执行检测 --------
            results = detector.detect(frame)

            # -------- 绘制检测结果 --------
            output_frame = draw_detections(frame, results, classes)

            # -------- 显示FPS信息 --------
            frame_count += 1
            if frame_count % fps_update_interval == 0:
                fps = detector.get_fps()
                cv2.putText(output_frame, f"FPS: {fps:.1f}",
                           (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

            # -------- 显示图像 --------
            cv2.imshow("YOLOv5 Detection", output_frame)

            # -------- 按ESC退出 --------
            key = cv2.waitKey(1)
            if key == 27:  # ESC键的ASCII码是27
                break

    except KeyboardInterrupt:
        print("\n用户中断，正在退出...")

    finally:
        # -------- 清理 --------
        print("关闭摄像头...")
        cam.close_cam()
        disp.close()
        cv2.destroyAllWindows()

        # 打印统计信息
        if len(detector.inference_times) > 0:
            avg_time = sum(detector.inference_times) / len(detector.inference_times)
            avg_fps = 1.0 / avg_time if avg_time > 0 else 0
            print(f"\n检测统计:")
            print(f"  总检测帧数: {len(detector.inference_times)}")
            print(f"  平均推理时间: {avg_time*1000:.2f} ms")
            print(f"  平均FPS: {avg_fps:.2f}")

# ***************************************************************************************************
# 第八部分：主函数
# ***************************************************************************************************

def main():
    """
    main - 程序入口

    配置参数说明：
    - model_path: YOLOv5模型文件路径
    - model_w, model_h: 模型输入分辨率（必须与模型匹配）
    - disp_w, disp_h: 显示分辨率
    - score_threshold: 置信度阈值
    - nms_threshold: NMS阈值
    """

    # ==================== 配置区域 ====================
    # 根据实际情况修改这些参数

    # 模型文件路径
    # 注意：必须是nv12格式的模型
    model_path = "/app/model/basic/yolov5s_672x672_nv12.bin"

    # 模型输入尺寸（必须与模型文件匹配）
    # YOLOv5s通常用 640x640 或 672x672
    model_w = 672
    model_h = 672

    # 显示分辨率
    disp_w = 1920
    disp_h = 1080

    # 检测参数
    score_threshold = 0.4   # 置信度阈值
    nms_threshold = 0.45   # NMS阈值
    nms_top_k = 20          # Top-K

    # ==================== 初始化 ====================

    # 检查模型文件是否存在
    if not os.path.exists(model_path):
        print(f"错误：模型文件不存在: {model_path}")
        print("请检查模型路径是否正确")
        return

    # 创建检测器
    detector = YOLOv5Detector(
        model_path=model_path,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        nms_top_k=nms_top_k
    )

    # 启动摄像头检测
    handle_cam(detector, model_h, model_w, disp_w, disp_h)

    print("程序结束")

# ***************************************************************************************************
# 第九部分：程序入口
# ***************************************************************************************************

if __name__ == '__main__':
    main()

# ***************************************************************************************************
# 课后练习
# ***************************************************************************************************
#
# 练习1：调整置信度阈值
#   找到 score_threshold = 0.4
#   - 改成 0.2：更灵敏，检测更多目标
#   - 改成 0.6：更严格，减少误检
#
# 练习2：改变检测目标
#   修改 classes 列表，只保留你关心的类别
#   例如只检测人和车：
#   classes = ["person", "car"]
#
# 练习3：添加FPS显示
#   在主循环中添加FPS计算和显示
#
# 练习4：保存检测结果
#   将检测结果保存到文件或数据库
#
# ***************************************************************************************************
# 进阶学习
# ***************************************************************************************************
#
# 1. 模型文件格式
#    - .bin 文件是地平线专用的模型格式
#    - 包含模型结构和权重
#    - 需要使用特定工具从.onnx转换
#
# 2. 为什么用NV12？
#    - NV12是YUV420格式的一种
#    - Y: 亮度通道（完整分辨率）
#    - UV: 色度通道（半分辨率）
#    - BPU加速器针对这种格式做了优化
#
# 3. NMS（非极大值抑制）
#    作用：去除重叠的检测框
#    原理：
#    1. 按置信度排序所有检测框
#    2. 保留最高置信度的框
#    3. 删除与保留框重叠超过阈值的框
#    4. 重复直到处理完所有框
#
# 4. 如何训练自己的模型？
#    1. 收集并标注数据
#    2. 使用YOLOv5训练
#    3. 导出为ONNX格式
#    4. 使用地平线工具转换为.bin格式
#
# ***************************************************************************************************
# 常见问题
# ***************************************************************************************************
#
# Q: 程序启动失败，提示 "Camera open failed"
# A: 检查：
#    1. 摄像头是否正确连接
#    2. 摄像头是否被其他程序占用
#    3. 尝试重启开发板
#
# Q: 检测很慢，FPS很低
# A: 优化方法：
#    1. 减小模型输入分辨率（如640x640）
#    2. 使用更小的模型（如yolov5s而不是yolov5x）
#    3. 关闭不需要的窗口
#
# Q: 检测不到目标
# A: 检查：
#    1. 置信度阈值是否太高？
#    2. 模型是否正确？（尝试用默认模型）
#    3. 摄像头是否正常工作？
#
# Q: 如何使用其他模型？
#    修改 model_path 为其他模型路径
#    确保输入尺寸与模型匹配
#
# ***************************************************************************************************

print("=" * 80)
print("恭喜你完成了YOLOv5目标检测的学习！")
print("=" * 80)
