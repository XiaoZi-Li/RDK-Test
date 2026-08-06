#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mipi_camera_web.py - MIPI摄像头Web实时目标检测示例
================================================================================

【程序功能】
本程序使用MIPI接口摄像头捕获视频，通过WebSocket协议将实时视频流和目标检测结果
传输到Web浏览器端展示。实现了完整的Web视频服务器功能。

【技术特点】
1. MIPI摄像头捕获：高带宽、低延迟的图像采集
2. WebSocket通信：支持浏览器实时接收视频流
3. Protobuf序列化：高效的检测结果数据传输
4. JPEG编码：浏览器可显示的视频流格式
5. 异步IO：使用asyncio实现高性能并发

【系统架构】
┌────────────────┐      ┌────────────────┐      ┌────────────────┐
│  MIPI Camera   │─────▶│  BPU Inference │─────▶│  WebSocket     │
│  (1080p@30fps) │      │  (FCOS)       │      │  (浏览器显示)   │
└────────────────┘      └────────────────┘      └────────────────┘
                              │
                              ▼
                       ┌────────────────┐
                       │  Protobuf封包  │
                       │  (检测结果+图像)│
                       └────────────────┘

【依赖服务】
1. Nginx Web服务器（用于静态文件服务）
2. WebSocket服务器（端口8080）
3. MIPI摄像头驱动
4. BPU推理引擎

【运行方式】
# 1. 启动Nginx
cd pydev_demo/05_web_display_camera_sample/
./start_nginx.sh

# 2. 运行本程序
python3 mipi_camera_web.py

# 3. 在浏览器中打开
http://localhost:8080/

【协议说明】
- 视频传输：JPEG格式通过WebSocket发送
- 检测结果：Protobuf格式，包含边界框、类别、置信度
- 图像分辨率：1920x1080
- 检测模型：FCOS 512x512

================================================================================
"""

import sys
import os
import signal
import numpy as np
import cv2
import google.protobuf
import asyncio
import websockets
import x3_pb2
import time
import subprocess

try:
    from hobot_vio import libsrcampy as srcampy
except ImportError:
    from hobot_vio_rdkx5 import libsrcampy as srcampy
try:
    from hobot_dnn import pyeasy_dnn as pyeasy_dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as pyeasy_dnn

# ================================================================================
# 全局配置
# ================================================================================

fps = 30  # 帧率配置

# ================================================================================
# C结构体定义 - 与BPU驱动和FCOS后处理库交互
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


class FcosPostProcessInfo_t(ctypes.Structure):
    """
    FcosPostProcessInfo_t - FCOS后处理参数结构体
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
    """
    if Layout == "NCHW":
        return int(2)
    else:
        return int(0)


def get_classes():
    """
    获取COCO数据集80类目标名称列表
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


def get_hw(pro):
    """从Tensor属性中获取高度和宽度"""
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


def limit_display_cord(coor):
    """
    限制坐标在显示范围内
    """
    coor[0] = max(min(1920, coor[0]), 0)
    coor[1] = max(min(1080, coor[1]), 2)  # 留出文字显示空间
    coor[2] = max(min(1920, coor[2]), 0)
    coor[3] = max(min(1080, coor[3]), 0)
    return coor


# ================================================================================
# Protobuf序列化函数
# ================================================================================

def serialize(FrameMessage, data, ori_w, ori_h, target_w, target_h):
    """
    将检测结果序列化为Protobuf格式

    【参数】
        FrameMessage: Protobuf消息对象
        data: 检测结果列表
        ori_w, ori_h: 原始图像尺寸
        target_w, target_h: 目标显示尺寸

    【功能】
        1. 缩放边界框坐标到目标分辨率
        2. 构建Target和Box消息
        3. 序列化并返回字节流
    """
    # 计算缩放比例
    scale_x = target_w / ori_w
    scale_y = target_h / ori_h

    if data:
        for result in data:
            Target = x3_pb2.Target()
            bbox = result['bbox']      # 边界框坐标
            score = result['score']    # 置信度
            id = int(result['id'])     # 类别ID
            name = result['name']      # 类别名称

            coor = [round(i) for i in bbox]
            # 缩放坐标
            coor[0] = int(coor[0] * scale_x)
            coor[1] = int(coor[1] * scale_y)
            coor[2] = int(coor[2] * scale_x)
            coor[3] = int(coor[3] * scale_y)

            # 限制在显示范围内
            bbox = limit_display_cord(coor)

            # 构建消息
            Target.type_ = classes[id]
            Box = x3_pb2.Box()
            Box.type_ = classes[id]
            Box.score_ = float(score)
            Box.top_left_.x_ = int(bbox[0])
            Box.top_left_.y_ = int(bbox[1])
            Box.bottom_right_.x_ = int(bbox[2])
            Box.bottom_right_.y_ = int(bbox[3])

            Target.boxes_.append(Box)
            FrameMessage.smart_msg_.targets_.append(Target)

    # 序列化为字节流
    prot_buf = FrameMessage.SerializeToString()
    return prot_buf


# ================================================================================
# 全局变量初始化
# ================================================================================

# 加载FCOS模型
models = pyeasy_dnn.load('../models/fcos_512x512_nv12.bin')
input_shape = (512, 512)

# 初始化摄像头
cam = srcampy.Camera()
cam.open_cam(0, -1, fps, [512, 1920], [512, 1088], 1080, 1920)

# 初始化JPEG编码器
enc = srcampy.Encoder()
enc.encode(0, 3, 1920, 1088)

# 获取类别列表
classes = get_classes()

# 打印模型属性
print_properties(models[0].inputs[0].properties)
print("--- model output properties ---")
for output in models[0].outputs:
    print_properties(output.properties)

# ================================================================================
# 配置FCOS后处理参数
# ================================================================================

fcos_postprocess_info = FcosPostProcessInfo_t()
fcos_postprocess_info.height = 512
fcos_postprocess_info.width = 512
fcos_postprocess_info.ori_height = 1080
fcos_postprocess_info.ori_width = 1920
fcos_postprocess_info.score_threshold = 0.5
fcos_postprocess_info.nms_threshold = 0.6
fcos_postprocess_info.nms_top_k = 500
fcos_postprocess_info.is_pad_resize = 0

# 准备输出Tensor数组
output_tensors = (hbDNNTensor_t * len(models[0].outputs))()

for i in range(len(models[0].outputs)):
    output_tensors[i].properties.tensorLayout = get_TensorLayout(
        models[0].outputs[i].properties.layout
    )

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

    for j in range(len(models[0].outputs[i].properties.shape)):
        output_tensors[i].properties.validShape.dimensionSize[j] = \
            models[0].outputs[i].properties.shape[j]
        output_tensors[i].properties.alignedShape.dimensionSize[j] = \
            models[0].outputs[i].properties.shape[j]


# ================================================================================
# WebSocket服务函数
# ================================================================================

async def web_service(websocket, path=None):
    """
    WebSocket服务主函数

    【功能】
        1. 接收客户端连接
        2. 循环获取摄像头图像
        3. 执行目标检测
        4. 发送检测结果和视频流
    """
    while True:
        # 创建帧消息
        FrameMessage = x3_pb2.FrameMessage()
        FrameMessage.img_.height_ = 1080
        FrameMessage.img_.width_ = 1920
        FrameMessage.img_.type_ = "JPEG"

        # 获取摄像头图像（512x512用于推理）
        img = cam.get_img(2, 512, 512)
        img = np.frombuffer(img, dtype=np.uint8)

        # 执行推理
        t0 = time.time()
        outputs = models[0].forward(img)
        t1 = time.time()
        print("forward time is :", (t1 - t0))

        # FCOS后处理（5个尺度）
        strides = [8, 16, 32, 64, 128]
        for i in range(len(strides)):
            if output_tensors[i].properties.quantiType == 0:
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

            libpostprocess.FcosdoProcess(
                output_tensors[i],
                output_tensors[i + 5],
                output_tensors[i + 10],
                fcos_postprocess_info,
                i
            )

        # 获取后处理结果
        result_str = get_Postprocess_result(ctypes.pointer(fcos_postprocess_info))
        result_str = result_str.decode('utf-8')
        t2 = time.time()
        print("FcosdoProcess time is :", (t2 - t1))

        # 解析JSON结果
        data = json.loads(result_str[14:])

        # 获取全分辨率图像用于编码
        origin_image = cam.get_img(2, 1920, 1088)
        enc.encode_file(origin_image)
        FrameMessage.img_.buf_ = enc.get_img()
        FrameMessage.smart_msg_.timestamp_ = int(time.time())

        # 序列化检测结果
        prot_buf = serialize(
            FrameMessage,
            data,
            fcos_postprocess_info.width,
            fcos_postprocess_info.height,
            FrameMessage.img_.width_,
            FrameMessage.img_.height_
        )

        # 发送给客户端
        await websocket.send(prot_buf)

    # 关闭摄像头
    cam.close_cam()


# ================================================================================
# 主函数
# ================================================================================

async def main():
    """
    主函数 - 启动WebSocket服务器

    【功能】
        在0.0.0.0:8080启动WebSocket服务器
        等待客户端连接并处理请求
    """
    # 创建WebSocket服务器
    async with websockets.serve(web_service, "0.0.0.0", 8080):
        # 阻塞事件循环，保持运行
        await asyncio.Future()


# ================================================================================
# 信号处理器
# ================================================================================

def signal_handler(sig, frame):
    """处理Ctrl+C信号"""
    sys.exit(0)


# ================================================================================
# 程序入口
# ================================================================================

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    asyncio.run(main())

# ================================================================================
# 【WebSocket + Protobuf 通信协议】
# ================================================================================
# 本程序使用WebSocket传输Protobuf编码的数据，实现高效的实时通信：
#
# 1. 视频流（JPEG）
#    - 原始图像通过Encoder压缩为JPEG
#    - 通过WebSocket发送到浏览器
#    - 浏览器直接解码显示
#
# 2. 检测结果（Protobuf）
#    - 检测结果序列化为Protobuf格式
#    - 包含边界框坐标、类别、置信度
#    - 浏览器端解码并叠加显示
#
# 【优势】
# - WebSocket：支持双向通信，低延迟
# - Protobuf：体积小，序列化速度快
# - JPEG：浏览器原生支持，无需额外解码
#
# 【前端交互】
# 浏览器接收数据后：
# 1. 解析Protobuf获取检测结果
# 2. 在Canvas上绘制边界框
# 3. 更新图像显示
