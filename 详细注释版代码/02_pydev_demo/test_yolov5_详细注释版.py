#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_yolov5.py - YOLOv5s目标检测推理示例（图片输入）
================================================================================

【程序功能】
本程序使用YOLOv5s模型对静态图片进行目标检测推理。
YOLOv5s是YOLOv5系列中的轻量版本，适合在边缘设备上实时运行。

【模型信息】
- 模型名称：YOLOv5s
- 输入尺寸：672x672像素
- 输入格式：NV12
- 支持：80类COCO目标检测

【YOLOv5s特点】
1. 轻量级：7.2M参数量，适合嵌入式部署
2. 高效率：推理速度快，适合实时应用
3. 精度平衡：在速度和精度之间取得良好平衡
4. 成熟生态：Ultralytics维护，更新活跃

【YOLOv5s vs 其他YOLOv5变体】
| 模型      | 参数量  | mAP@0.5 | 推理速度 |
|-----------|---------|---------|---------|
| YOLOv5s  | 7.2M    | 56.0%   | 非常快   |
| YOLOv5m  | 21.2M   | 63.1%   | 快       |
| YOLOv5l  | 46.5M   | 67.1%   | 中等     |
| YOLOv5x  | 86.7M   | 68.7%   | 较慢     |

【运行方式】
cd pydev_demo/07_yolov5_sample/
python3 test_yolov5.py

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
# C结构体定义 - 与BPU驱动和YOLOv5后处理库交互
# ================================================================================

class hbSysMem_t(ctypes.Structure):
    """
    hbSysMem_t - BPU系统内存结构体
    """
    _fields_ = [
        ("phyAddr", ctypes.c_double),
        ("virAddr", ctypes.c_void_p),
        ("memSize", ctypes.c_int)
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


class Yolov5PostProcessInfo_t(ctypes.Structure):
    """
    Yolov5PostProcessInfo_t - YOLOv5后处理参数结构体

    【参数说明】
        height/width: 模型输入尺寸
        ori_height/ori_width: 原始图像尺寸
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
# 加载YOLOv5后处理库
# ================================================================================

libpostprocess = ctypes.CDLL('/usr/lib/libpostprocess.so')

get_Postprocess_result = libpostprocess.Yolov5PostProcess
get_Postprocess_result.argtypes = [ctypes.POINTER(Yolov5PostProcessInfo_t)]
get_Postprocess_result.restype = ctypes.c_char_p


# ================================================================================
# 辅助函数
# ================================================================================

def get_TensorLayout(Layout):
    """
    Layout字符串转换为BPU内部整数值
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
    # 第1步：加载YOLOv5s模型
    # ==========================================================================
    models = dnn.load('../models/yolov5s_672x672_nv12.bin')

    # 打印输入tensor属性
    print_properties(models[0].inputs[0].properties)

    # 打印输出tensor属性
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

    # ==========================================================================
    # 第4步：准备后处理参数
    # ==========================================================================
    yolov5_postprocess_info = Yolov5PostProcessInfo_t()
    yolov5_postprocess_info.height = h
    yolov5_postprocess_info.width = w
    org_height, org_width = img_file.shape[0:2]
    yolov5_postprocess_info.ori_height = org_height
    yolov5_postprocess_info.ori_width = org_width
    yolov5_postprocess_info.score_threshold = 0.4  # 置信度阈值40%
    yolov5_postprocess_info.nms_threshold = 0.45   # NMS阈值45%
    yolov5_postprocess_info.nms_top_k = 20         # 最多20个检测框
    yolov5_postprocess_info.is_pad_resize = 0      # 不使用填充resize

    # ==========================================================================
    # 第5步：填充Tensor并调用后处理
    # ==========================================================================
    output_tensors = (hbDNNTensor_t * len(models[0].outputs))()
    for i in range(len(models[0].outputs)):
        output_tensors[i].properties.tensorLayout = get_TensorLayout(outputs[i].properties.layout)

        if len(outputs[i].properties.scale_data) == 0:
            # FLOAT32模型
            output_tensors[i].properties.quantiType = 0
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ctypes.c_void_p)
        else:
            # INT8量化模型
            output_tensors[i].properties.quantiType = 2
            output_tensors[i].properties.scale.scaleData = outputs[i].properties.scale_data.ctypes.data_as(
                ctypes.POINTER(ctypes.c_float))
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                ctypes.c_void_p)

        for j in range(len(outputs[i].properties.shape)):
            output_tensors[i].properties.validShape.dimensionSize[j] = outputs[i].properties.shape[j]

        # 调用YOLOv5后处理
        libpostprocess.Yolov5doProcess(
            output_tensors[i],
            ctypes.pointer(yolov5_postprocess_info),
            i
        )

    # ==========================================================================
    # 第6步：获取并解析检测结果
    # ==========================================================================
    result_str = get_Postprocess_result(ctypes.pointer(yolov5_postprocess_info))
    result_str = result_str.decode('utf-8')
    t2 = time.time()

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
        cv2.rectangle(
            img_file,
            (int(bbox[0]), int(bbox[1])),
            (int(bbox[2]), int(bbox[3])),
            (0, 255, 0),
            2
        )

        # 在边界框上方显示类别名称和置信度
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(
            img_file,
            f'{name} {score:.2f}',
            (int(bbox[0]), int(bbox[1]) - 10),
            font,
            0.5,
            (0, 255, 0),
            1
        )

    # 保存结果图像
    cv2.imwrite('output_image.jpg', img_file)

    t1 = time.time()
    print("draw result time is :", (t1 - t0))

# ================================================================================
# 【YOLOv5s 推理流程总结】
# ================================================================================
# 1. 模型加载: dnn.load() 加载.bin模型文件
# 2. 图像预处理: BGR -> Resize -> NV12
# 3. 模型推理: models[0].forward(nv12_data)
# 4. 后处理: Yolov5doProcess 执行NMS等
# 5. 结果解析: JSON -> 边界框/类别/置信度
# 6. 可视化: OpenCV绘制边界框和标签
#
# 【性能指标】
# - 推理时间: ~10-20ms (BPU上)
# - 后处理时间: ~5-10ms
# - 总处理时间: ~15-30ms
# - 理论最大FPS: ~30-60 FPS
