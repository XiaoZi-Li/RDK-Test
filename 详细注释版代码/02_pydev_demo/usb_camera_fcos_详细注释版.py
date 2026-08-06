#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
usb_camera_fcos.py - USB摄像头实时目标检测示例
================================================================================

【程序功能】
本程序使用USB摄像头捕获视频流，并利用FCOS（Fully Convolutional One-Stage）目标检测模型
进行实时目标检测。检测结果会通过HDMI显示到屏幕上，同时输出FPS性能指标。

【模型信息】
- 模型名称：FCOS（Fully Convolutional One-Stage Object Detector）
- 输入尺寸：512x512像素
- 输入格式：NV12
- 支持80类目标检测（COCO数据集）

【FCOS算法特点】
1. 无锚框（Anchor-Free）：不像YOLO等使用预定义的锚框，直接预测目标位置
2. 全卷积网络：完全基于卷积操作，可以接受任意尺寸输入
3. 多尺度检测：在多个特征图尺度上进行检测，适合不同大小的目标
4. 更少的超参数：相比锚框方法，调参更简单

【硬件要求】
- USB摄像头（支持V4L2）
- HDMI显示器（用于显示检测结果）

【运行方式】
# 自动检测摄像头
python3 usb_camera_fcos.py

# 指定摄像头设备
python3 usb_camera_fcos.py /dev/video1

【显示效果】
- 实时显示检测结果（边界框+类别+置信度）
- 每10秒输出一次FPS性能统计

================================================================================
"""

import sys
import signal
import os
try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn
try:
    from hobot_vio import libsrcampy as srcampy
except ImportError:
    from hobot_vio_rdkx5 import libsrcampy as srcampy
import numpy as np
import cv2
import colorsys
from time import time

import ctypes
import json

def signal_handler(signal, frame):
    """
    信号处理器 - 处理Ctrl+C优雅退出
    """
    print("\nExiting program")
    sys.exit(0)

output_tensors = None

fcos_postprocess_info = None

# ================================================================================
# C结构体定义 - 与BPU驱动和FCOS后处理库交互
# ================================================================================

class hbSysMem_t(ctypes.Structure):
    """BPU系统内存结构体"""
    _fields_ = [
        ("phyAddr",ctypes.c_double),
        ("virAddr",ctypes.c_void_p),
        ("memSize",ctypes.c_int)
    ]

class hbDNNQuantiShift_yt(ctypes.Structure):
    """量化位移参数"""
    _fields_ = [
        ("shiftLen",ctypes.c_int),
        ("shiftData",ctypes.c_char_p)
    ]

class hbDNNQuantiScale_t(ctypes.Structure):
    """量化比例参数"""
    _fields_ = [
        ("scaleLen",ctypes.c_int),
        ("scaleData",ctypes.POINTER(ctypes.c_float)),
        ("zeroPointLen",ctypes.c_int),
        ("zeroPointData",ctypes.c_char_p)
    ]

class hbDNNTensorShape_t(ctypes.Structure):
    """张量形状结构体"""
    _fields_ = [
        ("dimensionSize",ctypes.c_int * 8),
        ("numDimensions",ctypes.c_int)
    ]

class hbDNNTensorProperties_t(ctypes.Structure):
    """张量属性结构体"""
    _fields_ = [
        ("validShape",hbDNNTensorShape_t),
        ("alignedShape",hbDNNTensorShape_t),
        ("tensorLayout",ctypes.c_int),
        ("tensorType",ctypes.c_int),
        ("shift",hbDNNQuantiShift_yt),
        ("scale",hbDNNQuantiScale_t),
        ("quantiType",ctypes.c_int),
        ("quantizeAxis", ctypes.c_int),
        ("alignedByteSize",ctypes.c_int),
        ("stride",ctypes.c_int * 8)
    ]

class hbDNNTensor_t(ctypes.Structure):
    """BPU张量结构体"""
    _fields_ = [
        ("sysMem",hbSysMem_t * 4),
        ("properties",hbDNNTensorProperties_t)
    ]


class FcosPostProcessInfo_t(ctypes.Structure):
    """
    FcosPostProcessInfo_t - FCOS后处理参数结构体

    【与分类任务的区别】
        目标检测需要更多的配置参数，包括NMS阈值等
    """
    _fields_ = [
        ("height",ctypes.c_int),
        ("width",ctypes.c_int),
        ("ori_height",ctypes.c_int),
        ("ori_width",ctypes.c_int),
        ("score_threshold",ctypes.c_float),
        ("nms_threshold",ctypes.c_float),
        ("nms_top_k",ctypes.c_int),
        ("is_pad_resize",ctypes.c_int)
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
    """Layout字符串转换为BPU内部整数值"""
    if Layout == "NCHW":
        return int(2)
    else:
        return int(0)

def limit_display_cord(coor):
    """
    限制坐标在显示范围内

    【功能】
        确保边界框坐标不会超出屏幕边界

    【参数】
        coor: [x1, y1, x2, y2] 坐标列表

    【返回值】
        限制后的坐标列表
    """
    coor[0] = max(min(1920, coor[0]), 0)
    coor[1] = max(min(1080, coor[1]), 2)  # 最小值设为2，留出文字显示空间
    coor[2] = max(min(1920, coor[2]), 0)
    coor[3] = max(min(1080, coor[3]), 0)
    return coor

def get_classes():
    """
    获取COCO数据集80类目标名称列表

    【COCO数据集类别】
        涵盖了日常生活的常见物体：人、动物、交通工具、家具等
    """
    return np.array(["person", "bicycle", "car",
                     "motorcycle", "airplane", "bus",
                     "train", "truck", "boat",
                     "traffic light", "fire hydrant", "stop sign",
                     "parking meter", "bench", "bird",
                     "cat", "dog", "horse",
                     "sheep", "cow", "elephant",
                     "bear", "zebra", "giraffe",
                     "backpack", "umbrella", "handbag",
                     "tie", "suitcase", "frisbee",
                     "skis", "snowboard", "sports ball",
                     "kite", "baseball bat", "baseball glove",
                     "skateboard", "surfboard", "tennis racket",
                     "bottle", "wine glass", "cup",
                     "fork", "knife", "spoon",
                     "bowl", "banana", "apple",
                     "sandwich", "orange", "broccoli",
                     "carrot", "hot dog", "pizza",
                     "donut", "cake", "chair",
                     "couch", "potted plant", "bed",
                     "dining table", "toilet", "tv",
                     "laptop", "mouse", "remote",
                     "keyboard", "cell phone", "microwave",
                     "oven", "toaster", "sink",
                     "refrigerator", "book", "clock",
                     "vase", "scissors", "teddy bear",
                     "hair drier", "toothbrush"])

def bgr2nv12_opencv(image):
    """
    BGR图像转NV12格式

    【NV12格式】
        Y平面：H x W（亮度）
        UV平面：H/2 x W（色度，U/V交错）
    """
    height, width = image.shape[0], image.shape[1]
    area = height * width
    yuv420p = cv2.cvtColor(image, cv2.COLOR_BGR2YUV_I420).reshape((area * 3 // 2,))
    y = yuv420p[:area]
    uv_planar = yuv420p[area:].reshape((2, area // 4))
    uv_packed = uv_planar.transpose((1, 0)).reshape((area // 2,))

    nv12 = np.zeros_like(yuv420p)
    nv12[:height * width] = y
    nv12[height * width:] = uv_packed
    return nv12


def draw_bboxs(image, bboxes, ori_w, ori_h, target_w, target_h, classes=get_classes()):
    """
    在图像上绘制边界框

    【参数】
        image: 输入/输出图像
        bboxes: 边界框列表
        ori_w, ori_h: 原始图像尺寸
        target_w, target_h: 目标显示尺寸
        classes: 类别名称列表

    【绘制内容】
        - 矩形边界框（不同类别颜色不同）
        - 类别名称和置信度文字
        - 文字背景框
    """
    num_classes = len(classes)
    image_h, image_w, channel = image.shape

    # 为每个类别生成不同的颜色（HSV色彩空间转换）
    hsv_tuples = [(1.0 * x / num_classes, 1., 1.) for x in range(num_classes)]
    colors = list(map(lambda x: colorsys.hsv_to_rgb(*x), hsv_tuples))
    colors = list(
        map(lambda x: (int(x[0] * 255), int(x[1] * 255), int(x[2] * 255)),
            colors))

    # 根据图像尺寸自适应调整线宽和字体大小
    fontScale = 0.5
    bbox_thick = int(0.6 * (image_h + image_w) / 600)

    # 计算从模型输出坐标到显示坐标的缩放比例
    scale_x = target_w / ori_w
    scale_y = target_h / ori_h

    for i, result in enumerate(bboxes):
        bbox = result['bbox']   # 边界框坐标 [x1, y1, x2, y2]
        score = result['score']  # 置信度得分
        id = int(result['id'])   # 类别ID
        name = result['name']    # 类别名称

        # 坐标缩放到显示尺寸
        coor = [round(i) for i in bbox]
        coor[0] = int(coor[0] * scale_x)
        coor[1] = int(coor[1] * scale_y)
        coor[2] = int(coor[2] * scale_x)
        coor[3] = int(coor[3] * scale_y)

        # 获取类别对应的颜色
        bbox_color = colors[id]
        c1, c2 = (coor[0], coor[1]), (coor[2], coor[3])

        # 绘制矩形边界框
        cv2.rectangle(image, c1, c2, bbox_color, bbox_thick)

        # 准备显示文字
        classes_name = name
        bbox_mess = '%s: %.2f' % (classes_name, score)

        # 计算文字大小，用于绘制背景框
        t_size = cv2.getTextSize(bbox_mess,
                                 0,
                                 fontScale,
                                 thickness=bbox_thick // 2)[0]

        # 绘制文字背景框（填充）
        cv2.rectangle(image, c1, (c1[0] + t_size[0], c1[1] - t_size[1] - 3),
                      bbox_color, -1)

        # 绘制文字
        cv2.putText(image,
                    bbox_mess, (c1[0], c1[1] - 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    fontScale, (0, 0, 0),
                    bbox_thick // 2,
                    lineType=cv2.LINE_AA)

        print("{} is in the picture with confidence:{:.4f}".format(
            classes_name, score))

    return image

def get_display_res():
    """
    获取HDMI显示分辨率

    【返回值】
        (width, height): 显示分辨率

    【说明】
        如果系统没有get_hdmi_res工具，默认返回1920x1080
    """
    if os.path.exists("/usr/bin/get_hdmi_res") == False:
        return 1920, 1080

    import subprocess
    p = subprocess.Popen(["/usr/bin/get_hdmi_res"], stdout=subprocess.PIPE)
    result = p.communicate()
    res = result[0].split(b',')
    res[1] = max(min(int(res[1]), 1920), 0)
    res[0] = max(min(int(res[0]), 1080), 0)
    return int(res[1]), int(res[0])


def is_usb_camera(device):
    """检测设备是否为可用的USB摄像头"""
    try:
        cap = cv2.VideoCapture(device)
        if not cap.isOpened():
            return False
        cap.release()
        return True
    except Exception:
        return False

def find_first_usb_camera():
    """查找第一个可用的USB摄像头"""
    video_devices = [os.path.join('/dev', dev) for dev in os.listdir('/dev') if dev.startswith('video')]
    for dev in video_devices:
        if is_usb_camera(dev):
            return dev
    return None

def print_properties(pro):
    """打印Tensor属性"""
    print("tensor type:", pro.tensor_type)
    print("data type:", pro.dtype)
    print("layout:", pro.layout)
    print("shape:", pro.shape)

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

    # 打印模型输入输出属性
    print_properties(models[0].inputs[0].properties)
    print(len(models[0].outputs))
    for output in models[0].outputs:
        print_properties(output.properties)

    # ==========================================================================
    # 第2步：初始化USB摄像头
    # ==========================================================================
    if len(sys.argv) > 1:
        video_device = sys.argv[1]
    else:
        video_device = find_first_usb_camera()

    if video_device is None:
        print("No USB camera found.")
        sys.exit(-1)

    print(f"Opening video device: {video_device}")
    cap = cv2.VideoCapture(video_device)
    if(not cap.isOpened()):
        exit(-1)

    print("Open usb camera successfully")

    # 配置摄像头参数
    # 设置输出格式为MJPEG，分辨率640x480
    codec = cv2.VideoWriter_fourcc( 'M', 'J', 'P', 'G' )
    cap.set(cv2.CAP_PROP_FOURCC, codec)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    # ==========================================================================
    # 第3步：初始化HDMI显示
    # ==========================================================================
    disp = srcampy.Display()

    # 获取支持的显示分辨率列表
    resolution_list = disp.get_display_res()
    for res in resolution_list:
        if res[0] == 0 | res[1] == 0:
            break
        disp_w = res[0]
        disp_h = res[1]

    # 启动显示
    disp.display(0, disp_w, disp_h)

    # ==========================================================================
    # 第4步：配置FCOS后处理参数
    # ==========================================================================
    fcos_postprocess_info = FcosPostProcessInfo_t()
    fcos_postprocess_info.height = 512
    fcos_postprocess_info.width = 512
    fcos_postprocess_info.ori_height = disp_h
    fcos_postprocess_info.ori_width = disp_w
    fcos_postprocess_info.score_threshold = 0.5  # 置信度阈值50%
    fcos_postprocess_info.nms_threshold = 0.6     # NMS阈值60%
    fcos_postprocess_info.nms_top_k = 5          # 最多返回5个检测框
    fcos_postprocess_info.is_pad_resize = 0

    # 准备输出Tensor数组
    output_tensors = (hbDNNTensor_t * len(models[0].outputs))()

    for i in range(len(models[0].outputs)):
        output_tensors[i].properties.tensorLayout = get_TensorLayout(models[0].outputs[i].properties.layout)

        if (len( models[0].outputs[i].properties.scale_data) == 0):
            output_tensors[i].properties.quantiType = 0
        else:
            output_tensors[i].properties.quantiType = 2
            scale_data_tmp = models[0].outputs[i].properties.scale_data.reshape(1, 1, 1, models[0].outputs[i].properties.shape[3])
            output_tensors[i].properties.scale.scaleData = scale_data_tmp.ctypes.data_as(ctypes.POINTER(ctypes.c_float))

        for j in range(len(models[0].outputs[i].properties.shape)):
            output_tensors[i].properties.validShape.dimensionSize[j] = models[0].outputs[i].properties.shape[j]
            output_tensors[i].properties.alignedShape.dimensionSize[j] = models[0].outputs[i].properties.shape[j]

    # ==========================================================================
    # 第5步：主循环 - 实时目标检测
    # ==========================================================================
    start_time = time()
    image_counter = 0

    while True:
        # 捕获摄像头帧
        _, frame = cap.read()

        if frame is None:
            print("Failed to get image from usb camera")
            continue

        # 获取模型输入尺寸并resize图像
        h, w = models[0].inputs[0].properties.shape[2], models[0].inputs[0].properties.shape[3]
        des_dim = (w, h)
        resized_data = cv2.resize(frame, des_dim, interpolation=cv2.INTER_AREA)

        # 转换为NV12格式
        nv12_data = bgr2nv12_opencv(resized_data)

        # 执行推理
        t0 = time()
        outputs = models[0].forward(nv12_data)
        t1 = time()

        # ==========================================================================
        # FCOS多尺度后处理
        # ==========================================================================
        # FCOS使用5个不同尺度的特征图进行检测
        # strides = [8, 16, 32, 64, 128] 对应不同大小的感受野
        strides = [8, 16, 32, 64, 128]
        for i in range(len(strides)):
            # 根据量化类型设置正确的指针类型
            if (output_tensors[i].properties.quantiType == 0):
                output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                    outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    ctypes.c_void_p)
                output_tensors[i + 5].sysMem[0].virAddr = ctypes.cast(
                    outputs[i + 5].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    ctypes.c_void_p)
                output_tensors[i + 10].sysMem[0].virAddr = ctypes.cast(
                    outputs[i + 10].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    ctypes.c_void_p)
            else:
                output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                    outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                    ctypes.c_void_p)
                output_tensors[i + 5].sysMem[0].virAddr = ctypes.cast(
                    outputs[i + 5].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                    ctypes.c_void_p)
                output_tensors[i + 10].sysMem[0].virAddr = ctypes.cast(
                    outputs[i + 10].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                    ctypes.c_void_p)

            # 调用FCOS后处理
            libpostprocess.FcosdoProcess(
                output_tensors[i],
                output_tensors[i + 5],
                output_tensors[i + 10],
                ctypes.pointer(fcos_postprocess_info),
                i)

        # 获取并解析检测结果
        result_str = get_Postprocess_result(ctypes.pointer(fcos_postprocess_info))
        result_str = result_str.decode('utf-8')
        t2 = time()

        # 解析JSON结果
        data = json.loads(result_str[14:])

        # 调整图像尺寸以适应显示
        if frame.shape[0] != disp_h or frame.shape[1] != disp_w:
            frame = cv2.resize(frame, (disp_w, disp_h), interpolation=cv2.INTER_AREA)

        # 在图像上绘制检测框
        box_bgr = draw_bboxs(frame, data, fcos_postprocess_info.width, fcos_postprocess_info.height, disp_w, disp_h)

        # 转换为NV12并显示
        box_nv12 = bgr2nv12_opencv(box_bgr)
        disp.set_img(box_nv12.tobytes())

        # 计算并输出FPS
        finish_time = time()
        image_counter += 1
        if finish_time - start_time > 10:
            print(start_time, finish_time, image_counter)
            print("FPS: {:.2f}".format(image_counter / (finish_time - start_time)))
            start_time = finish_time
            image_counter = 0

# ================================================================================
# 【FCOS算法原理简述】
# ================================================================================
# FCOS（Fully Convolutional One-Stage Object Detector）是一种无锚框目标检测算法
#
# 核心思想：
# 1. 将目标检测问题转化为像素级分类和回归问题
# 2. 对特征图的每个像素预测：类别、边界框坐标、中心度
# 3. 使用FPN（Feature Pyramid Network）实现多尺度检测
#
# 与YOLO的区别：
# | 特性     | FCOS              | YOLO                |
# |---------|-------------------|---------------------|
# | 锚框     | 无锚框            | 有锚框              |
# | 检测方式 | 逐像素预测         | 网格单元预测        |
# | 多尺度   | FPN金字塔         | 多尺度特征图        |
# | 后处理   | NMS               | NMS                 |
#
# FCOS的优势：
# - 不需要预设锚框，减少了超参数
# - 可以检测任意形状的目标
# - 对小目标检测效果更好
