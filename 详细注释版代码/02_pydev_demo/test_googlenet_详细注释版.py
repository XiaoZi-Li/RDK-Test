#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_googlenet.py - GoogleNet模型图像分类推理示例
================================================================================

【程序功能】
本程序使用GoogleNet（Inception V1）深度学习模型对图像进行分类推理。
GoogleNet是2014年ImageNet竞赛的冠军模型，以其高效的"Inception模块"著称。

【模型信息】
- 模型名称：GoogleNet
- 输入尺寸：224x224像素
- 输入格式：NV12（YUV420格式）
- 输出：1000类ImageNet图像分类结果

【GoogleNet特点】
1. Inception模块：并行使用多种卷积核尺寸，捕获不同尺度的特征
2. 1x1卷积降维：减少参数量和计算量
3. 全局平均池化：替代全连接层，减少过拟合
4. 辅助分类器：训练时帮助梯度传播

【运行方式】
cd pydev_demo/01_basic_sample/
python3 test_googlenet.py

================================================================================
"""

try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn
import numpy as np
import cv2

import time
import ctypes
import json

output_tensors = None

fcos_postprocess_info = None

# ================================================================================
# C结构体定义 - 与BPU驱动和后处理库交互
# ================================================================================

class hbSysMem_t(ctypes.Structure):
    """
    hbSysMem_t - BPU系统内存结构体
    描述内存区域的物理地址、虚拟地址和大小
    """
    _fields_ = [
        ("phyAddr",ctypes.c_double),
        ("virAddr",ctypes.c_void_p),
        ("memSize",ctypes.c_int)
    ]

class hbDNNQuantiShift_yt(ctypes.Structure):
    """
    hbDNNQuantiShift_yt - 量化位移参数结构体
    用于非对称量化中的shift参数
    """
    _fields_ = [
        ("shiftLen",ctypes.c_int),
        ("shiftData",ctypes.c_char_p)
    ]

class hbDNNQuantiScale_t(ctypes.Structure):
    """
    hbDNNQuantiScale_t - 量化比例参数结构体
    用于非对称量化中的scale和zero_point参数
    """
    _fields_ = [
        ("scaleLen",ctypes.c_int),
        ("scaleData",ctypes.POINTER(ctypes.c_float)),
        ("zeroPointLen",ctypes.c_int),
        ("zeroPointData",ctypes.c_char_p)
    ]

class hbDNNTensorShape_t(ctypes.Structure):
    """
    hbDNNTensorShape_t - 张量形状结构体
    描述多维张量的维度信息
    """
    _fields_ = [
        ("dimensionSize",ctypes.c_int * 8),
        ("numDimensions",ctypes.c_int)
    ]

class hbDNNTensorProperties_t(ctypes.Structure):
    """
    hbDNNTensorProperties_t - 张量属性结构体
    包含形状、布局、量化参数等所有张量属性
    """
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
    """
    hbDNNTensor_t - BPU张量结构体
    完整的BPU张量描述（内存+属性）
    """
    _fields_ = [
        ("sysMem",hbSysMem_t * 4),
        ("properties",hbDNNTensorProperties_t)
    ]


class ClassificationPostProcessInfo_t(ctypes.Structure):
    """
    ClassificationPostProcessInfo_t - 分类后处理参数结构体

    【字段说明】
        height/width: 模型输入尺寸
        ori_height/ori_width: 原始图像尺寸
        score_threshold: 置信度阈值，低于此值的结果被过滤
        nms_threshold: 非极大值抑制阈值
        nms_top_k: 返回的最大结果数量
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
# 加载后处理库
# ================================================================================

libpostprocess = ctypes.CDLL('/usr/lib/libpostprocess.so')

get_Postprocess_result = libpostprocess.ClassificationPostProcess
get_Postprocess_result.argtypes = [ctypes.POINTER(ClassificationPostProcessInfo_t)]
get_Postprocess_result.restype = ctypes.c_char_p

# ================================================================================
# 辅助函数
# ================================================================================

def get_TensorLayout(Layout):
    """
    将Layout字符串转换为BPU内部整数值

    【参数】
        Layout: "NCHW"或"NHWC"

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
    将BGR图像转换为NV12格式

    【NV12格式】
        Y平面：H x W（亮度）
        UV平面：H/2 x W（色度，U和V交错）

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

def print_properties(pro):
    """
    打印Tensor属性信息

    【打印内容】
        - tensor_type: 张量类型
        - dtype: 数据类型
        - layout: 布局格式
        - shape: 形状
    """
    print("tensor type:", pro.tensor_type)
    print("data type:", pro.dtype)
    print("layout:", pro.layout)
    print("shape:", pro.shape)


def get_hw(pro):
    """
    从Tensor属性中获取高度和宽度

    【说明】
        NCHW: shape = [B, C, H, W] -> 返回 [H, W]
        NHWC: shape = [B, H, W, C] -> 返回 [H, W]
    """
    if pro.layout == "NCHW":
        return pro.shape[2], pro.shape[3]
    else:
        return pro.shape[1], pro.shape[2]


# ================================================================================
# 主程序入口
# ================================================================================

if __name__ == '__main__':
    # ==========================================================================
    # 第1步：加载GoogleNet模型
    # ==========================================================================
    models = dnn.load('../models/googlenet_224x224_nv12.bin')

    # ==========================================================================
    # 第2步：打印模型输入输出属性
    # ==========================================================================
    print("=" * 10, "inputs[0] properties", "=" * 10)
    print_properties(models[0].inputs[0].properties)
    print("inputs[0] name is:", models[0].inputs[0].name)

    print("=" * 10, "outputs[0] properties", "=" * 10)
    print_properties(models[0].outputs[0].properties)
    print("outputs[0] name is:", models[0].outputs[0].name)


    # ==========================================================================
    # 第3步：读取并预处理测试图像
    # ==========================================================================
    img_file = cv2.imread('./zebra_cls.jpg')
    h, w = get_hw(models[0].inputs[0].properties)
    des_dim = (w, h)
    resized_data = cv2.resize(img_file, des_dim, interpolation=cv2.INTER_AREA)
    nv12_data = bgr2nv12_opencv(resized_data)

    # ==========================================================================
    # 第4步：执行模型推理
    # ==========================================================================
    outputs = models[0].forward(nv12_data)

    # ==========================================================================
    # 第5步：准备后处理参数
    # ==========================================================================
    t0 = time.time()

    classification_postprocess_info = ClassificationPostProcessInfo_t()
    classification_postprocess_info.height = h
    classification_postprocess_info.width = w
    org_height, org_width = img_file.shape[0:2]
    classification_postprocess_info.ori_height = org_height
    classification_postprocess_info.ori_width = org_width
    classification_postprocess_info.score_threshold = 0.3
    classification_postprocess_info.nms_threshold = 0
    classification_postprocess_info.nms_top_k = 1
    classification_postprocess_info.is_pad_resize = 0

    # ==========================================================================
    # 第6步：填充输出Tensor信息并调用后处理
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
            output_tensors[i].properties.validShape.numDimensions = len(outputs[i].properties.shape)
            output_tensors[i].properties.validShape.dimensionSize[j] = outputs[i].properties.shape[j]

        libpostprocess.ClassificationDoProcess(
            output_tensors[i],
            ctypes.pointer(classification_postprocess_info),
            i)

    # ==========================================================================
    # 第7步：获取并解析分类结果
    # ==========================================================================
    result_str = get_Postprocess_result(ctypes.pointer(classification_postprocess_info))
    result_str = result_str.decode('utf-8')
    t1 = time.time()
    print("postprocess time is :", (t1 - t0))

    # 解析JSON结果
    data = json.loads(result_str[25:])

    # 打印分类结果
    for result in data:
        prob = result['prob']      # 置信度
        label = result['label']    # 类别ID
        name = result['class_name'] # 类别名称

        print(f"cls id: {label}, Confidence: {prob}, class_name: {name}")

# ================================================================================
# 【GoogleNet vs EfficientNASNet 对比】
# ================================================================================
# | 特性         | GoogleNet        | EfficientNASNet     |
# |--------------|------------------|---------------------|
# | 参数量       | ~5M              | ~5.3M               |
# | 浮点运算量   | ~1.5G FLOPs      | ~1.2G FLOPs         |
# | 网络结构     | Inception模块    | NAS搜索结构          |
# | 输入尺寸     | 224x224          | 300x300             |
# | 特点         | 多尺度特征融合   | 高效计算            |
#
# 两者都是轻量级高性能网络，适合边缘设备部署
