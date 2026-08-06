#!/usr/bin/env python3

################################################################################
# Simplified YOLOv8 BPU Inference Sample (without complex postprocessing)
################################################################################

import numpy as np
import cv2
try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn
import time


def bgr2nv12_opencv(image):
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
    if pro.layout == "NCHW":
        return pro.shape[2], pro.shape[3]
    else:
        return pro.shape[1], pro.shape[2]


if __name__ == '__main__':
    # 加载YOLOv8模型
    models = dnn.load('../models/yolov8_640x640_nv12.bin')
    
    print("YOLOv8 Model Info:")
    print(f"Input type: {models[0].inputs[0].properties.tensor_type}")
    print(f"Input layout: {models[0].inputs[0].properties.layout}")
    print(f"Input shape: {models[0].inputs[0].properties.shape}")
    print(f"Number of outputs: {len(models[0].outputs)}")
    
    for i, output in enumerate(models[0].outputs):
        print(f"Output {i} shape: {output.properties.shape}")
    
    # 创建测试图片
    img_file = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    cv2.imwrite('test_image.jpg', img_file)
    
    # 预处理
    h, w = get_hw(models[0].inputs[0].properties)
    des_dim = (w, h)
    resized_data = cv2.resize(img_file, des_dim, interpolation=cv2.INTER_AREA)
    nv12_data = bgr2nv12_opencv(resized_data)
    
    # BPU推理
    print("\nRunning YOLOv8 inference...")
    t0 = time.time()
    outputs = models[0].forward(nv12_data)
    t1 = time.time()
    
    print(f"Inference time: {(t1 - t0)*1000:.2f} ms")
    print(f"BPU was used: {len(outputs) > 0}")
    
    # 显示输出信息
    print(f"\nOutput tensors:")
    for i, output in enumerate(outputs):
        print(f"  Output {i}: shape={output.properties.shape}, dtype={output.properties.dtype}")
        output_buffer = np.frombuffer(output.buffer, dtype=output.properties.dtype)
        output_buffer = output_buffer.reshape(output.properties.shape)
        print(f"    Range: [{np.min(output_buffer):.3f}, {np.max(output_buffer):.3f}]")
    
    print("\nYOLOv8 BPU inference completed successfully!")