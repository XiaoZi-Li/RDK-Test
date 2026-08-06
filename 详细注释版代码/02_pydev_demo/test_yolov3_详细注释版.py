#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_yolov3.py - YOLOv3目标检测推理示例
================================================================================

【程序功能】
本程序使用YOLOv3（You Only Look Once v3）目标检测模型对图像进行检测推理。
YOLOv3是一个经典的单阶段目标检测器，以其速度和精度平衡著称。

【模型信息】
- 模型名称：YOLOv3
- 输入尺寸：416x416像素
- 输入格式：NV12
- 支持80类目标检测（COCO数据集）

【YOLOv3算法特点】
1. 单阶段检测：直接从图像到边界框和类别概率的端到端检测
2. 多尺度预测：在三个不同尺度的特征图上进行检测（13x13, 26x26, 52x52）
3. 锚框机制：使用预定义的锚框提高检测精度
4. 类别预测：每个检测头使用逻辑回归进行类别预测（支持多标签分类）

【YOLOv3 vs YOLOv5】
- YOLOv3使用逻辑回归进行类别预测
- YOLOv5使用交叉熵损失和Focal Loss
- YOLOv5有更现代的网络结构（Focus、CSP等）
- YOLOv5推理速度通常更快

【运行方式】
cd pydev_demo/06_yolov3_sample/
python3 test_yolov3.py

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
# C结构体定义 - 与BPU驱动和YOLOv3后处理库交互
# ================================================================================

class hbSysMem_t(ctypes.Structure):
    """
    hbSysMem_t - BPU系统内存结构体

    【功能】
        描述BPU使用的内存区域信息
    """
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


class Yolov3PostProcessInfo_t(ctypes.Structure):
    """
    Yolov3PostProcessInfo_t - YOLOv3后处理参数结构体

    【参数说明】
        height/width: 模型输入尺寸（416x416）
        ori_height/ori_width: 原始图像尺寸
        score_threshold: 置信度阈值，低于此值的检测结果被过滤
        nms_threshold: 非极大值抑制阈值，用于去除重叠的检测框
        nms_top_k: 最多保留的检测框数量
        is_pad_resize: 是否使用填充方式调整图像大小
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
# 加载YOLOv3后处理库
# ================================================================================

libpostprocess = ctypes.CDLL('/usr/lib/libpostprocess.so')

get_Postprocess_result = libpostprocess.Yolov3PostProcess
get_Postprocess_result.argtypes = [ctypes.POINTER(Yolov3PostProcessInfo_t)]
get_Postprocess_result.restype = ctypes.c_char_p

# ================================================================================
# 辅助函数
# ================================================================================

def get_TensorLayout(Layout):
    """
    Layout字符串转换为BPU内部整数值

    【返回值】
        2 = NCHW格式
        0 = NHWC格式
    """
    if Layout == "NCHW":
        return int(2)
    else:
        return int(0)

def bgr2nv12_opencv(image):
    """
    BGR图像转NV12格式

    【NV12格式】
        Y平面：H x W（亮度分量）
        UV平面：H/2 x W（色度分量，U/V交错）

    【处理流程】
        BGR -> YUV_I420 -> 分离Y/U/V -> UV交错 -> NV12
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
# 主程序入口
# ================================================================================

if __name__ == '__main__':
    # ==========================================================================
    # 第1步：加载YOLOv3模型
    # ==========================================================================
    models = dnn.load('../models/yolov3_416x416_nv12.bin')

    # 打印模型输入输出属性
    print_properties(models[0].inputs[0].properties)
    print(len(models[0].outputs))
    for output in models[0].outputs:
        print_properties(output.properties)

    # ==========================================================================
    # 第2步：读取并预处理测试图像
    # ==========================================================================
    img_file = cv2.imread('./kite.jpg')
    h, w = get_hw(models[0].inputs[0].properties)
    des_dim = (w, h)
    resized_data = cv2.resize(img_file, des_dim, interpolation=cv2.INTER_AREA)
    nv12_data = bgr2nv12_opencv(resized_data)

    # ==========================================================================
    # 第3步：执行模型推理
    # ==========================================================================
    t0 = time.time()
    outputs = models[0].forward(nv12_data)
    t1 = time.time()
    print("inferece time is :", (t1 - t0))

    # ==========================================================================
    # 第4步：准备后处理参数
    # ==========================================================================
    yolov3_postprocess_info = Yolov3PostProcessInfo_t()
    yolov3_postprocess_info.height = h
    yolov3_postprocess_info.width = w
    org_height, org_width = img_file.shape[0:2]
    yolov3_postprocess_info.ori_height = org_height
    yolov3_postprocess_info.ori_width = org_width
    # 置信度阈值30%
    yolov3_postprocess_info.score_threshold = 0.3
    # NMS阈值45%（YOLOv3通常使用较高的NMS阈值）
    yolov3_postprocess_info.nms_threshold = 0.45
    # 最多保留20个检测框
    yolov3_postprocess_info.nms_top_k = 20
    yolov3_postprocess_info.is_pad_resize = 0

    # ==========================================================================
    # 第5步：填充输出Tensor信息并调用后处理
    # ==========================================================================
    output_tensors = (hbDNNTensor_t * len(models[0].outputs))()
    for i in range(len(models[0].outputs)):
        output_tensors[i].properties.tensorLayout = get_TensorLayout(outputs[i].properties.layout)

        # 设置量化轴
        if output_tensors[i].properties.tensorLayout == 2:
            output_tensors[i].properties.quantizeAxis = 1
        else:
            output_tensors[i].properties.quantizeAxis = 3

        if (len(outputs[i].properties.scale_data) == 0):
            # 无量化：使用float32
            output_tensors[i].properties.quantiType = 0
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ctypes.c_void_p)
        else:
            # INT8量化：使用int32和scale
            output_tensors[i].properties.quantiType = 2
            output_tensors[i].properties.scale.scaleData = outputs[i].properties.scale_data.ctypes.data_as(
                ctypes.POINTER(ctypes.c_float))
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                ctypes.c_void_p)

        for j in range(len(outputs[i].properties.shape)):
            output_tensors[i].properties.validShape = ctypes.cast(
                outputs[i].properties.validShape,
                ctypes.POINTER(hbDNNTensorShape_t)).contents
            output_tensors[i].properties.alignedShape = ctypes.cast(
                outputs[i].properties.alignedShape,
                ctypes.POINTER(hbDNNTensorShape_t)).contents

        libpostprocess.Yolov3doProcess(
            output_tensors[i],
            ctypes.pointer(yolov3_postprocess_info),
            i)

    # ==========================================================================
    # 第6步：获取并解析检测结果
    # ==========================================================================
    result_str = get_Postprocess_result(ctypes.pointer(yolov3_postprocess_info))
    result_str = result_str.decode('utf-8')
    t2 = time.time()
    print("postprocess time is :", (t2 - t1))

    # ==========================================================================
    # 第7步：绘制检测结果
    # ==========================================================================
    t0 = time.time()

    # 解析JSON结果
    data = json.loads(result_str[16:])

    # 遍历每个检测结果
    for result in data:
        bbox = result['bbox']   # 边界框坐标 [x1, y1, x2, y2]
        score = result['score'] # 置信度得分
        id = result['id']      # 类别ID
        name = result['name']  # 类别名称

        print(f"bbox: {bbox}, score: {score}, id: {id}, name: {name}")

        # 绘制绿色边界框
        cv2.rectangle(img_file,
                     (int(bbox[0]), int(bbox[1])),
                     (int(bbox[2]), int(bbox[3])),
                     (0, 255, 0), 2)

        # 在边界框上方显示类别名称和置信度
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(img_file,
                    f'{name} {score:.2f}',
                    (int(bbox[0]), int(bbox[1]) - 10),
                    font, 0.5, (0, 255, 0), 1)

    # 保存结果图像
    cv2.imwrite('output_image.jpg', img_file)

    t1 = time.time()
    print("draw result time is :", (t1 - t0))

# ================================================================================
# 【YOLOv3算法原理】
# ================================================================================
# YOLOv3（You Only Look Once v3）核心原理：
#
# 1. 网络结构
#    - Darknet-53作为backbone（53层卷积网络）
#    - FPN（Feature Pyramid Network）用于多尺度特征融合
#    - 3个检测头分别在13x13、26x26、52x52特征图上检测
#
# 2. 检测机制
#    - 每个网格单元预测3个边界框（锚框）
#    - 每个边界框预测：位置(x,y,w,h)、置信度、80类类别概率
#    - 坐标预测使用sigmoid函数归一化到[0,1]
#
# 3. 损失函数
#    - 边界框回归：MSE损失
#    - 置信度：二元交叉熵
#    - 类别预测：二元交叉熵（支持多标签）
#
# 4. 后处理
#    - 置信度阈值过滤
#    - 非极大值抑制（NMS）去除重叠框
#
# 【YOLOv3性能】
# - 输入尺寸：416x416
# - 在COCO上mAP@0.5：55.3%
# - 推理速度：约45 FPS（Titan X GPU）
