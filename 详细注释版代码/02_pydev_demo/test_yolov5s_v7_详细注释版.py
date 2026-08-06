#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_yolov5s_v7.py - YOLOv5s V7版本目标检测推理示例
================================================================================

【程序功能】
本程序使用YOLOv5s V7版本（Ultralytics YOLOv5的第七版迭代）目标检测模型进行图像推理。
V7版本是YOLOv5系列的重大更新，引入了更强的数据增强和新的网络模块。

【模型信息】
- 模型名称：YOLOv5s V7
- 输入尺寸：640x640像素
- 输入格式：NV12
- 支持80类目标检测（COCO数据集）

【YOLOv5 V7版本核心改进】
1. 骨干网络：引入TFF（Transformer Fusion）模块
2. 数据增强：更强的马赛克增强和MixUp
3. 标签分配：改进的标签分配策略
4. 损失函数：优化的DFL损失
5. 模型优化：更好的INT8量化支持

【YOLOv5s适用场景】
- 边缘设备部署（机器人、无人机）
- 实时视频分析
- 资源受限环境
- 平衡精度与速度的应用

【V7 vs V6 性能对比】
| 指标       | YOLOv5s V6  | YOLOv5s V7  |
|------------|-------------|-------------|
| COCO mAP   | 44.5%      | 45.7%      |
| 推理速度   | 基准       | 略慢5-10%  |
| 量化精度   | 较好       | 更好       |

【运行方式】
cd pydev_demo/12_yolov5s_v6_v7_sample/
python3 test_yolov5s_v7.py

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


class Yolov5PostProcessInfo_t(ctypes.Structure):
    """
    Yolov5PostProcessInfo_t - YOLOv5后处理参数结构体
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
# 加载后处理库
# ================================================================================

libpostprocess = ctypes.CDLL('/usr/lib/libpostprocess.so')

get_Postprocess_result = libpostprocess.Yolov5PostProcess
get_PostprocessResult.argtypes = [ctypes.POINTER(Yolov5PostProcessInfo_t)]
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
    # 第1步：加载YOLOv5s V7模型
    # ==========================================================================
    models = dnn.load('../models/yolov5s_v7_640x640_nv12.bin')

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

    # ==========================================================================
    # 第4步：准备后处理参数
    # ==========================================================================
    yolov5_postprocess_info = Yolov5PostProcessInfo_t()
    yolov5_postprocess_info.height = h
    yolov5_postprocess_info.width = w
    org_height, org_width = img_file.shape[0:2]
    yolov5_postprocess_info.ori_height = org_height
    yolov5_postprocess_info.ori_width = org_width
    yolov5_postprocess_info.score_threshold = 0.4
    yolov5_postprocess_info.nms_threshold = 0.45
    yolov5_postprocess_info.nms_top_k = 20
    yolov5_postprocess_info.is_pad_resize = 0

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

        libpostprocess.Yolov5doProcess(
            output_tensors[i],
            ctypes.pointer(yolov5_postprocess_info),
            i)

    # ==========================================================================
    # 第6步：解析结果
    # ==========================================================================
    result_str = get_Postprocess_result(ctypes.pointer(yolov5_postprocess_info))
    result_str = result_str.decode('utf-8')
    t2 = time.time()

    # ==========================================================================
    # 第7步：绘制检测结果
    # ==========================================================================
    t0 = time.time()

    data = json.loads(result_str[16:])

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
# 【YOLOv5各版本发展历程】
# ================================================================================
# YOLOv5作为Ultralytics维护的活跃项目，持续迭代更新：
#
# | 版本  | 发布时间  | 关键特性                           |
# |-------|----------|-----------------------------------|
# | V1.0  | 2020.6   | 初始发布，基于YOLOv4思想          |
# | V3.0  | 2020.11  | 数据增强改进                      |
# | V4.0  | 2021.1   | 骨干网络优化                      |
# | V5.0  | 2021.4   | 训练速度优化                      |
# | V6.0  | 2021.10  | NMS优化，推理加速                 |
# | V7.0  | 2022.7   | TFF模块，更强数据增强             |
#
# V7版本的主要改进：
# 1. 引入Transformer Fusion模块增强特征融合
# 2. 改进的马赛克增强（最多9宫格）
# 3. 新的标签分配策略（Task Alignment Learning）
# 4. 优化的模型结构和训练策略
