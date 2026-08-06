#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ***************************************************************************************************
# 逐行详细注释版 - 专门为零基础学习者编写
# ***************************************************************************************************
#
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │                    《MobileNetV1图像分类》                                    │
# │                                                                             │
# │  功能说明:                                                                   │
# │  这是一个完整的图像分类程序                                                    │
# │  加载MobileNetV1模型，对输入图像进行分类                                      │
# │  输出最可能的类别和置信度                                                       │
# │                                                                             │
# │  什么是图像分类？                                                            │
# │  图像分类是让计算机识别图像中物体类别的任务                                     │
# │  输入一张图片，输出类别标签（如"猫"、"狗"、"汽车"）                             │
# │                                                                             │
# │  MobileNetV1模型简介:                                                       │
# │  - 专为移动端/嵌入式设备设计                                                  │
# │  - 轻量级模型，计算量小                                                       │
# │  - ImageNet 1000类分类器                                                     │
# │  - 输入尺寸: 224x224像素                                                     │
# │                                                                             │
# │  学习目标:                                                                   │
# │  1. 理解图像分类的基本流程                                                    │
# │  2. 学会加载和使用AI模型                                                     │
# │  3. 理解图像预处理（缩放、格式转换）                                          │
# │  4. 理解模型输出的后处理                                                     │
# └─────────────────────────────────────────────────────────────────────────────┘

# ***************************************************************************************************
# 第一部分：导入必要的库
# ***************************************************************************************************

# 标准库
import os           # 文件路径操作
import sys          # 系统相关
import time         # 时间计时
import json         # JSON数据解析
import ctypes       # C语言类型接口（调用后处理库）
from typing import List, Tuple, Any  # 类型提示

# 第三方库
import numpy as np           # 数值计算/矩阵运算
import cv2                   # OpenCV计算机视觉库

# 地平线BPU推理库
# 这是最核心的库，用于加载模型并在BPU加速器上运行
try:
    from hobot_dnn import pyeasy_dnn as dnn  # RDK X3版本
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn  # RDK X5版本

# ***************************************************************************************************
# 第二部分：C语言结构体定义
# ***************************************************************************************************

"""
为什么需要定义C语言结构体？

这个程序调用了地平线提供的后处理C库（libpostprocess.so）
Python和C是两种语言，数据结构不兼容
ctypes模块允许我们在Python中定义C语言的结构体

这就像制作一个"翻译器"：
Python数据类型 ──转换──> C数据类型 ──> C函数处理
"""

# 内存区域结构体
class hbSysMem_t(ctypes.Structure):
    """
    hbSysMem_t - 内存区域结构体

    属性说明：
    - phyAddr: 物理地址（硬件直接访问）
    - virAddr: 虚拟地址（程序使用的内存地址）
    - memSize: 内存大小（字节）
    """
    _fields_ = [
        ("phyAddr", ctypes.c_double),
        ("virAddr", ctypes.c_void_p),
        ("memSize", ctypes.c_int)
    ]

# 量化偏移结构体
class hbDNNQuantiShift_yt(ctypes.Structure):
    """
    hbDNNQuantiShift_yt - 量化偏移结构体

    用于AI模型的量化处理
    量化可以减小模型大小、加速推理
    """
    _fields_ = [
        ("shiftLen", ctypes.c_int),
        ("shiftData", ctypes.c_char_p)
    ]

# 量化比例结构体
class hbDNNQuantiScale_t(ctypes.Structure):
    """
    hbDNNQuantiScale_t - 量化比例结构体
    """
    _fields_ = [
        ("scaleLen", ctypes.c_int),
        ("scaleData", ctypes.POINTER(ctypes.c_float)),
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
        ("numDimensions", ctypes.c_int)
    ]

# 张量属性结构体
class hbDNNTensorProperties_t(ctypes.Structure):
    """
    hbDNNTensorProperties_t - 张量属性结构体
    """
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

# DNN张量结构体
class hbDNNTensor_t(ctypes.Structure):
    """
    hbDNNTensor_t - DNN张量完整结构体

    用于在Python和C之间传递AI模型的输入输出数据
    """
    _fields_ = [
        ("sysMem", hbSysMem_t * 4),
        ("properties", hbDNNTensorProperties_t)
    ]

# 分类后处理信息结构体
class ClassificationPostProcessInfo_t(ctypes.Structure):
    """
    ClassificationPostProcessInfo_t - 分类后处理参数结构体

    包含分类后处理需要的所有参数
    """
    _fields_ = [
        ("height", ctypes.c_int),                 # 模型输入高度
        ("width", ctypes.c_int),                  # 模型输入宽度
        ("ori_height", ctypes.c_int),             # 原始图像高度
        ("ori_width", ctypes.c_int),              # 原始图像宽度
        ("score_threshold", ctypes.c_float),      # 置信度阈值
        ("nms_threshold", ctypes.c_float),        # NMS阈值（分类不用）
        ("nms_top_k", ctypes.c_int),              # Top-K
        ("is_pad_resize", ctypes.c_int)            # 是否带填充缩放
    ]

# ***************************************************************************************************
# 第三部分：加载后处理库
# ***************************************************************************************************

def load_postprocess_library():
    """
    load_postprocess_library - 加载后处理C共享库

    后处理库路径: /usr/lib/libpostprocess.so

    作用：
    AI模型的输出是一堆原始数字（张量）
    需要经过复杂的计算才能变成我们能理解的分类结果
    这些计算在C库中实现，效率更高
    """
    try:
        lib = ctypes.CDLL('/usr/lib/libpostprocess.so')
        print("✓ 后处理库加载成功")
        return lib
    except Exception as e:
        print(f"✗ 加载后处理库失败: {e}")
        print("请确保已正确安装 libpostprocess.so")
        return None

# 加载后处理库
libpostprocess = load_postprocess_library()

# 配置分类后处理函数
if libpostprocess:
    libpostprocess.ClassificationPostProcess.argtypes = [
        ctypes.POINTER(ClassificationPostProcessInfo_t)
    ]
    libpostprocess.ClassificationPostProcess.restype = ctypes.c_char_p

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

    NCHW = [N, C, H, W] = [批次, 通道, 高, 宽]
    NHWC = [N, H, W, C] = [批次, 高, 宽, 通道]
    """
    if layout_str == "NCHW":
        return int(2)
    else:
        return int(0)

def get_hw(properties) -> Tuple[int, int]:
    """
    get_hw - 从张量属性中获取高度和宽度
    """
    if properties.layout == "NCHW":
        return properties.shape[2], properties.shape[3]
    else:
        return properties.shape[1], properties.shape[2]

def print_tensor_properties(pro, name: str = ""):
    """
    print_tensor_properties - 打印张量属性

    帮助理解模型输入输出的格式
    """
    print(f"\n{'='*50}")
    print(f"{name} 属性:")
    print(f"{'='*50}")
    print(f"  数据类型: {pro.dtype}")
    print(f"  布局: {pro.layout}")
    print(f"  形状: {pro.shape}")
    print(f"{'='*50}\n")

def bgr2nv12_opencv(image: np.ndarray) -> np.ndarray:
    """
    bgr2nv12_opencv - 将BGR图像转换为NV12格式

    参数:
        image: OpenCV读取的BGR图像

    返回:
        NV12格式的图像数据

    为什么需要NV12？
    - 摄像头输出通常是YUV格式，不是RGB
    - BPU加速器需要NV12格式的输入
    - NV12 = Y平面(完整) + UV交错(半分辨率)
    """
    height, width = image.shape[0], image.shape[1]
    area = height * width

    # BGR转YUV420
    # cv2.COLOR_BGR2YUV_I420 是OpenCV的颜色空间转换
    yuv420p = cv2.cvtColor(image, cv2.COLOR_BGR2YUV_I420).reshape((area * 3 // 2,))

    # Y分量（完整分辨率）
    y = yuv420p[:area]

    # UV分量（半分辨率，交错存储）
    uv_planar = yuv420p[area:].reshape((2, area // 4))
    uv_packed = uv_planar.transpose((1, 0)).reshape((area // 2,))

    # 组合NV12
    nv12 = np.zeros_like(yuv420p)
    nv12[:height * width] = y
    nv12[height * width:] = uv_packed
    return nv12

# ***************************************************************************************************
# 第五部分：模型加载和推理
# ***************************************************************************************************

def load_model(model_path: str):
    """
    load_model - 加载AI模型

    参数:
        model_path: 模型文件路径（.bin格式）

    返回:
        加载的模型对象
    """
    print(f"\n正在加载模型: {model_path}")

    # 检查文件是否存在
    if not os.path.exists(model_path):
        print(f"错误：模型文件不存在: {model_path}")
        sys.exit(1)

    # dnn.load() 是加载模型的函数
    # 它会：
    # 1. 读取模型文件
    # 2. 解析模型结构
    # 3. 分配BPU内存
    # 4. 返回模型对象
    models = dnn.load(model_path)

    print(f"✓ 模型加载成功!")
    print(f"  输入数量: {len(models[0].inputs)}")
    print(f"  输出数量: {len(models[0].outputs)}")

    return models

def preprocess_image(image_path: str, target_size: Tuple[int, int]):
    """
    preprocess_image - 图像预处理

    参数:
        image_path: 图像文件路径
        target_size: 目标尺寸 (宽, 高)

    返回:
        预处理后的NV12格式数据
    """
    print(f"\n预处理图像: {image_path}")

    # 读取图像
    # cv2.imread() 读取图像并转换为numpy数组
    img = cv2.imread(image_path)

    if img is None:
        print(f"错误：无法读取图像: {image_path}")
        sys.exit(1)

    print(f"  原始尺寸: {img.shape[1]} x {img.shape[0]} (宽 x 高)")

    # 缩放到模型输入尺寸
    # cv2.resize() 参数：
    # - 图像
    # - 目标尺寸 (宽, 高)
    # - 插值方法: INTER_AREA适合缩小, INTER_LINEAR适合放大
    resized = cv2.resize(img, target_size, interpolation=cv2.INTER_AREA)
    print(f"  缩放后尺寸: {resized.shape[1]} x {resized.shape[0]}")

    # 转换为NV12格式
    nv12_data = bgr2nv12_opencv(resized)
    print(f"  NV12格式大小: {nv12_data.nbytes} 字节")

    return nv12_data, img

def run_inference(model, input_data):
    """
    run_inference - 执行模型推理

    参数:
        model: 加载的模型对象
        input_data: 预处理后的输入数据

    返回:
        模型输出
    """
    print("\n执行BPU推理...")

    # 记录开始时间
    t0 = time.time()

    # model.forward() 是执行推理的函数
    # 输入: NV12格式的图像数据
    # 输出: 模型输出（张量列表）
    outputs = model.forward(input_data)

    # 记录结束时间
    t1 = time.time()
    print(f"✓ 推理完成，耗时: {(t1-t0)*1000:.2f} ms")

    return outputs

# ***************************************************************************************************
# 第六部分：后处理
# ***************************************************************************************************

def postprocess_classification(outputs, input_h, input_w, orig_h, orig_w, score_thresh=0.3):
    """
    postprocess_classification - 分类后处理

    参数:
        outputs: 模型输出
        input_h, input_w: 模型输入尺寸
        orig_h, orig_w: 原始图像尺寸
        score_thresh: 置信度阈值

    返回:
        分类结果列表
    """
    print("\n执行后处理...")

    # 创建后处理参数
    postprocess_info = ClassificationPostProcessInfo_t()
    postprocess_info.height = input_h
    postprocess_info.width = input_w
    postprocess_info.ori_height = orig_h
    postprocess_info.ori_width = orig_w
    postprocess_info.score_threshold = score_thresh
    postprocess_info.nms_threshold = 0  # 分类不需要NMS
    postprocess_info.nms_top_k = 500    # 输出前500个结果
    postprocess_info.is_pad_resize = 0

    # 准备输出张量
    output_tensors = (hbDNNTensor_t * len(outputs))()

    for i in range(len(outputs)):
        # 设置张量布局
        output_tensors[i].properties.tensorLayout = get_TensorLayout(outputs[i].properties.layout)

        # 根据量化类型设置
        if len(outputs[i].properties.scale_data) == 0:
            # 无量化，使用浮点数
            output_tensors[i].properties.quantiType = 0
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ctypes.c_void_p)
        else:
            # 量化类型，使用整数
            output_tensors[i].properties.quantiType = 2
            output_tensors[i].properties.scale.scaleData = outputs[i].properties.scale_data.ctypes.data_as(
                ctypes.POINTER(ctypes.c_float))
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                ctypes.c_void_p)

        # 设置形状
        for j in range(len(outputs[i].properties.shape)):
            output_tensors[i].properties.validShape.numDimensions = len(outputs[i].properties.shape)
            output_tensors[i].properties.validShape.dimensionSize[j] = outputs[i].properties.shape[j]

        # 调用后处理
        libpostprocess.ClassificationDoProcess(output_tensors[i],
                                              ctypes.pointer(postprocess_info),
                                              i)

    # 获取结果
    result_str = libpostprocess.ClassificationPostProcess(
        ctypes.pointer(postprocess_info))
    result_str = result_str.decode('utf-8')

    # 解析JSON结果
    # 格式通常是 "Classification results:\n{...}"
    if "{" in result_str:
        json_str = result_str[result_str.index("{"):]
        results = json.loads(json_str)
        return results

    return []

# ***************************************************************************************************
# 第七部分：ImageNet 1000类标签
# ***************************************************************************************************

# ImageNet 1000分类标签（部分）
# 完整列表包含1000个类别，这里是常用的一部分
IMAGENET_LABELS = {
    0: "tench", 1: "goldfish", 2: "great white shark", 3: "tiger shark",
    4: "hammerhead shark", 5: "electric ray", 10: "cock", 11: "hen",
    50: "bee", 100: "ostrich", 200: "sandwich", 207: "golden retriever",
    210: "collie", 232: "meerkat", 281: "tabby cat", 282: "tiger cat",
    285: "Egyptian cat", 340: "zebra", 388: "giant panda", 400: "airliner",
    500: "coffee mug", 700: "wig", 800: "parachute", 900: "snowplow",
    999: "toilet seat"
}

def get_class_name(class_id: int) -> str:
    """
    get_class_name - 获取类别名称
    """
    return IMAGENET_LABELS.get(class_id, f"class_{class_id}")

# ***************************************************************************************************
# 第八部分：主函数
# ***************************************************************************************************

def main():
    """
    main - 主函数

    完整流程：
    1. 加载模型
    2. 读取并预处理图像
    3. 执行推理
    4. 后处理
    5. 显示结果
    """

    print("=" * 60)
    print("MobileNetV1 图像分类")
    print("=" * 60)

    # ==================== 配置 ====================
    # 模型文件路径
    # 注意：必须是nv12格式的MobileNetV1模型
    model_path = "/app/model/basic/mobilenetv1_224x224_nv12.bin"

    # 测试图像
    test_image = "./zebra_cls.jpg"

    # 分类阈值
    score_threshold = 0.3

    # ==================== 加载模型 ====================
    models = load_model(model_path)

    # 打印模型信息
    print_tensor_properties(models[0].inputs[0].properties, "模型输入")
    print_tensor_properties(models[0].outputs[0].properties, "模型输出")

    # 获取模型输入尺寸
    input_h, input_w = get_hw(models[0].inputs[0].properties)
    print(f"模型输入尺寸: {input_w} x {input_h}")

    # ==================== 预处理图像 ====================
    nv12_data, orig_img = preprocess_image(test_image, (input_w, input_h))

    orig_h, orig_w = orig_img.shape[:2]

    # ==================== 执行推理 ====================
    outputs = run_inference(models[0], nv12_data)

    # ==================== 后处理 ====================
    if libpostprocess:
        results = postprocess_classification(outputs, input_h, input_w, orig_h, orig_w, score_threshold)

        # ==================== 显示结果 ====================
        print("\n" + "=" * 60)
        print("分类结果 (Top 10):")
        print("=" * 60)

        for i, result in enumerate(results[:10]):
            class_id = result['label']
            prob = result['prob']
            class_name = get_class_name(class_id)

            print(f"  {i+1:2d}. {class_name:20s} (ID: {class_id:4d}) - 置信度: {prob:.4f}")

        print("=" * 60)

    else:
        print("\n警告：后处理库未加载，无法显示分类结果")
        print("模型输出形状:", outputs[0].properties.shape)
        print("模型输出数据(前10个):", outputs[0].buffer[:10])

# ***************************************************************************************************
# 第九部分：程序入口
# ***************************************************************************************************

if __name__ == '__main__':
    main()

# ***************************************************************************************************
# 知识详解
# ***************************************************************************************************
#
# 1. 图像分类 vs 目标检测 vs 语义分割
#
#    ┌─────────────────────────────────────────────────────────────────┐
#    │                                                                 │
#    │  图像分类 (Classification)                                     │
#    │  输入: 一张图像                                                 │
#    │  输出: 类别标签（如"猫"）                                       │
#    │  示例: MobileNetV1, ResNet, EfficientNet                      │
#    │                                                                 │
#    │  目标检测 (Object Detection)                                    │
#    │  输入: 一张图像                                                 │
#    │  输出: 多个目标的位置+类别                                       │
#    │  示例: YOLOv5, SSD, Faster R-CNN                               │
#    │                                                                 │
#    │  语义分割 (Semantic Segmentation)                               │
#    │  输入: 一张图像                                                 │
#    │  输出: 每个像素的类别                                            │
#    │  示例: UNet, DeepLab, FCN                                     │
#    │                                                                 │
#    └─────────────────────────────────────────────────────────────────┘
#
# 2. 预处理的重要性
#
#    AI模型对输入有严格要求：
#    - 固定的输入尺寸（如224x224）
#    - 固定的数据格式（如NV12）
#    - 固定的数据范围（如0-1或0-255）
#
#    预处理步骤：
#    ┌─────────────────────────────────────────────────────────────────┐
#    │                                                                 │
#    │  原始图像          缩放               格式转换              │
#    │  ┌────┐          ┌────┐            ┌────┐                  │
#    │  │    │   ────▶ │    │   ────▶   │    │                  │
#    │  │    │          └────┘            └────┘                  │
#    │  │    │   任意尺寸        224x224        NV12               │
#    │  └────┘                                                  │
#    │                                                                 │
#    └─────────────────────────────────────────────────────────────────┘
#
# 3. 模型量化
#
#    量化是将浮点数转换为低精度整数的技术
#    ┌─────────────────────────────────────────────────────────────────┐
#    │                                                                 │
#    │  全精度 (FP32):  4字节/参数    精度高    占用大                  │
#    │  量化 (INT8):    1字节/参数    精度略低  占用小，推理快          │
#    │                                                                 │
#    │  量化公式:                                                       │
#    │  quantized = round(float / scale + zero_point)                  │
#    │                                                                 │
#    └─────────────────────────────────────────────────────────────────┘
#
# ***************************************************************************************************
# 课后练习
# ***************************************************************************************************
#
# 练习1：使用自己的图片测试
#   修改 test_image = "./your_image.jpg"
#
# 练习2：调整分类阈值
#   修改 score_threshold = 0.3
#   降低阈值会显示更多类别，提高阈值只显示高置信度
#
# 练习3：显示更多结果
#   修改 Top 10 为 Top 20 或更多
#
# ***************************************************************************************************
# 常见问题
# ***************************************************************************************************
#
# Q: 模型加载失败？
#   - 检查模型路径是否正确
#   - 确认模型文件存在且有读取权限
#
# Q: 图像读取失败？
#   - 确认图像文件存在
#   - 确认OpenCV支持该图像格式
#
# Q: 后处理库加载失败？
#   - 确认 libpostprocess.so 存在于 /usr/lib/
#   - 可能需要设置 LD_LIBRARY_PATH
#
# ***************************************************************************************************

print("=" * 60)
print("恭喜完成MobileNetV1图像分类学习！")
print("=" * 60)
