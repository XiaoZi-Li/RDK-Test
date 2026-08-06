# pydev_demo 模块详细使用指南

## 目录
1. [模块概述](#1-模块概述)
2. [环境配置](#2-环境配置)
3. [01_basic_sample 基础分类模型](#3-01_basic_sample-基础分类模型)
4. [02_usb_camera_sample USB摄像头](#4-02_usb_camera_sample-usb摄像头)
5. [03_mipi_camera_sample MIPI摄像头](#5-03_mipi_camera_sample-mipi摄像头)
6. [04_segment_sample 语义分割](#6-04_segment_sample-语义分割)
7. [05_web_display_camera_sample 网页显示](#7-05_web_display_camera_sample-网页显示)
8. [06-12 目标检测系列](#8-06-12-目标检测系列)
9. [my_code_backup 代码备份详解](#9-my_code_backup-代码备份详解)
10. [参数调整详解](#10-参数调整详解)
11. [后处理库使用](#11-后处理库使用)
12. [常见问题解决](#12-常见问题解决)

---

## 1. 模块概述

### 1.1 功能说明
pydev_demo 提供基于 Python 的 AI 视觉推理示例，通过 `hobot_dnn` 或 `hobot_dnn_rdkx5` 库调用 BPU 加速器进行模型推理。相比 C++ 版本更易使用和调试。

### 1.2 核心库

| 库名 | 说明 | 导入语句 |
|------|------|----------|
| hobot_dnn | RDK X3版本 | `from hobot_dnn import pyeasy_dnn as dnn` |
| hobot_dnn_rdkx5 | RDK X5版本 | `from hobot_dnn_rdkx5 import pyeasy_dnn as dnn` |
| hobot_vio | 视频输入输出 | `from hobot_vio import libsrcampy as srcampy` |
| hobot_codec | 编解码 | `from hobot_codec import ...` |

### 1.3 目录结构
```
pydev_demo/
├── 01_basic_sample/              # 图像分类基础示例
│   ├── test_mobilenetv1.py     # MobileNetV1分类
│   ├── test_efficientnasnet_m.py # EfficientNASNet分类
│   ├── test_googlenet.py       # GoogleNet分类
│   ├── test_resnet18.py         # ResNet18分类
│   ├── test_vargconvnet.py     # VarGCNet分类
│   └── zebra_cls.jpg            # 测试图片
│
├── 02_usb_camera_sample/        # USB摄像头示例
│   ├── usb_camera_fcos.py      # USB摄像头FCOS检测
│   └── usb_camera_snap.py      # USB摄像头拍照
│
├── 03_mipi_camera_sample/       # MIPI摄像头示例
│   └── mipi_camera.py          # MIPI摄像头实时检测
│
├── 04_segment_sample/           # 语义分割示例
│   ├── test_mobilenet_unet.py # UNet分割
│   └── segmentation.png        # 分割结果示例
│
├── 05_web_display_camera_sample/ # 网页显示示例
│   ├── mipi_camera_web.py     # 网页摄像头
│   ├── start_nginx.sh         # Nginx启动脚本
│   ├── x3_pb2.py              # Protobuf定义
│   └── webservice/            # Web服务文件
│
├── 06_yolov3_sample/           # YOLOv3检测
├── 07_yolov5_sample/          # YOLOv5检测
├── 08_decode_rtsp_stream/      # RTSP解码
├── 09_yolov5x_sample/          # YOLOv5x检测
├── 10_ssd_mobilenetv1_sample/  # SSD检测
├── 11_centernet_sample/       # CenterNet检测
├── 12_yolov5s_v6_v7_sample/   # YOLOv5新版本
│
└── my_code_backup/            # 代码备份/扩展功能
```

---

## 2. 环境配置

### 2.1 必需依赖
```bash
# Python 版本
Python 3.8+

# 必需包
pip3 install numpy opencv-python
```

### 2.2 BPU推理库
```bash
# RDK X5 平台
pip3 install hobot-dnn-rdkx5
pip3 install hobot-vio-rdkx5

# RDK X3 平台
pip3 install hobot-dnn
pip3 install hobot-vio
```

### 2.3 验证安装
```python
# 测试导入
python3 -c "from hobot_dnn import pyeasy_dnn as dnn; print('OK')"

# 或
python3 -c "from hobot_dnn_rdkx5 import pyeasy_dnn as dnn; print('OK')"
```

---

## 3. 01_basic_sample 基础分类模型

### 3.1 概述
基础图像分类示例，演示如何加载模型、预处理图像、进行推理和后处理。

### 3.2 MobileNetV1 分类详解

**文件**: [test_mobilenetv1.py](file:///e:/BaiduNetdiskDownload/app/app/pydev_demo/01_basic_sample/test_mobilenetv1.py)

#### 完整代码注释
```python
#!/usr/bin/env python3

import numpy as np
import cv2

# BPU推理库
try:
    from hobot_dnn import pyeasy_dnn as dnn  # X3版本
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn  # X5版本

import time
import ctypes
import json

# ==================== C结构体定义 ====================
# 这些结构体用于与后处理C库交互

class hbSysMem_t(ctypes.Structure):
    _fields_ = [
        ("phyAddr", ctypes.c_double),    # 物理地址
        ("virAddr", ctypes.c_void_p),   # 虚拟地址
        ("memSize", ctypes.c_int)        # 内存大小
    ]

class hbDNNQuantiShift_yt(ctypes.Structure):
    _fields_ = [
        ("shiftLen", ctypes.c_int),      # 量化偏移长度
        ("shiftData", ctypes.c_char_p)   # 量化偏移数据
    ]

class hbDNNQuantiScale_t(ctypes.Structure):
    _fields_ = [
        ("scaleLen", ctypes.c_int),       # 量化比例长度
        ("scaleData", ctypes.POINTER(ctypes.c_float)),  # 比例数据
        ("zeroPointLen", ctypes.c_int),   # 零点长度
        ("zeroPointData", ctypes.c_char_p) # 零点数据
    ]

class hbDNNTensorShape_t(ctypes.Structure):
    _fields_ = [
        ("dimensionSize", ctypes.c_int * 8),  # 维度大小
        ("numDimensions", ctypes.c_int)        # 维度数量
    ]

class hbDNNTensorProperties_t(ctypes.Structure):
    _fields_ = [
        ("validShape", hbDNNTensorShape_t),      # 有效形状
        ("alignedShape", hbDNNTensorShape_t),    # 对齐形状
        ("tensorLayout", ctypes.c_int),          # 张量布局
        ("tensorType", ctypes.c_int),             # 张量类型
        ("shift", hbDNNQuantiShift_yt),          # 量化偏移
        ("scale", hbDNNQuantiScale_t),            # 量化比例
        ("quantiType", ctypes.c_int),             # 量化类型
        ("quantizeAxis", ctypes.c_int),           # 量化轴
        ("alignedByteSize", ctypes.c_int),         # 对齐字节大小
        ("stride", ctypes.c_int * 8)               # 步长
    ]

class hbDNNTensor_t(ctypes.Structure):
    _fields_ = [
        ("sysMem", hbSysMem_t * 4),              # 系统内存
        ("properties", hbDNNTensorProperties_t)  # 属性
    ]

# 分类后处理信息结构体
class ClassificationPostProcessInfo_t(ctypes.Structure):
    _fields_ = [
        ("height", ctypes.c_int),                 # 输入高度
        ("width", ctypes.c_int),                   # 输入宽度
        ("ori_height", ctypes.c_int),             # 原始高度
        ("ori_width", ctypes.c_int),               # 原始宽度
        ("score_threshold", ctypes.c_float),       # 置信度阈值
        ("nms_threshold", ctypes.c_float),         # NMS阈值
        ("nms_top_k", ctypes.c_int),               # Top-K
        ("is_pad_resize", ctypes.c_int)            # 是否带填充缩放
    ]

# ==================== 后处理库加载 ====================
libpostprocess = ctypes.CDLL('/usr/lib/libpostprocess.so')

get_Postprocess_result = libpostprocess.ClassificationPostProcess
get_Postprocess_result.argtypes = [ctypes.POINTER(ClassificationPostProcessInfo_t)]
get_Postprocess_result.restype = ctypes.c_char_p

# ==================== 工具函数 ====================

def get_TensorLayout(Layout):
    """获取张量布局"""
    if Layout == "NCHW":
        return int(2)
    else:
        return int(0)

def bgr2nv12_opencv(image):
    """将BGR图像转换为NV12格式

    NV12格式: Y平面 + UV交错平面
    Y平面: height × width
    UV平面: height/2 × width/2 (UV交错)
    """
    height, width = image.shape[0], image.shape[1]
    area = height * width

    # BGR -> YUV420
    yuv420p = cv2.cvtColor(image, cv2.COLOR_BGRYUV_I420).reshape((area * 3 // 2,))

    # Y分量
    y = yuv420p[:area]

    # UV分量 (交错存储)
    uv_planar = yuv420p[area:].reshape((2, area // 4))
    uv_packed = uv_planar.transpose((1, 0)).reshape((area // 2,))

    # 组合NV12
    nv12 = np.zeros_like(yuv420p)
    nv12[:height * width] = y
    nv12[height * width:] = uv_packed
    return nv12

def print_properties(pro):
    """打印张量属性"""
    print("tensor type:", pro.tensor_type)
    print("data type:", pro.dtype)
    print("layout:", pro.layout)
    print("shape:", pro.shape)

def get_hw(pro):
    """获取张量的高度和宽度"""
    if pro.layout == "NCHW":
        return pro.shape[2], pro.shape[3]
    else:
        return pro.shape[1], pro.shape[2]

# ==================== 主程序 ====================
if __name__ == '__main__':
    # 1. 加载模型
    models = dnn.load('../models/mobilenetv1_224x224_nv12.bin')

    # 2. 打印模型信息
    print("=" * 10, "inputs[0] properties", "=" * 10)
    print_properties(models[0].inputs[0].properties)
    print("inputs[0] name:", models[0].inputs[0].name)

    print("=" * 10, "outputs[0] properties", "=" * 10)
    print_properties(models[0].outputs[0].properties)
    print("outputs[0] name:", models[0].outputs[0].name)

    # 3. 读取并预处理图像
    img_file = cv2.imread('./zebra_cls.jpg')
    h, w = get_hw(models[0].inputs[0].properties)  # 224, 224
    des_dim = (w, h)
    resized_data = cv2.resize(img_file, des_dim, interpolation=cv2.INTER_AREA)
    nv12_data = bgr2nv12_opencv(resized_data)

    # 4. 推理
    outputs = models[0].forward(nv12_data)

    # 5. 后处理
    t0 = time.time()

    # 配置后处理参数
    classification_postprocess_info = ClassificationPostProcessInfo_t()
    classification_postprocess_info.height = h
    classification_postprocess_info.width = w
    org_height, org_width = img_file.shape[0:2]
    classification_postprocess_info.ori_height = org_height
    classification_postprocess_info.ori_width = org_width
    classification_postprocess_info.score_threshold = 0.3
    classification_postprocess_info.nms_threshold = 0
    classification_postprocess_info.nms_top_k = 500
    classification_postprocess_info.is_pad_resize = 0

    # 准备输出张量
    output_tensors = (hbDNNTensor_t * len(models[0].outputs))()

    for i in range(len(models[0].outputs)):
        output_tensors[i].properties.tensorLayout = get_TensorLayout(outputs[i].properties.layout)

        # 根据量化类型设置
        if (len(outputs[i].properties.scale_data) == 0):
            output_tensors[i].properties.quantiType = 0
            # float32类型
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ctypes.c_void_p)
        else:
            output_tensors[i].properties.quantiType = 2
            # int32量化类型
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
                                                ctypes.pointer(classification_postprocess_info),
                                                i)

    # 获取结果
    result_str = get_Postprocess_result(ctypes.pointer(classification_postprocess_info))
    result_str = result_str.decode('utf-8')
    t1 = time.time()
    print("postprocess time:", (t1 - t0))

    # 6. 解析并显示结果
    data = json.loads(result_str[25:])

    print("=" * 10, "Classification result", "=" * 10)
    for result in data:
        prob = result['prob']       # 置信度
        label = result['label']     # 类别ID
        name = result['class_name'] # 类别名称
        print(f"cls id: {label}, Confidence: {prob}, class_name: {name}")
```

### 3.3 使用方法
```bash
cd /app/pydev_demo/01_basic_sample
python3 test_mobilenetv1.py
```

### 3.4 输出示例
```
========== inputs[0] properties ==========
tensor type: 2
data type: <class 'numpy.uint8'>
layout: NHWC
shape: [1, 224, 224, 3]
inputs[0] name: image

========== outputs[0] properties ==========
tensor type: 4
data type: <class 'numpy.float32'>
layout: NHWC
shape: [1, 1, 1, 1000]
outputs[0] name: det_out

postprocess time: 0.012
========== Classification result ==========
cls id: 340, Confidence: 0.92, class_name: zebra
```

### 3.5 更换测试图片
```python
# 修改第147行
img_file = cv2.imread('./your_image.jpg')
```

---

## 4. 02_usb_camera_sample USB摄像头

### 4.1 usb_camera_fcos.py 详解

**功能**: 使用USB摄像头进行FCOS目标检测

#### 核心代码结构
```python
# USB摄像头使用 OpenCV
import cv2

# 打开USB摄像头
cap = cv2.VideoCapture(0)  # 0 = 默认摄像头

# 设置分辨率
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

# 读取帧
ret, frame = cap.read()
if ret:
    # 转换为NV12
    nv12_data = bgr2nv12_opencv(frame)
    # 送入模型推理
    outputs = model.forward(nv12_data)
```

#### 使用方法
```bash
cd /app/pydev_demo/02_usb_camera_sample
python3 usb_camera_fcos.py
```

### 4.2 usb_camera_snap.py 详解

**功能**: USB摄像头拍照保存

```python
# 核心代码
cap = cv2.VideoCapture(0)

# 拍照
ret, frame = cap.read()
if ret:
    # 保存图片
    cv2.imwrite('snapshot.jpg', frame)
    print("Saved to snapshot.jpg")

cap.release()
```

---

## 5. 03_mipi_camera_sample MIPI摄像头

### 5.1 mipi_camera.py 详解

**功能**: MIPI摄像头实时采集 + BPU推理

#### 核心代码结构
```python
# 导入摄像头库
try:
    from hobot_vio import libsrcampy as srcampy  # X3
except ImportError:
    from hobot_vio_rdkx5 import libsrcampy as srcampy  # X5

# 摄像头分辨率配置
sensor_width = 1920
sensor_height = 1080

# 获取摄像头对象
cam = srcampy.Camera()

# 打开摄像头
# 参数: 设备ID, 模式, 标志, [宽度列表], [高度列表], 传感器高, 传感器宽
cam.open_cam(0, -1, -1, [w, disp_w], [h, disp_h], sensor_height, sensor_width)

# 获取显示对象
disp = srcampy.Display()

# 绑定摄像头到显示
srcampy.bind(cam, disp)

# 主循环
while not is_stop:
    # 获取图像 (格式: NV12)
    img = cam.get_img(2, 512, 512)

    # 转换为numpy数组
    img = np.frombuffer(img, dtype=np.uint8)

    # BPU推理
    outputs = models[0].forward(img)

    # 后处理和显示...

# 清理
cam.close_cam()
disp.close()
```

#### 使用方法
```bash
cd /app/pydev_demo/03_mipi_camera_sample
python3 mipi_camera.py
```

#### 关键参数
```python
# 摄像头参数
sensor_width = 1920   # 传感器宽度
sensor_height = 1080   # 传感器高度

# 模型输入
h, w = 512, 512       # FCOS输入尺寸

# 显示配置
disp_w, disp_h = 1920, 1080  # 显示分辨率
```

---

## 6. 04_segment_sample 语义分割

### 6.1 test_mobilenet_unet.py 详解

**功能**: UNet语义分割，分割出不同类别的像素区域

#### 模型信息
- 模型: mobilenet_unet_1024x2048_nv12.bin
- 输入: 1024×2048 NV12
- 输出: 分割掩码

#### 核心后处理
```python
# 分割结果结构
class UnetPostProcessInfo_t(ctypes.Structure):
    _fields_ = [
        ("height", ctypes.c_int),
        ("width", ctypes.c_int),
        ("ori_height", ctypes.c_int),
        ("ori_width", ctypes.c_int),
        ("num_classes", ctypes.c_int),  # 分割类别数
    ]

# 后处理调用
libpostprocess.UnetPostProcess(output_tensor,
                               ctypes.pointer(unet_postprocess_info),
                               0)
```

#### 使用方法
```bash
cd /app/pydev_demo/04_segment_sample
python3 test_mobilenet_unet.py
```

---

## 7. 05_web_display_camera_sample 网页显示

### 7.1 功能说明
通过Nginx提供Web服务，在浏览器实时显示摄像头画面。

### 7.2 架构
```
摄像头 -> mipi_camera_web.py -> JPEG编码 -> Nginx -> 浏览器
```

### 7.3 使用方法

**步骤1: 启动Nginx**
```bash
cd /app/pydev_demo/05_web_display_camera_sample
./start_nginx.sh
```

**步骤2: 启动摄像头**
```bash
python3 mipi_camera_web.py
```

**步骤3: 访问**
```
http://设备IP地址:8080/
```

### 7.4 start_nginx.sh 脚本内容
```bash
#!/bin/bash

# 停止现有Nginx
nginx -s stop 2>/dev/null

# 启动Nginx (前台运行)
nginx -c ./webservice/conf/nginx.conf -g 'daemon off;'
```

### 7.5 配置修改
修改 `webservice/conf/nginx.conf`:
```nginx
server {
    listen 8080;  # 端口号
    server_name localhost;

    location / {
        root html;  # 网页根目录
        index index.html;
    }

    # 摄像头流
    location /camera {
        proxy_pass http://127.0.0.1:8000;
    }
}
```

---

## 8. 06-12 目标检测系列

### 8.1 模型对比表

| 目录 | 模型 | 输入尺寸 | 速度 | 精度 | 适用场景 |
|------|------|----------|------|------|----------|
| 06 | YOLOv3 | 416×416 | 中 | 高 | 通用检测 |
| 07 | YOLOv5s | 672×672 | 快 | 中 | **实时推荐** |
| 08 | RTSP解码 | - | - | - | 视频流 |
| 09 | YOLOv5x | 672×672 | 慢 | 最高 | 高精度 |
| 10 | SSD | 300×300 | 最快 | 中 | 移动端 |
| 11 | CenterNet | 512×512 | 中 | 高 | 关键点检测 |
| 12 | YOLOv5s v6/v7 | 640×640 | 快 | 高 | 新版本 |

### 8.2 YOLOv5 详解 (07_yolov5_sample)

**最推荐的示例**，实时性好，使用广泛。

#### yolov5_camera.py 核心参数
```python
# 模型配置
models = dnn.load('../models/yolov5s_672x672_nv12.bin')

# 后处理参数
yolov5_postprocess_info = Yolov5PostProcessInfo_t()
yolov5_postprocess_info.height = 672
yolov5_postprocess_info.width = 672
yolov5_postprocess_info.ori_height = disp_h  # 原始图像高度
yolov5_postprocess_info.ori_width = disp_w  # 原始图像宽度
yolov5_postprocess_info.score_threshold = 0.4  # 置信度阈值
yolov5_postprocess_info.nms_threshold = 0.45   # NMS阈值
yolov5_postprocess_info.nms_top_k = 20         # Top-K
yolov5_postprocess_info.is_pad_resize = 0
```

#### COCO类别 (80类)
```python
classes = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    # ... 共80类
]
```

#### 使用方法
```bash
# 实时摄像头检测
cd /app/pydev_demo/07_yolov5_sample
python3 yolov5_camera.py

# 图片测试
python3 test_yolov5.py
```

### 8.3 YOLOv3 详解 (06_yolov3_sample)

#### 与YOLOv5的区别
| 参数 | YOLOv3 | YOLOv5 |
|------|--------|--------|
| 输入尺寸 | 416 | 672 |
| 输出层数 | 3 | 3 |
| 后处理函数 | Yolov3doProcess | Yolov5doProcess |

#### 使用方法
```bash
cd /app/pydev_demo/06_yolov3_sample
python3 test_yolov3.py
```

### 8.4 SSD MobileNetV1 详解 (10_ssd_mobilenetv1_sample)

**特点**: 极轻量级，适合边缘设备

#### 参数配置
```python
# SSD 输入尺寸
input_width = 300
input_height = 300

# SSD 输出层数
ssd_output_nums_ = 12
```

#### 使用方法
```bash
cd /app/pydev_demo/10_ssd_mobilenetv1_sample
python3 test_ssd_mobilenetv1.py
```

### 8.5 CenterNet 详解 (11_centernet_sample)

**特点**: 基于关键点的检测，无锚框

#### 参数配置
```python
# CenterNet 输入尺寸
input_width = 512
input_height = 512

# 输出: heatmap, size, offset
```

#### 使用方法
```bash
cd /app/pydev_demo/11_centernet_sample
python3 test_centernet.py
```

### 8.6 RTSP流解码 (08_decode_rtsp_stream)

**功能**: 解码RTSP视频流进行检测

```python
# 使用hobot_codec解码
from hobot_codec import ...

# 初始化解码器
decoder = hobot_codec.Decoder()

# 打开RTSP流
decoder.open_rtsp("rtsp://example.com/stream")

# 解码循环
while True:
    frame = decoder.read()
    if frame is not None:
        # 转换为NV12
        nv12 = bgr2nv12_opencv(frame)
        # BPU推理
        outputs = model.forward(nv12)
```

---

## 9. my_code_backup 代码备份详解

### 9.1 目录结构
```
my_code_backup/
├── puppy_control/          # 机器狗控制
├── puppy_extend_demo/      # 扩展功能示例
├── puppy_bringup/          # 启动配置
├── puppy_navigation/       # 导航
├── puppy_slam/            # SLAM建图
├── puppy_with_arm/        # 机械臂控制
├── large_models/          # 大模型集成
├── apriltag_detect/       # Apriltag定位
├── color_detect/         # 颜色检测
├── face_detect/          # 人脸检测
├── lidar_app/            # 雷达应用
├── object_tracking/       # 目标跟踪
├── ros_robot_controller/  # ROS机器人控制
└── ...
```

### 9.2 puppy_control 机器狗控制

**关键文件**: puppy_demo.py

```python
import rospy
from puppy_control.msg import Velocity, Pose, Gait

# 运动参数
PuppyMove = {
    'x': 5,      # 前进速度 (cm/s)
    'y': 0,      # 侧移速度 (cm/s)
    'yaw_rate': 0  # 转向角速度 (rad/s)
}

# 姿态参数
PuppyPose = {
    'roll': math.radians(0),   # 横滚角
    'pitch': math.radians(0),  # 俯仰角
    'yaw': 0,                  # 偏航角
    'height': -10,             # 高度 (cm)
    'x_shift': 0.5,            # X偏移
    'stance_x': 0,             # Xstance
    'stance_y': 0              # Ystance
}

# 步态配置
GaitConfig = {
    'overlap_time': 0.2,    # 支撑相时长
    'swing_time': 0.3,      # 摆动相时长
    'clearance_time': 0.0,  # 抬腿间隔
    'z_clearance': 8        # 抬腿高度
}

# 发布控制指令
PuppyVelocityPub.publish(x=5, y=0, yaw_rate=0.5)
```

### 9.3 puppy_extend_demo 扩展功能

| 示例文件 | 功能 |
|----------|------|
| servo_control_single.py | 单舵机控制 |
| servo_control_multi.py | 多舵机控制 |
| servo_control_speed.py | 舵机速度控制 |
| rgb_control_demo.py | RGB LED控制 |
| buzzer_control_demo.py | 蜂鸣器控制 |
| sonar_avoidance.py | 超声波避障 |
| face_detect.py | 人脸检测 |
| mp3_moonwalk_demo.py | 音乐播放+跳舞 |

---

## 10. 参数调整详解

### 10.1 推理参数

#### 置信度阈值 (score_threshold)
```python
# 默认值
score_threshold = 0.4

# 高灵敏度 (检测更多目标，但可能误检)
score_threshold = 0.2

# 高精度 (减少误检，但可能漏检)
score_threshold = 0.6
```

#### NMS阈值 (nms_threshold)
```python
# 默认值
nms_threshold = 0.45

# 更多重叠框被保留
nms_threshold = 0.6

# 更多重叠框被抑制
nms_threshold = 0.3
```

#### Top-K
```python
# 默认值
nms_top_k = 20

# 检测更多目标
nms_top_k = 50

# 只保留最可信的目标
nms_top_k = 10
```

### 10.2 显示参数

```python
# 显示分辨率
disp_w = 1920
disp_h = 1080

# 缩放边界框到原始分辨率
def scale_bbox(bbox, input_w, input_h, output_w, output_h):
    scale_x = output_w / input_w
    scale_y = output_h / input_h
    return [
        int(bbox[0] * scale_x),
        int(bbox[1] * scale_y),
        int(bbox[2] * scale_x),
        int(bbox[3] * scale_y)
    ]
```

---

## 11. 后处理库使用

### 11.1 后处理库路径
```
/usr/lib/libpostprocess.so
```

### 11.2 可用后处理函数

| 函数 | 模型 | 功能 |
|------|------|------|
| Yolov5PostProcess | YOLOv5 | YOLOv5后处理 |
| Yolov5doProcess | YOLOv5 | YOLOv5单层处理 |
| Yolov3PostProcess | YOLOv3 | YOLOv3后处理 |
| Yolov3_ParseTensor | YOLOv3 | YOLOv3张量解析 |
| FcosPostProcess | FCOS | FCOS后处理 |
| FcosdoProcess | FCOS | FCOS单层处理 |
| SSDPostProcess | SSD | SSD后处理 |
| CenternetPostProcess | CenterNet | CenterNet后处理 |
| ClassificationPostProcess | MobileNet | 分类后处理 |
| UnetPostProcess | UNet | 分割后处理 |

### 11.3 后处理信息结构体

```python
class Yolov5PostProcessInfo_t(ctypes.Structure):
    _fields_ = [
        ("height", ctypes.c_int),              # 模型输入高度
        ("width", ctypes.c_int),               # 模型输入宽度
        ("ori_height", ctypes.c_int),          # 原始图像高度
        ("ori_width", ctypes.c_int),           # 原始图像宽度
        ("score_threshold", ctypes.c_float),   # 置信度阈值
        ("nms_threshold", ctypes.c_float),     # NMS阈值
        ("nms_top_k", ctypes.c_int),           # Top-K
        ("is_pad_resize", ctypes.c_int),        # 是否带填充缩放
    ]
```

---

## 12. 常见问题解决

### 12.1 导入错误

**问题**: `ModuleNotFoundError: No module named 'hobot_dnn'`

**解决**:
```bash
# 安装正确的库
pip3 install hobot-dnn-rdkx5    # X5平台
pip3 install hobot-dnn          # X3平台
```

### 12.2 模型加载失败

**问题**: `RuntimeError: load model failed`

**解决**:
```bash
# 检查模型文件
ls -la /app/model/basic/*.bin

# 检查权限
chmod 644 /app/model/basic/*.bin
```

### 12.3 摄像头打开失败

**问题**: `Camera open failed`

**解决**:
```bash
# 检查摄像头设备
ls -la /dev/video*

# MIPI摄像头需要特定驱动
# USB摄像头尝试
python3 -c "import cv2; print(cv2.__version__)"
```

### 12.4 内存不足

**问题**: `std::bad_alloc` 或内存分配失败

**解决**:
```python
# 减小输入分辨率
h, w = 320, 320  # 而不是 672, 672

# 减少批处理大小
# 默认batch_size=1
```

---

## 附录: 快速参考

```bash
# 图像分类
cd 01_basic_sample && python3 test_mobilenetv1.py

# USB摄像头检测
cd 02_usb_camera_sample && python3 usb_camera_fcos.py

# MIPI摄像头实时检测
cd 03_mipi_camera_sample && python3 mipi_camera.py

# 语义分割
cd 04_segment_sample && python3 test_mobilenet_unet.py

# YOLOv5实时检测
cd 07_yolov5_sample && python3 yolov5_camera.py

# YOLOv5图片测试
cd 07_yolov5_sample && python3 test_yolov5.py
```

---

**文档版本**: 1.0
**更新日期**: 2026-04-20
**适用平台**: 地平线 RDK X3/X5 开发板
**Python版本**: 3.8+
