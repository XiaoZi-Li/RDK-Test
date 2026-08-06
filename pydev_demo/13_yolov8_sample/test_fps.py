#!/usr/bin/env python3

################################################################################
# YOLOv8 BPU FPS Performance Test
################################################################################

import numpy as np
import cv2
import time
import sys
try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn


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
    # 加载模型
    print("Loading YOLOv8 model...")
    models = dnn.load('../models/yolov8_640x640_nv12.bin')
    
    # 准备测试数据
    h, w = get_hw(models[0].inputs[0].properties)
    des_dim = (w, h)
    
    # 创建测试图片（避免重复创建开销）
    test_img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    resized_data = cv2.resize(test_img, des_dim, interpolation=cv2.INTER_AREA)
    nv12_data = bgr2nv12_opencv(resized_data)
    
    # 预热
    print("Warming up BPU...")
    for _ in range(3):
        models[0].forward(nv12_data)
    
    # FPS测试
    num_iterations = 100
    print(f"Starting FPS test with {num_iterations} iterations...")
    
    start_time = time.time()
    bpu_start_ratio = None
    bpu_end_ratio = None
    
    # 检测BPU使用率变化
    import os
    def get_bpu_ratio():
        try:
            with open('/sys/devices/system/bpu/bpu0/ratio', 'r') as f:
                return int(f.read().strip())
        except:
            return 0
    
    bpu_max = 0
    inference_times = []
    
    for i in range(num_iterations):
        if i == 0:
            bpu_start_ratio = get_bpu_ratio()
        
        # 单次推理计时
        iter_start = time.time()
        outputs = models[0].forward(nv12_data)
        iter_end = time.time()
        
        inference_times.append((iter_end - iter_start) * 1000)  # 转换为ms
        
        # 检查BPU使用率
        bpu_ratio = get_bpu_ratio()
        bpu_max = max(bpu_max, bpu_ratio)
        
        if (i + 1) % 10 == 0:
            print(f"  Progress: {i + 1}/{num_iterations}")
    
    end_time = time.time()
    bpu_end_ratio = get_bpu_ratio()
    
    # 统计结果
    total_time = end_time - start_time
    avg_fps = num_iterations / total_time
    
    inference_times = np.array(inference_times)
    avg_inference_time = np.mean(inference_times)
    min_inference_time = np.min(inference_times)
    max_inference_time = np.max(inference_times)
    
    print("\n" + "="*50)
    print("YOLOv8 BPU FPS Test Results")
    print("="*50)
    print(f"Total iterations: {num_iterations}")
    print(f"Total time: {total_time:.3f} seconds")
    print(f"Average FPS: {avg_fps:.1f}")
    print(f"Theoretical max FPS: {1000/avg_inference_time:.1f}")
    print(f"\nInference Time Statistics:")
    print(f"  Average: {avg_inference_time:.2f} ms")
    print(f"  Min: {min_inference_time:.2f} ms")
    print(f"  Max: {max_inference_time:.2f} ms")
    print(f"  Std: {np.std(inference_times):.2f} ms")
    print(f"\nBPU Usage:")
    print(f"  Start ratio: {bpu_start_ratio}%")
    print(f"  Max ratio observed: {bpu_max}%")
    print(f"  End ratio: {bpu_end_ratio}%")
    print("="*50)
    
    # 计算实际应用的FPS（考虑数据处理等开销）
    print(f"\nRealistic FPS estimate (with preprocessing overhead): ~{avg_fps * 0.8:.0f} FPS")