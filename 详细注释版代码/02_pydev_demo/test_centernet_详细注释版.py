#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_centernet.py - CenterNet目标检测推理示例
================================================================================

【程序功能】
本程序使用CenterNet（以ResNet101为backbone）目标检测模型进行图像推理。
CenterNet是一种创新的"无锚框"目标检测方法，将目标检测问题转化为关键点检测问题。

【模型信息】
- 模型名称：CenterNet-ResNet101
- 输入尺寸：512x512像素
- 输入格式：NV12
- 支持80类目标检测（COCO数据集）

【CenterNet核心思想】
CenterNet将目标检测重新定义为：
1. 中心点检测：预测物体的中心点热力图
2. 尺寸预测：预测物体的宽度和高度
3. 偏移预测：预测中心点的亚像素偏移

【CenterNet vs 传统锚框检测器】
| 特性           | CenterNet              | SSD/YOLO              |
|----------------|------------------------|-----------------------|
| 锚框机制       | 无锚框                | 使用预定义锚框        |
| 检测方式       | 关键点检测            | 网格+锚框预测        |
| 优点           | 简洁、无需NMS         | 成熟、精度高          |
| 缺点           | 对密集物体效果可能较差 | 需要调参、依赖NMS    |

【运行方式】
cd pydev_demo/11_centernet_sample/
python3 test_centernet.py

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
        ("alignedByteSize",ctypes.c_int),
        ("stride",ctypes.c_int * 8)
    ]

class hbDNNTensor_t(ctypes.Structure):
    """BPU张量结构体"""
    _fields_ = [
        ("sysMem",hbSysMem_t * 4),
        ("properties",hbDNNTensorProperties_t)
    ]


class CenternetPostProcessInfo_t(ctypes.Structure):
    """
    CenternetPostProcessInfo_t - CenterNet后处理参数结构体

    【CenterNet输出】
        - 热力图（Heatmap）：表示中心点位置
        - 尺寸图（Size）：表示边界框宽高
        - 偏移图（Offset）：中心点亚像素偏移
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
# 加载CenterNet后处理库
# ================================================================================

libpostprocess = ctypes.CDLL('/usr/lib/libpostprocess.so')

get_Postprocess_result = libpostprocess.CenternetPostProcess
get_Postprocess_result.argtypes = [ctypes.POINTER(CenternetPostProcessInfo_t)]
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
    # 第1步：加载CenterNet-ResNet101模型
    # ==========================================================================
    models = dnn.load('../models/centernet_resnet101_512x512_nv12.bin')

    print_properties(models[0].inputs[0].properties)
    print(len(models[0].outputs))
    for output in models[0].outputs:
        print_properties(output.properties)

    # ==========================================================================
    # 第2步：读取并预处理图像
    # ==========================================================================
    img_file = cv2.imread('./kite.jpg')
    h, w = get_hw(models[0].inputs[0].properties)
    des_dim = (w, h)
    resized_data = cv2.resize(img_file, des_dim, interpolation=cv2.INTER_AREA)
    nv12_data = bgr2nv12_opencv(resized_data)

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
    centernet_postprocess_info = CenternetPostProcessInfo_t()
    centernet_postprocess_info.height = h
    centernet_postprocess_info.width = w
    org_height, org_width = img_file.shape[0:2]
    centernet_postprocess_info.ori_height = org_height
    centernet_postprocess_info.ori_width = org_width
    centernet_postprocess_info.score_threshold = 0.4
    centernet_postprocess_info.nms_threshold = 0.45
    centernet_postprocess_info.nms_top_k = 20
    centernet_postprocess_info.is_pad_resize = 0

    # ==========================================================================
    # 第5步：填充Tensor并调用后处理
    # ==========================================================================
    output_tensors = (hbDNNTensor_t * len(models[0].outputs))()
    for i in range(len(models[0].outputs)):
        output_tensors[i].properties.tensorLayout = get_TensorLayout(outputs[i].properties.layout)

        if (len(outputs[i].properties.scale_data) == 0):
            output_tensors[i].properties.quantiType = 0
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ctypes.c_void_p)
        else:
            output_tensors[i].properties.quantiType = 2
            output_tensors[i].properties.scale.scaleData = outputs[i].properties.scale_data.ctypes.data_as(
                ctypes.POINTER(ctypes.c_float))
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                ctypes.c_void_p)

        for j in range(len(outputs[i].properties.shape)):
            output_tensors[i].properties.validShape.dimensionSize[j] = outputs[i].properties.shape[j]

    # CenterNet后处理需要三个输出：heatmap、size、offset
    libpostprocess.Centernet_resnet101_doProcess(
        output_tensors[0],
        output_tensors[1],
        output_tensors[2],
        ctypes.pointer(centernet_postprocess_info),
        0)

    # ==========================================================================
    # 第6步：解析结果
    # ==========================================================================
    result_str = get_Postprocess_result(ctypes.pointer(centernet_postprocess_info))
    result_str = result_str.decode('utf-8')
    t2 = time.time()
    print("postprocess time is :", (t2 - t1))

    # ==========================================================================
    # 第7步：绘制检测结果
    # ==========================================================================
    t0 = time.time()

    data = json.loads(result_str[20:])

    for result in data:
        bbox = result['bbox']
        score = result['score']
        id = result['id']
        name = result['name']

        print(f"bbox: {bbox}, score: {score}, id: {id}, name: {name}")

        cv2.rectangle(img_file,
                     (int(bbox[0]), int(bbox[1])),
                     (int(bbox[2]), int(bbox[3])),
                     (0, 255, 0), 2)

        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(img_file,
                    f'{name} {score:.2f}',
                    (int(bbox[0]), int(bbox[1]) - 10),
                    font, 0.5, (0, 255, 0), 1)

    cv2.imwrite('output_image.jpg', img_file)

    t1 = time.time()
    print("draw result time is :", (t1 - t0))

# ================================================================================
# 【CenterNet算法原理】
# ================================================================================
# CenterNet将目标检测问题转化为三个关键点检测问题：
#
# 1. 中心点热力图（Heatmap）
#    - 尺寸：H/4 x W/4 x C（C为类别数）
#    - 预测每个位置是否是某类物体的中心点
#    - 使用高斯热力图表示中心点位置
#
# 2. 尺寸图（Size）
#    - 尺寸：H/4 x W/4 x 2（宽和高）
#    - 预测以该点为中心的物体尺寸
#
# 3. 偏移图（Offset）
#    - 尺寸：H/4 x W/4 x 2
#    - 预测中心点的亚像素偏移（因为热力图是下采样后的）
#
# 【检测流程】
# 1. 从热力图中提取所有局部最大值点
# 2. 根据阈值过滤低置信度点
# 3. 结合尺寸图和偏移图恢复边界框
# 4. 直接输出检测结果，无需NMS
#
# 【优势】
# - 端到端，无需锚框设计
# - 无需NMS后处理
# - 可迁移到其他关键点检测任务（人体姿态估计等）
