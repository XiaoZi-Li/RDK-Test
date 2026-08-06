#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mipi_camera.py - MIPI摄像头实时目标检测示例
================================================================================

【程序功能】
本程序使用MIPI接口摄像头捕获视频流，并结合FCOS目标检测模型进行实时检测。
MIPI摄像头具有高带宽、低延迟的特点，适合实时AI视觉应用。

【硬件要求】
- MIPI接口摄像头（支持D-Robotics平台）
- HDMI显示器（用于显示检测结果）

【技术特点】
1. MIPI CSI接口：高速图像数据传输
2. 硬件绑定：摄像头与显示直接绑定，减少CPU开销
3. 多进程并行：后处理使用进程池并行执行
4. 实时显示：检测结果实时叠加在HDMI显示上

【系统架构】
┌────────────────┐      ┌────────────────┐      ┌────────────────┐
│  MIPI Camera   │─────▶│  BPU Inference │─────▶│   HDMI Display │
│  (1080p@30fps) │      │  (FCOS 512x512)│      │   (检测结果)   │
└────────────────┘      └────────────────┘      └────────────────┘

【模型信息】
- 模型：FCOS（Fully Convolutional One-Stage Detector）
- 输入尺寸：512x512像素
- 支持：80类COCO目标检测

【运行方式】
cd pydev_demo/03_mipi_camera_sample/
python3 mipi_camera.py

【输出】
- 实时HDMI显示检测结果（边界框+类别+置信度）
- 每处理100帧输出FPS统计

================================================================================
"""

import sys
import signal
import os
import numpy as np
import cv2
import colorsys
from time import time, sleep
import multiprocessing
from threading import BoundedSemaphore
import ctypes
import json

try:
    from hobot_vio import libsrcampy as srcampy
except ImportError:
    from hobot_vio_rdkx5 import libsrcampy as srcampy
try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn

import threading

# ================================================================================
# 全局配置
# ================================================================================

# 传感器分辨率配置
sensor_width = 1920   # 传感器宽度
sensor_height = 1080  # 传感器高度

# 全局变量
image_counter = None   # 帧计数器（用于FPS计算）
is_stop = False       # 停止标志
output_tensors = None # 输出张量数组
fcos_postprocess_info = None  # 后处理参数

# ================================================================================
# C结构体定义 - 与BPU驱动和FCOS后处理库交互
# ================================================================================

class hbSysMem_t(ctypes.Structure):
    """
    hbSysMem_t - BPU系统内存结构体

    【功能】
        描述BPU使用的内存区域信息
    """
    _fields_ = [
        ("phyAddr", ctypes.c_double),   # 物理地址
        ("virAddr", ctypes.c_void_p),   # 虚拟地址
        ("memSize", ctypes.c_int)       # 内存大小
    ]

class hbDNNQuantiShift_yt(ctypes.Structure):
    """量化位移参数结构体"""
    _fields_ = [
        ("shiftLen", ctypes.c_int),
        ("shiftData", ctypes.c_char_p)
    ]

class hbDNNQuantiScale_t(ctypes.Structure):
    """量化比例参数结构体"""
    _fields_ = [
        ("scaleLen", ctypes.c_int),
        ("scaleData", ctypes.POINTER(ctypes.c_float)),
        ("zeroPointLen", ctypes.c_int),
        ("zeroPointData", ctypes.c_char_p)
    ]

class hbDNNTensorShape_t(ctypes.Structure):
    """张量形状结构体"""
    _fields_ = [
        ("dimensionSize", ctypes.c_int * 8),
        ("numDimensions", ctypes.c_int)
    ]

class hbDNNTensorProperties_t(ctypes.Structure):
    """张量属性结构体"""
    _fields_ = [
        ("validShape", hbDNNTensorShape_t),
        ("alignedShape", hbDNNTensorShape_t),
        ("tensorLayout", ctypes.c_int),
        ("tensorType", ctypes.c_int),
        ("shift", hbDNNQuantiShift_yt),
        ("scale", hbDNNQuantiScale_t),
        ("quantiType", ctypes.c_int),
        ("quantizeAxis", ctypes.c_int),
        ("alignedByteSize", ctypes.c_int),
        ("stride", ctypes.c_int * 8)
    ]

class hbDNNTensor_t(ctypes.Structure):
    """BPU张量结构体"""
    _fields_ = [
        ("sysMem", hbSysMem_t * 4),
        ("properties", hbDNNTensorProperties_t)
    ]


class FcosPostProcessInfo_t(ctypes.Structure):
    """
    FcosPostProcessInfo_t - FCOS后处理参数结构体

    【参数说明】
        height/width: 模型输入尺寸（512x512）
        ori_height/ori_width: 原始显示分辨率
        score_threshold: 置信度阈值
        nms_threshold: 非极大值抑制阈值
        nms_top_k: 最多保留的检测框数量
        is_pad_resize: 是否使用填充方式resize
    """
    _fields_ = [
        ("height", ctypes.c_int),
        ("width", ctypes.c_int),
        ("ori_height", ctypes.c_int),
        ("ori_width", ctypes.c_int),
        ("score_threshold", ctypes.c_float),
        ("nms_threshold", ctypes.c_float),
        ("nms_top_k", ctypes.c_int),
        ("is_pad_resize", ctypes.c_int)
    ]


# ================================================================================
# 加载FCOS后处理库
# ================================================================================

libpostprocess = ctypes.CDLL('/usr/lib/libpostprocess.so')

get_Postprocess_result = libpostprocess.FcosPostProcess
get_Postprocess_result.argtypes = [ctypes.POINTER(FcosPostProcessInfo_t)]
get_Postprocess_result.restype = ctypes.c_char_p

# ================================================================================
# 辅助函数
# ================================================================================

def get_TensorLayout(Layout):
    """
    Layout字符串转换为BPU内部整数值

    【返回值】
        2 = NCHW格式（通道在前）
        0 = NHWC格式（通道在后）
    """
    if Layout == "NCHW":
        return int(2)
    else:
        return int(0)


def get_display_res():
    """
    获取HDMI显示分辨率

    【功能】
        自动检测系统支持的HDMI分辨率，返回最合适的分辨率

    【返回值】
        (disp_w, disp_h): 显示分辨率
    """
    disp_w_small = 1920
    disp_h_small = 1080

    disp = srcampy.Display()
    resolution_list = disp.get_display_res()

    # 检查传感器分辨率是否在支持列表中
    if (sensor_width, sensor_height) in resolution_list:
        print(f"Resolution {sensor_width}x{sensor_height} exists in the list.")
        return int(sensor_width), int(sensor_height)
    else:
        print(f"Resolution {sensor_width}x{sensor_height} does not exist in the list.")
        # 遍历查找最佳分辨率
        for res in resolution_list:
            if res[0] == 0 and res[1] == 0:
                break
            else:
                disp_w_small = res[0]
                disp_h_small = res[1]

            # 选择不超过传感器尺寸的最大分辨率
            if res[0] <= sensor_width and res[1] <= sensor_height:
                print(f"Resolution {res[0]}x{res[1]}.")
                return int(res[0]), int(res[1])

    disp.close()
    return disp_w_small, disp_h_small


def get_classes():
    """
    获取COCO数据集80类目标名称列表

    【COCO数据集类别】
        涵盖了日常生活中的常见物体
    """
    return np.array([
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
    ])


def get_hw(pro):
    """
    从Tensor属性中获取高度和宽度
    """
    if pro.layout == "NCHW":
        return pro.shape[2], pro.shape[3]
    else:
        return pro.shape[1], pro.shape[2]


def print_properties(pro):
    """
    打印Tensor属性信息
    """
    print("tensor type:", pro.tensor_type)
    print("data type:", pro.dtype)
    print("layout:", pro.layout)
    print("shape:", pro.shape)


# ================================================================================
# 并行推理执行器
# ================================================================================

class ParallelExector(object):
    """
    并行推理执行器

    【功能】
        使用多进程池并行执行后处理任务，提高系统吞吐量

    【参数】
        counter: 帧计数器（multiprocessing.Value）
        parallel_num: 并行进程数量，默认为4
    """

    def __init__(self, counter, parallel_num=4):
        global image_counter
        image_counter = counter
        self.parallel_num = parallel_num

        # 创建进程池
        if parallel_num != 1:
            self._pool = multiprocessing.Pool(
                processes=self.parallel_num,
                maxtasksperchild=5  # 每个进程最多处理5个任务后重启，防止内存泄漏
            )
            self.workers = BoundedSemaphore(self.parallel_num)

    def infer(self, output):
        """
        提交推理任务

        【参数】
            output: 模型输出数组
        """
        if self.parallel_num == 1:
            run(output)
        else:
            self.workers.acquire()
            self._pool.apply_async(
                func=run,
                args=(output,),
                callback=self.task_done,
                error_callback=print
            )

    def task_done(self, *args, **kwargs):
        """任务完成回调，释放信号量"""
        self.workers.release()

    def close(self):
        """关闭进程池"""
        if hasattr(self, "_pool"):
            self._pool.close()
            self._pool.join()


# ================================================================================
# 坐标处理函数
# ================================================================================

def limit_display_cord(coor):
    """
    限制坐标在显示范围内

    【功能】
        确保边界框不会超出屏幕边界
        y坐标最小值设为2，为文字显示留出空间

    【参数】
        coor: [x1, y1, x2, y2] 坐标列表

    【返回值】
        限制后的坐标列表
    """
    coor[0] = max(min(disp_w, coor[0]), 0)
    coor[1] = max(min(disp_h, coor[1]), 2)  # 留出文字显示空间
    coor[2] = max(min(disp_w, coor[2]), 0)
    coor[3] = max(min(disp_h, coor[3]), 0)
    return coor


def scale_bbox(bbox, input_w, input_h, output_w, output_h):
    """
    边界框坐标缩放

    【功能】
        将模型输出的边界框坐标缩放到显示分辨率

    【参数】
        bbox: [x1, y1, x2, y2] 原始坐标
        input_w, input_h: 输入尺寸（512x512）
        output_w, output_h: 输出尺寸（显示分辨率）
    """
    scale_x = output_w / input_w
    scale_y = output_h / input_h

    x1 = int(bbox[0] * scale_x)
    y1 = int(bbox[1] * scale_y)
    x2 = int(bbox[2] * scale_x)
    y2 = int(bbox[3] * scale_y)

    return [x1, y1, x2, y2]


# ================================================================================
# 后处理和显示函数
# ================================================================================

def run(outputs):
    """
    FCOS后处理和结果绘制函数

    【功能】
        1. 执行FCOS后处理（NMS等）
        2. 在HDMI上绘制检测框和标签
        3. 更新帧计数器
    """
    global image_counter

    # FCOS使用5个不同尺度的特征图，strides = [8, 16, 32, 64, 128]
    strides = [8, 16, 32, 64, 128]

    for i in range(len(strides)):
        # 根据量化类型设置正确的指针类型
        if output_tensors[i].properties.quantiType == 0:
            # FLOAT32模型
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ctypes.c_void_p)
            output_tensors[i + 5].sysMem[0].virAddr = ctypes.cast(
                outputs[i + 5].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ctypes.c_void_p)
            output_tensors[i + 10].sysMem[0].virAddr = ctypes.cast(
                outputs[i + 10].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ctypes.c_void_p)
        else:
            # INT8量化模型
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                ctypes.c_void_p)
            output_tensors[i + 5].sysMem[0].virAddr = ctypes.cast(
                outputs[i + 5].ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                ctypes.c_void_p)
            output_tensors[i + 10].sysMem[0].virAddr = ctypes.cast(
                outputs[i + 10].ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                ctypes.c_void_p)

        # 调用FCOS后处理
        libpostprocess.FcosdoProcess(
            output_tensors[i],
            output_tensors[i + 5],
            output_tensors[i + 10],
            ctypes.pointer(fcos_postprocess_info),
            i
        )

    # 获取后处理结果
    result_str = get_Postprocess_result(ctypes.pointer(fcos_postprocess_info))
    result_str = result_str.decode('utf-8')

    # 解析JSON结果
    data = json.loads(result_str[14:])

    # 遍历每个检测结果并绘制
    for index, result in enumerate(data):
        bbox = result['bbox']      # 边界框坐标
        score = result['score']    # 置信度
        id = int(result['id'])     # 类别ID
        name = result['name']      # 类别名称

        # 缩放坐标到显示分辨率
        bbox = scale_bbox(bbox, 512, 512, disp_w, disp_h)
        coor = limit_display_cord(bbox)
        coor = [round(i) for i in coor]
        score = float(score)

        # 格式化显示字符串
        bbox_string = '%s: %.2f' % (name, score)
        bbox_string = bbox_string.encode('gb2312')

        # 获取颜色
        box_color = colors[id]
        color_base = 0xFF000000
        box_color_ARGB = color_base | (box_color[0]) << 16 | (box_color[1]) << 8 | (box_color[2])

        print("{} is in the picture with confidence:{:.4f}, bbox:{}".format(
            name, score, coor))

        # 在HDMI上绘制检测框和标签
        # index == 0时需要刷新显示缓冲区
        if index == 0:
            disp.set_graph_rect(coor[0], coor[1], coor[2], coor[3], 3, 1, box_color_ARGB)
            disp.set_graph_word(coor[0], coor[1] - 2, bbox_string, 3, 1, box_color_ARGB)
        else:
            disp.set_graph_rect(coor[0], coor[1], coor[2], coor[3], 3, 0, box_color_ARGB)
            disp.set_graph_word(coor[0], coor[1] - 2, bbox_string, 3, 0, box_color_ARGB)

    # 更新帧计数器并计算FPS
    with image_counter.get_lock():
        image_counter.value += 1
    if image_counter.value == 100:
        finish_time = time()
        print(f"Total time cost for 100 frames: {finish_time - start_time}, fps: {100/(finish_time - start_time)}")


# ================================================================================
# 信号处理器
# ================================================================================

def signal_handler(signal, frame):
    """处理Ctrl+C信号，优雅退出"""
    global is_stop
    print("Stopping!\n")
    is_stop = True
    sys.exit(0)


# ================================================================================
# 全局显示对象（供多进程使用）
# ================================================================================

disp = None
start_time = None

# ================================================================================
# 主程序入口
# ================================================================================

if __name__ == '__main__':
    # 注册Ctrl+C信号处理器
    signal.signal(signal.SIGINT, signal_handler)

    # ==========================================================================
    # 第1步：加载FCOS目标检测模型
    # ==========================================================================
    models = dnn.load('../models/fcos_512x512_nv12.bin')

    print("--- model input properties ---")
    print_properties(models[0].inputs[0].properties)
    print("--- model output properties ---")
    for output in models[0].outputs:
        print_properties(output.properties)

    # ==========================================================================
    # 第2步：获取显示分辨率
    # ==========================================================================
    disp_w, disp_h = get_display_res()

    # ==========================================================================
    # 第3步：配置FCOS后处理参数
    # ==========================================================================
    fcos_postprocess_info = FcosPostProcessInfo_t()
    fcos_postprocess_info.height = 512       # 模型输入高度
    fcos_postprocess_info.width = 512       # 模型输入宽度
    fcos_postprocess_info.ori_height = disp_h  # 原始显示高度
    fcos_postprocess_info.ori_width = disp_w   # 原始显示宽度
    fcos_postprocess_info.score_threshold = 0.5  # 置信度阈值50%
    fcos_postprocess_info.nms_threshold = 0.6     # NMS阈值60%
    fcos_postprocess_info.nms_top_k = 5           # 最多5个检测框
    fcos_postprocess_info.is_pad_resize = 0       # 不使用填充resize

    # ==========================================================================
    # 第4步：准备输出Tensor数组
    # ==========================================================================
    output_tensors = (hbDNNTensor_t * len(models[0].outputs))()

    for i in range(len(models[0].outputs)):
        output_tensors[i].properties.tensorLayout = get_TensorLayout(
            models[0].outputs[i].properties.layout
        )

        # 设置量化类型
        if len(models[0].outputs[i].properties.scale_data) == 0:
            output_tensors[i].properties.quantiType = 0
        else:
            output_tensors[i].properties.quantiType = 2
            scale_data_tmp = models[0].outputs[i].properties.scale_data.reshape(
                1, 1, 1, models[0].outputs[i].properties.shape[3]
            )
            output_tensors[i].properties.scale.scaleData = scale_data_tmp.ctypes.data_as(
                ctypes.POINTER(ctypes.c_float)
            )

        # 设置张量形状
        for j in range(len(models[0].outputs[i].properties.shape)):
            output_tensors[i].properties.validShape.dimensionSize[j] = \
                models[0].outputs[i].properties.shape[j]
            output_tensors[i].properties.alignedShape.dimensionSize[j] = \
                models[0].outputs[i].properties.shape[j]

    # ==========================================================================
    # 第5步：初始化MIPI摄像头
    # ==========================================================================
    cam = srcampy.Camera()

    # 获取模型输入尺寸
    h, w = get_hw(models[0].inputs[0].properties)
    input_shape = (h, w)

    # 打开MIPI摄像头
    # 参数：cam_id=0, fps=-1(自动), padding, 输出尺寸, 传感器高宽
    cam.open_cam(0, -1, -1, [w, disp_w], [h, disp_h], sensor_height, sensor_width)

    # ==========================================================================
    # 第6步：初始化HDMI显示
    # ==========================================================================
    global disp
    disp = srcampy.Display()
    disp.display(0, disp_w, disp_h)

    # ==========================================================================
    # 第7步：绑定摄像头到显示（硬件级联）
    # ==========================================================================
    srcampy.bind(cam, disp)

    # 切换到OSD层用于绘制检测框
    disp.display(3, disp_w, disp_h)

    # ==========================================================================
    # 第8步：准备颜色表
    # ==========================================================================
    classes = get_classes()
    num_classes = len(classes)
    hsv_tuples = [(1.0 * x / num_classes, 1., 1.) for x in range(num_classes)]
    colors = list(map(lambda x: colorsys.hsv_to_rgb(*x), hsv_tuples))
    colors = list(
        map(lambda x: (int(x[0] * 255), int(x[1] * 255), int(x[2] * 255)), colors)
    )

    # ==========================================================================
    # 第9步：初始化FPS计时器和帧计数器
    # ==========================================================================
    global start_time
    start_time = time()
    image_counter = multiprocessing.Value("i", 0)

    # ==========================================================================
    # 第10步：创建并行执行器
    # ==========================================================================
    parallel_exe = ParallelExector(image_counter)

    # ==========================================================================
    # 第11步：主循环 - 实时检测
    # ==========================================================================
    while not is_stop:
        # 获取摄像头图像（512x512 NV12格式）
        cam_start_time = time()
        img = cam.get_img(2, 512, 512)
        cam_finish_time = time()

        # 转换为numpy数组
        buffer_start_time = time()
        img = np.frombuffer(img, dtype=np.uint8)
        buffer_finish_time = time()

        # 执行BPU推理
        infer_start_time = time()
        outputs = models[0].forward(img)
        infer_finish_time = time()

        # 准备输出数据
        output_array = []
        for item in outputs:
            output_array.append(item.buffer)

        # 提交并行后处理任务
        parallel_exe.infer(output_array)

    # ==========================================================================
    # 第12步：清理资源
    # ==========================================================================
    cam.close_cam()
    disp.close()
    parallel_exe.close()

# ================================================================================
# 【MIPI摄像头 vs USB摄像头 对比】
# ================================================================================
# | 特性         | MIPI摄像头          | USB摄像头            |
# |--------------|---------------------|----------------------|
# | 接口类型     | CSI-2 (MIPI)       | USB 3.0/2.0         |
# | 延迟         | 极低 (<10ms)       | 较高 (20-50ms)      |
# | 带宽         | 高 (可达4K@60fps)   | 受限 (取决于USB)    |
# | 驱动复杂度   | 复杂 (内核驱动)     | 简单 (V4L2)         |
# | 适用场景     | 实时AI、机器人      | 通用视频采集        |
#
# MIPI摄像头直接与BPU相连，数据流更高效，适合对延迟敏感的应用
