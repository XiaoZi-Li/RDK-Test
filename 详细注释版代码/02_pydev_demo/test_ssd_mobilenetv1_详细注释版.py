#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ssd_mobilenetv1.py - SSD目标检测推理示例
================================================================================

【程序功能】
本程序使用SSD（Single Shot MultiBox Detector）与MobileNetV1结合的目标检测模型
进行图像推理。SSD是一个经典的单阶段目标检测器，以其速度和精度平衡著称。

【模型信息】
- 模型名称：SSD-MobileNetV1
- 输入尺寸：300x300像素
- 输入格式：NV12
- 支持80类目标检测（COCO数据集）

【SSD算法核心原理】
SSD采用"单阶段"检测策略，直接从特征图预测边界框和类别，避免了Faster R-CNN等
两阶段检测器的区域提议阶段，因此速度更快。

【SSD vs YOLO 对比】
| 特性         | SSD                | YOLOv3/v5           |
|--------------|--------------------|----------------------|
| 检测方式     | 多尺度特征图检测   | 单尺度特征图检测     |
| 锚框机制     | 多种尺度锚框       | 3个尺度锚框          |
| 速度         | 较快               | 非常快               |
| 精度         | 中等（mAP@0.5 43%）| 较高（mAP@0.5 55%+）|
| 适用场景     | 实时检测           | 实时+高精度检测      |

【运行方式】
cd pydev_demo/10_ssd_mobilenetv1_sample/
python3 test_ssd_mobilenetv1.py

【输出】
- output_image.jpg：带有检测结果的图像

================================================================================
"""

import numpy as np
import cv2
try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn
import time
import ctypes
import json
import math

def align_to_4(num):
    """
    将数值对齐到4的倍数

    【功能】
        BPU硬件要求某些参数按4字节对齐
    """
    return 4 * math.ceil(num / 4)

# ================================================================================
# C结构体定义
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
        ("alignedByteSize",ctype.c_int),
        ("stride",ctypes.c_int * 8)
    ]

class hbDNNTensor_t(ctypes.Structure):
    """BPU张量结构体"""
    _fields_ = [
        ("sysMem",hbSysMem_t * 4),
        ("properties",hbDNNTensorProperties_t)
    ]


class SsdPostProcessInfo_t(ctypes.Structure):
    """
    SsdPostProcessInfo_t - SSD后处理参数结构体

    【SSD特点】
        - nms_top_k=200：SSD使用更多候选框，需要更大的NMS处理数量
        - strides=[15,30,60,100,150,300]：6个不同尺度的特征图
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
# 加载SSD后处理库
# ================================================================================

libpostprocess = ctypes.CDLL('/usr/lib/libpostprocess.so')

get_Postprocess_result = libpostprocess.SsdPostProcess
get_Postprocess_result.argtypes = [ctypes.POINTER(SsdPostProcessInfo_t)]
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


def bgr2nv12_opencv(image):
    """
    BGR图像转NV12格式
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


def align_16(value):
    """将数值对齐到16字节边界"""
    return (value + 15) // 16 * 16


def bgr_to_nv12_custom_with_padding(bgr_image, aligned_width, aligned_height):
    """
    BGR图像转NV12格式（带内存对齐填充）

    【功能】
        确保转换后的数据满足BPU的内存对齐要求
    """
    height, width = bgr_image.shape[:2]

    yuv_image = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2YUV_I420)

    y_plane = np.zeros((aligned_height, aligned_width), dtype=np.uint8)
    uv_plane = np.zeros((aligned_height // 2, aligned_width), dtype=np.uint8)

    y_orig = yuv_image[:height, :]
    u_orig = yuv_image[height:height + height // 4].reshape(height // 2, width // 2)
    v_orig = yuv_image[height + height // 4:].reshape(height // 2, width // 2)

    for i in range(height):
        y_plane[i, :width] = y_orig[i, :]

    for i in range(height // 2):
        uv_plane[i, 0:width:2] = u_orig[i, :]
        uv_plane[i, 1:width:2] = v_orig[i, :]

    return y_plane, uv_plane


def combine_yuv_to_nv12(y_data, uv_data):
    """合并Y和UV数据为NV12格式"""
    return np.concatenate((y_data.flatten(), uv_data.flatten()))


def process_image(img_file, models_h, models_w):
    """
    图像预处理函数

    【参数】
        img_file: 输入图像
        models_h, models_w: 模型输入尺寸
    """
    h, w = (models_h, models_w)
    des_dim = (w, h)

    resized_data = cv2.resize(img_file, des_dim, interpolation=cv2.INTER_AREA)

    aligned_width = align_16(w)
    aligned_height = h

    y_data, uv_data = bgr_to_nv12_custom_with_padding(resized_data, aligned_width, aligned_height)

    return combine_yuv_to_nv12(y_data, uv_data)


def get_hw(pro):
    """获取Tensor的高度和宽度"""
    if pro.layout == "NCHW":
        return pro.shape[2], pro.shape[3]
    else:
        return pro.shape[1], pro.shape[2]


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
    # ==========================================================================
    # 第1步：加载SSD-MobileNetV1模型
    # ==========================================================================
    models = dnn.load('../models/ssd_mobilenetv1_300x300_nv12.bin')

    print_properties(models[0].inputs[0].properties)
    print(len(models[0].outputs))
    for output in models[0].outputs:
        print_properties(output.properties)

    # ==========================================================================
    # 第2步：读取并预处理图像
    # ==========================================================================
    img_file = cv2.imread('./2007_000241.jpg')
    h, w = get_hw(models[0].inputs[0].properties)
    nv12_data = process_image(img_file, h, w)

    # ==========================================================================
    # 第3步：执行推理
    # ==========================================================================
    t0 = time.time()
    outputs = models[0].forward(nv12_data)
    t1 = time.time()
    print("inferece time is :", (t1 - t0))

    # ==========================================================================
    # 第4步：准备后处理参数
    # ==========================================================================
    ssd_postprocess_info = SsdPostProcessInfo_t()
    ssd_postprocess_info.height = h
    ssd_postprocess_info.width = w
    org_height, org_width = img_file.shape[0:2]
    ssd_postprocess_info.ori_height = org_height
    ssd_postprocess_info.ori_width = org_width
    ssd_postprocess_info.score_threshold = 0.4
    ssd_postprocess_info.nms_threshold = 0.45
    ssd_postprocess_info.nms_top_k = 200  # SSD使用更多候选框
    ssd_postprocess_info.is_pad_resize = 0

    # ==========================================================================
    # 第5步：填充Tensor并调用后处理
    # ==========================================================================
    output_tensors = (hbDNNTensor_t * len(models[0].outputs))()
    for i in range(len(models[0].outputs)):
        output_tensors[i].properties.tensorLayout = get_TensorLayout(outputs[i].properties.layout)

        if (len(outputs[i].properties.scale_data) == 0):
            output_tensors[i].properties.quantiType = 0
        else:
            output_tensors[i].properties.quantiType = 2
            scale_data_tmp = outputs[i].properties.scale_data.reshape(1, 1, 1, models[0].outputs[i].properties.shape[3])
            output_tensors[i].properties.scale.scaleData = scale_data_tmp.ctypes.data_as(ctypes.POINTER(ctypes.c_float))

        for j in range(len(outputs[i].properties.shape)):
            output_tensors[i].properties.validShape = ctypes.cast(outputs[i].properties.validShape, ctypes.POINTER(hbDNNTensorShape_t)).contents
            output_tensors[i].properties.alignedShape = ctypes.cast(outputs[i].properties.alignedShape, ctypes.POINTER(hbDNNTensorShape_t)).contents

    # SSD使用6个不同尺度的特征图
    strides = [15, 30, 60, 100, 150, 300]
    for i in range(len(strides)):
        if (output_tensors[i].properties.quantiType == 0):
            output_tensors[i * 2].sysMem[0].virAddr = ctypes.cast(outputs[i * 2].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), ctypes.c_void_p)
            output_tensors[i * 2 + 1].sysMem[0].virAddr = ctypes.cast(outputs[i * 2 + 1].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), ctypes.c_void_p)
        else:
            output_tensors[i * 2].sysMem[0].virAddr = ctypes.cast(outputs[i * 2].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)), ctypes.c_void_p)
            output_tensors[i * 2 + 1].sysMem[0].virAddr = ctypes.cast(outputs[i * 2 + 1].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)), ctypes.c_void_p)

        libpostprocess.SsddoProcess(output_tensors[i * 2], output_tensors[i * 2 + 1], ctypes.pointer(ssd_postprocess_info), i)

    # ==========================================================================
    # 第6步：解析结果
    # ==========================================================================
    result_str = get_Postprocess_result(ctypes.pointer(ssd_postprocess_info))
    result_str = result_str.decode('utf-8')
    t2 = time.time()
    print("postprocess time is :", (t2 - t1))

    # ==========================================================================
    # 第7步：绘制检测结果
    # ==========================================================================
    t0 = time.time()

    result_str = result_str.replace('-nan', 'null').replace('nan', 'null')
    data = json.loads(result_str[13:])

    for result in data:
        bbox = result['bbox']
        score = result['score']
        id = result['id']
        name = result['name']

        # 过滤无效检测
        if score == None:
            continue
        if bbox[0] == 0 and bbox[1] == 0 and bbox[2] == (org_width - 1) and bbox[3] == (org_height - 1):
            print("Situations that require careful screening")
            continue

        print(f"bbox: {bbox}, score: {score}, id: {id}, name: {name}")

        cv2.rectangle(img_file, (int(bbox[0]), int(bbox[1])), (int(bbox[2]), int(bbox[3])), (0, 255, 0), 2)

        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(img_file, f'{name} {score:.2f}', (int(bbox[0]), int(bbox[1]) - 10), font, 0.5, (0, 255, 0), 1)

    cv2.imwrite('output_image.jpg', img_file)

    t1 = time.time()
    print("draw result time is :", (t1 - t0))

# ================================================================================
# 【SSD网络架构解析】
# ================================================================================
# SSD使用VGG16（或MobileNet）作为backbone，在多个尺度的特征图上进行检测：
#
# | 特征图  | 锚框尺度  | 用途                    |
# |---------|-----------|-------------------------|
# | 38x38  | 15, 30   | 检测小物体               |
# | 19x19  | 60, 105  | 检测中等物体             |
# | 10x10  | 150, 195 | 检测较大物体             |
# | 5x5    | 240, 285 | 检测大物体               |
# | 3x3    | 330, 375 | 检测非常大物体            |
# | 1x1    | 435, 480 | 检测超大规模物体         |
#
# 每个锚框预测：4个边界框坐标 + 80类类别分数
