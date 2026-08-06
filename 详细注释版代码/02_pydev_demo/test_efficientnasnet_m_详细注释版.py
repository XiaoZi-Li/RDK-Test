#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_efficientnasnet_m.py - EfficientNASNet模型图像分类推理示例
================================================================================

【程序功能】
本程序展示了如何使用D-Robotics开发板上的BPU（Byte Processing Unit，字节处理单元）
进行高效的神经网络模型推理。
程序使用EfficientNASNet模型对输入图像进行图像分类，识别图像中的物体类别。

【模型信息】
- 模型名称：EfficientNASNet-M（中规模版本）
- 输入尺寸：300x300像素
- 输入格式：NV12（YUV420格式，常用于视频和图像处理）
- 输出：1000类ImageNet图像分类结果

【技术要点】
1. DNN推理引擎：使用hobot_dnn Python API加载和运行神经网络模型
2. NV12格式转换：将OpenCV读取的BGR图像转换为NV12格式
3. 后处理调用：通过C库进行分类结果的非极大值抑制（NMS）和阈值过滤
4. 量化推理支持：支持INT8量化模型的推理加速

【运行方式】
# 进入脚本目录
cd pydev_demo/01_basic_sample/

# 运行分类推理
python3 test_efficientnasnet_m.py

# 需要准备模型文件：../models/efficientnasnet_m_300x300_nv12.bin
# 测试图片：./zebra_cls.jpg（斑马图片）

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
# C结构体定义 - 用于与BPU驱动和后处理库交互
# ================================================================================

class hbSysMem_t(ctypes.Structure):
    """
    hbSysMem_t - BPU系统内存结构体

    【功能】
        描述一块内存区域的物理地址、虚拟地址和大小
        用于BPU推理时传递输入输出tensor的内存信息

    【字段说明】
        phyAddr: 物理地址（Double类型，实际是64位地址）
        virAddr: 虚拟地址（void*指针）
        memSize: 内存大小（字节）
    """
    _fields_ = [
        ("phyAddr",ctypes.c_double),
        ("virAddr",ctypes.c_void_p),
        ("memSize",ctypes.c_int)
    ]

class hbDNNQuantiShift_yt(ctypes.Structure):
    """
    hbDNNQuantiShift_yt - 量化位移结构体

    【功能】
        用于非对称量化中的位移（shift）参数
        量化公式: real_value = (quantized_value + shift) * scale
    """
    _fields_ = [
        ("shiftLen",ctypes.c_int),
        ("shiftData",ctypes.c_char_p)
    ]

class hbDNNQuantiScale_t(ctypes.Structure):
    """
    hbDNNQuantiScale_t - 量化比例结构体

    【功能】
        用于非对称量化中的比例（scale）和零点（zero point）参数
        量化公式: real_value = (quantized_value - zero_point) * scale
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

    【功能】
        描述多维张量的形状（dimensions）

    【字段说明】
        dimensionSize: 各维度大小的数组（最多8维）
        numDimensions: 实际维度数量
    """
    _fields_ = [
        ("dimensionSize",ctypes.c_int * 8),
        ("numDimensions",ctypes.c_int)
    ]

class hbDNNTensorProperties_t(ctypes.Structure):
    """
    hbDNNTensorProperties_t - 张量属性结构体

    【功能】
        描述BPU Tensor的所有属性信息，包括形状、布局、量化参数等

    【字段说明】
        validShape: 有效形状（实际数据维度）
        alignedShape: 对齐后的形状（内存对齐）
        tensorLayout: 张量布局（NCHW或NHWC）
        tensorType: 张量数据类型
        shift/scale: 量化参数
        quantiType: 量化类型（0=无量化，2=非对称量化）
        alignedByteSize: 对齐后的字节大小
        stride: 各维度步长
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

    【功能】
        完整的BPU张量描述，包含内存信息和属性信息
    """
    _fields_ = [
        ("sysMem",hbSysMem_t * 4),
        ("properties",hbDNNTensorProperties_t)
    ]


class ClassificationPostProcessInfo_t(ctypes.Structure):
    """
    ClassificationPostProcessInfo_t - 分类后处理参数结构体

    【功能】
        定义分类后处理所需的各种参数，如输入尺寸、阈值等

    【字段说明】
        height/width: 模型输入的高和宽
        ori_height/ori_width: 原始图像的高和宽
        score_threshold: 分类置信度阈值，低于此值的结果被过滤
        nms_threshold: 非极大值抑制阈值（分类任务通常为0）
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
    将字符串格式的Layout转换为BPU内部使用的整数值

    【参数】
        Layout: 张量布局字符串，如"NCHW"或"NHWC"

    【返回值】
        2: NCHW格式（通道在前）
        0: NHWC格式（通道在后）

    【备注】
        NCHW: [Batch, Channel, Height, Width]
        NHWC: [Batch, Height, Width, Channel]
        BPU推理通常使用NCHW格式以提高计算效率
    """
    if Layout == "NCHW":
        return int(2)
    else:
        return int(0)

def bgr2nv12_opencv(image):
    """
    将BGR格式图像转换为NV12格式

    【参数】
        image: OpenCV读取的BGR格式图像（numpy数组）

    【返回值】
        nv12_data: NV12格式的图像数据（numpy数组）

    【NV12格式说明】
        NV12是一种YUV420格式，由一个Y平面和一个UV交错平面组成：
        - Y平面：亮度分量，大小为 H x W
        - UV平面：色度分量（U和V交错），大小为 H/2 x W
        - 总大小：H x W + H/2 x W = H x W x 1.5

    【处理流程】
        1. 将BGR转换为YUV_I420（Planar格式）
        2. 分离Y、U、V分量
        3. 将U和V交错排列形成UV平面
        4. 合并Y和UV为NV12格式
    """
    height, width = image.shape[0], image.shape[1]
    area = height * width
    # BGR -> YUV_I420 (planar格式)
    yuv420p = cv2.cvtColor(image, cv2.COLOR_BGR2YUV_I420).reshape((area * 3 // 2,))
    # 提取Y分量（亮度）
    y = yuv420p[:area]
    # 提取UV分量并重新排列为交错格式
    uv_planar = yuv420p[area:].reshape((2, area // 4))
    uv_packed = uv_planar.transpose((1, 0)).reshape((area // 2,))

    nv12 = np.zeros_like(yuv420p)
    nv12[:height * width] = y
    nv12[height * width:] = uv_packed
    return nv12

def print_properties(pro):
    """
    打印Tensor属性信息

    【参数】
        pro: Tensor属性对象（来自pyeasy_dnn）

    【打印内容】
        tensor_type: 张量类型
        dtype: 数据类型
        layout: 布局格式
        shape: 形状
    """
    print("tensor type:", pro.tensor_type)
    print("data type:", pro.dtype)
    print("layout:", pro.layout)
    print("shape:", pro.shape)


# 对宽度进行16字节对齐
def align_16(value):
    """
    将数值向上对齐到16的倍数

    【参数】
        value: 输入数值

    【返回值】
        对齐后的数值（16字节边界对齐）

    【用途】
        BPU硬件要求输入图像宽度是16的倍数
    """
    return (value + 15) // 16 * 16

# 分配对齐后的内存，并填充图像数据
def bgr_to_nv12_custom_with_padding(bgr_image, aligned_width, aligned_height):
    """
    将BGR图像转换为NV12格式并进行内存对齐填充

    【参数】
        bgr_image: 输入BGR图像
        aligned_width: 对齐后的宽度
        aligned_height: 对齐后的高度

    【返回值】
        y_plane: 对齐后的Y分量
        uv_plane: 对齐后的UV分量
    """
    height, width = bgr_image.shape[:2]

    # 分离 YUV 分量
    yuv_image = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2YUV_I420)

    # 创建对齐后的 Y 平面和 UV 平面
    y_plane = np.zeros((aligned_height, aligned_width), dtype=np.uint8)
    uv_plane = np.zeros((aligned_height // 2, aligned_width), dtype=np.uint8)

    # 提取 Y、U、V 分量
    y_orig = yuv_image[:height, :]
    u_orig = yuv_image[height:height + height // 4].reshape(height // 2, width // 2)
    v_orig = yuv_image[height + height // 4:].reshape(height // 2, width // 2)

    # 填充 Y 分量到对齐后的 Y 平面
    for i in range(height):
        y_plane[i, :width] = y_orig[i, :]

    # 填充 UV 分量到对齐后的 UV 平面 (交错 U 和 V)
    for i in range(height // 2):
        uv_plane[i, 0:width:2] = u_orig[i, :]  # 奇数列填充 U
        uv_plane[i, 1:width:2] = v_orig[i, :]  # 偶数列填充 V

    # 返回对齐后的 Y 和 UV 数据
    return y_plane, uv_plane

# 将 Y 和 UV 数据合并为 NV12 格式
def combine_yuv_to_nv12(y_data, uv_data):
    """
    将分离的Y数据和UV数据合并为NV12格式

    【参数】
        y_data: Y分量数据
        uv_data: UV分量数据

    【返回值】
        合并后的NV12格式数据
    """
    return np.concatenate((y_data.flatten(), uv_data.flatten()))

def get_hw(pro):
    """
    从Tensor属性中获取高度和宽度

    【参数】
        pro: Tensor属性对象

    【返回值】
        (height, width): 高和宽的元组

    【说明】
        不同布局格式，shape含义不同：
        - NCHW: shape = [batch, channel, height, width]
        - NHWC: shape = [batch, height, width, channel]
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
    # 第1步：加载EfficientNASNet模型
    # ==========================================================================
    # dnn.load() 用于加载DNN模型文件（.bin格式）
    # 返回模型列表，本例中只有一个模型
    # 模型文件位于上级目录的models文件夹中
    models = dnn.load('../models/efficientnasnet_m_300x300_nv12.bin')

    # ==========================================================================
    # 第2步：打印模型输入输出属性（用于调试）
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
    # 使用OpenCV读取斑马图片（测试ImageNet 1000类分类）
    img_file = cv2.imread('./zebra_cls.jpg')

    # 获取模型输入的高和宽
    h, w = get_hw(models[0].inputs[0].properties)
    des_dim = (w, h)

    # 将图像resize到模型输入尺寸（300x300）
    resized_data = cv2.resize(img_file, des_dim, interpolation=cv2.INTER_AREA)

    # 将BGR图像转换为NV12格式
    nv12_data = bgr2nv12_opencv(resized_data)

    # ==========================================================================
    # 第4步：执行模型推理（前向传播）
    # ==========================================================================
    # models[0].forward() 接收预处理后的输入数据
    # 返回模型输出（分类logits）
    outputs = models[0].forward(nv12_data)

    # ==========================================================================
    # 第5步：准备后处理参数
    # ==========================================================================
    t0 = time.time()

    # 创建后处理参数结构体
    classification_postprocess_info = ClassificationPostProcessInfo_t()

    # 设置模型输入尺寸
    classification_postprocess_info.height = h
    classification_postprocess_info.width = w

    # 设置原始图像尺寸
    org_height, org_width = img_file.shape[0:2]
    classification_postprocess_info.ori_height = org_height
    classification_postprocess_info.ori_width = org_width

    # 设置后处理阈值参数
    classification_postprocess_info.score_threshold = 0.3  # 置信度阈值30%
    classification_postprocess_info.nms_threshold = 0    # NMS阈值（分类任务为0）
    classification_postprocess_info.nms_top_k = 1        # 返回Top-1结果
    classification_postprocess_info.is_pad_resize = 0     # 不使用填充resize

    # ==========================================================================
    # 第6步：填充输出Tensor信息
    # ==========================================================================
    # 为每个输出创建hbDNNTensor_t结构体
    output_tensors = (hbDNNTensor_t * len(models[0].outputs))()

    for i in range(len(models[0].outputs)):
        # 设置张量布局
        output_tensors[i].properties.tensorLayout = get_TensorLayout(outputs[i].properties.layout)

        # 根据量化类型设置相应的参数
        if (len(outputs[i].properties.scale_data) == 0):
            # 无量化：使用float类型
            output_tensors[i].properties.quantiType = 0
            # 将numpy数组的内存地址转换为void*指针
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ctypes.c_void_p)
        else:
            # 非对称量化：使用int32类型和scale参数
            output_tensors[i].properties.quantiType = 2
            output_tensors[i].properties.scale.scaleData = outputs[i].properties.scale_data.ctypes.data_as(
                ctypes.POINTER(ctypes.c_float))
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                ctypes.c_void_p)

        # 填充张量形状信息
        for j in range(len(outputs[i].properties.shape)):
            output_tensors[i].properties.validShape.numDimensions = len(outputs[i].properties.shape)
            output_tensors[i].properties.validShape.dimensionSize[j] = outputs[i].properties.shape[j]

        # 调用C库进行分类后处理
        libpostprocess.ClassificationDoProcess(
            output_tensors[i],
            ctypes.pointer(classification_postprocess_info),
            i)

    # ==========================================================================
    # 第7步：获取并解析后处理结果
    # ==========================================================================
    result_str = get_Postprocess_result(ctypes.pointer(classification_postprocess_info))
    result_str = result_str.decode('utf-8')
    t1 = time.time()
    print("postprocess time is :", (t1 - t0))

    # ==========================================================================
    # 第8步：解析并打印分类结果
    # ==========================================================================
    # 后处理结果为JSON字符串格式
    # 解析JSON获取分类结果列表
    data = json.loads(result_str[25:])  # 跳过前缀字符

    # 遍历每一个分类结果
    for result in data:
        prob = result['prob']      # 置信度得分
        label = result['label']     # 类别ID
        name = result['class_name'] # 类别名称（如"zebra"）

        # 打印分类结果
        print(f"cls id: {label}, Confidence: {prob}, class_name: {name}")

# ================================================================================
# 【运行结果示例】
# ================================================================================
# cls id: 340, Confidence: 0.91234, class_name: zebra
#
# 表示：模型识别出图像中有97.58%的概率是斑马（类别ID 340）
#
# 【程序总结】
# ================================================================================
# 1. 本程序展示了完整的AI推理流程：
#    加载模型 -> 读取图像 -> 预处理 -> 推理 -> 后处理 -> 结果解析
#
# 2. 关键技术点：
#    - 使用pyeasy_dnn API简化BPU推理
#    - BGR到NV12格式转换
#    - 16字节边界对齐
#    - 量化模型推理支持
#    - C库后处理加速
#
# 3. EfficientNASNet特点：
#    - 高效的神经网络架构搜索（NAS）结果
#    - 适合在边缘设备上运行
#    - 300x300输入尺寸适合中等复杂度任务
