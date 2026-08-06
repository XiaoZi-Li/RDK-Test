#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_mobilenet_unet.py - MobileNetV1 + UNet语义分割示例
================================================================================

【程序功能】
本程序使用MobileNetV1作为backbone的UNet网络进行图像语义分割。
UNet是一种经典的编码器-解码器结构的语义分割网络，广泛应用于医学图像、自动驾驶等领域。

【模型信息】
- 模型名称：MobileNetV1-UNet
- 输入尺寸：1024x2048像素（Cityscapes城市景观数据集标准尺寸）
- 输入格式：NV12
- 输出：Cityscapes 19类语义分割结果

【UNet网络结构】
┌─────────────────────────────────────────────────────────────┐
│                      编码器 (Encoder)                        │
│  输入 → Conv1 → Conv2 → Conv3 → Conv4 → Conv5 → Bottleneck │
│    ↓       ↓       ↓       ↓       ↓       ↓               │
│  特征   1/2    1/4    1/8   1/16   1/32   1/32            │
└─────────────────────────────────────────────────────────────┘
                            ↓ 跳跃连接
┌─────────────────────────────────────────────────────────────┐
│                      解码器 (Decoder)                        │
│  Bottleneck → Up1 → Up2 → Up3 → Up4 → Up5 → 分割输出      │
│    ↑       ↑     ↑     ↑     ↑     ↑                      │
│  特征   1/16   1/8   1/4   1/2   1/1                     │
└─────────────────────────────────────────────────────────────┘

【MobileNetV1特点】
1. 深度可分离卷积：将标准卷积分解为深度卷积和逐点卷积
2. 大幅减少参数量和计算量
3. 适合移动端和边缘设备部署

【Cityscapes数据集类别】
人行道、行人、骑行者、汽车、卡车、公交车、火车、摩托车、自行车、交通标志、人行横道、围栏、柱子、墙体、护栏、植被、地面、天空

【运行方式】
cd pydev_demo/04_segment_sample/
python3 test_mobilenet_unet.py

【输出】
- segment_result.png：分割结果图像（叠加在原图上，60%透明度）

================================================================================
"""

try:
    from hobot_dnn import pyeasy_dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn
import numpy as np
import cv2
from PIL import Image
from matplotlib import pyplot as plt

# ================================================================================
# 辅助函数
# ================================================================================

def bgr2nv12_opencv(image):
    """
    BGR图像转NV12格式

    【NV12格式】
        Y平面：H x W（亮度）
        UV平面：H/2 x W（色度，U/V交错）
    """
    height, width = image.shape[0], image.shape[1]
    area = height * width
    yuv420p = cv2.cvtColor(image, cv2.COLOR_BGRYUV_I420).reshape((area * 3 // 2,))
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


def get_pallete():
    """
    获取Cityscapes数据集的19类分割调色板

    【调色板说明】
        每个类别对应一个RGB颜色，用于可视化分割结果
        格式：[R1,G1,B1, R2,G2,B2, ...]

    【Cityscapes类别颜色表】
        - 道路: (128, 64, 128) 紫色
        - 人行道: (244, 35, 232) 粉紫色
        - 建筑: (70, 70, 70) 深灰色
        - 围栏: (190, 153, 153) 浅灰色
        - 植被: (107, 142, 35) 黄绿色
        - 天空: (70, 130, 180) 天蓝色
        等等...
    """
    pallete = [
        128, 64, 128,    # 道路
        244, 35, 232,    # 人行道
        70, 70, 70,      # 建筑
        102, 102, 156,   # 围栏
        156, 190, 153,   # 柱子
        153, 153, 153,   # 交通标志
        153, 153, 153,   # 围墙
        250, 170, 30,    # 护栏
        220, 220, 0,     # 交通灯
        107, 142, 35,    # 植被
        152, 251, 152,   # 地面
        0, 130, 180,     # 天空
        220, 20, 60,     # 行人
        255, 0, 0,       # 骑行者
        0, 0, 142,       # 汽车
        0, 0, 70,        # 卡车
        0, 60, 100,      # 公交车
        0, 80, 100,      # 火车
        0, 230, 119,     # 摩托车
        11, 32,          # 自行车
    ]
    return pallete


def plot_image(origin_image, onnx_output):
    """
    可视化分割结果

    【参数】
        origin_image: 原图
        onnx_output: 分割预测结果（每个像素的类别ID）

    【处理流程】
        1. 将预测结果缩放到原图尺寸
        2. 将类别ID转换为调色板颜色
        3. 与原图叠加显示（60%透明度）
        4. 保存结果图像
    """
    # 确保输出是uint8类型
    onnx_output = onnx_output.astype(np.uint8)
    onnx_output = np.squeeze(onnx_output)  # 移除所有大小为1的维度

    # 获取原图尺寸（宽高顺序）
    image_shape = origin_image.shape[:2][::-1]

    # 扩展维度并resize到原图尺寸
    # 使用INTER_NEAREST保持分割标签的准确性
    onnx_output = np.expand_dims(onnx_output, axis=2)
    onnx_output = cv2.resize(onnx_output,
                             image_shape,
                             interpolation=cv2.INTER_NEAREST)

    # 创建调色板图像
    out_img = Image.fromarray(onnx_output)
    out_img.putpalette(get_pallete())

    # 叠加显示原图和分割结果
    plt.imshow(origin_image)           # 显示原图
    plt.imshow(out_img, alpha=0.6)     # 叠加分割结果，60%透明度

    # 保存结果
    fig_name = 'segment_result.png'
    print(f"Saving predicted image with name {fig_name} ")
    plt.savefig(fig_name)


def postprocess(model_output, origin_image):
    """
    后处理：解析分割结果并可视化

    【参数】
        model_output: 模型输出（每个像素的类别概率）
        origin_image: 原图

    【处理流程】
        1. 对输出进行argmax，获取每个像素的类别ID
        2. 调用plot_image进行可视化
    """
    # 在最后一个维度上取argmax，获取每个像素的类别ID
    pred_result = np.argmax(model_output[0], axis=-1)

    print("=" * 10, "Postprocess successfully.", "=" * 10)
    print("=" * 10, "Waiting for drawing image ", "." * 10)

    plot_image(origin_image, pred_result)

    print("=" * 10, "Dump result image segment_result.png successfully.", "=" * 10)


# ================================================================================
# 主程序入口
# ================================================================================

if __name__ == '__main__':
    # ==========================================================================
    # 第1步：加载MobileNetV1-UNet分割模型
    # ==========================================================================
    models = pyeasy_dnn.load('../models/mobilenet_unet_1024x2048_nv12.bin')
    print("=" * 10, "Model load successfully.", "=" * 10)

    # ==========================================================================
    # 第2步：读取并预处理测试图像
    # ==========================================================================
    # 获取模型输入尺寸
    h, w = get_hw(models[0].inputs[0].properties)

    # 读取分割测试图像
    img_file = cv2.imread('./segmentation.png')

    # 调整图像到模型输入尺寸
    des_dim = (w, h)
    resized_data = cv2.resize(img_file, des_dim, interpolation=cv2.INTER_AREA)

    # 转换为NV12格式
    nv12_data = bgr2nv12_opencv(resized_data)

    # ==========================================================================
    # 第3步：执行模型推理
    # ==========================================================================
    outputs = models[0].forward(nv12_data)
    print("=" * 10, "Model forward finished.", "=" * 10)

    # ==========================================================================
    # 第4步：后处理和可视化
    # ==========================================================================
    postprocess(outputs[0].buffer, img_file)

# ================================================================================
# 【语义分割 vs 目标检测】
# ================================================================================
# | 特性         | 语义分割                | 目标检测              |
# |--------------|-------------------------|----------------------|
# | 输出         | 每个像素的类别标签      | 边界框+类别+置信度   |
# | 重叠物体     | 只能标记一个类别        | 可以检测多个物体      |
# | 实例区分     | 同类物体不区分          | 区分同类不同实例      |
# | 计算量       | 通常较大                | 相对较小              |
# | 应用场景     | 自动驾驶、医学图像      | 人脸识别、安防监控    |
#
# UNet的编码器-解码器结构特别适合需要精细边缘分割的任务
