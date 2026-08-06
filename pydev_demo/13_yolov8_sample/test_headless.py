#!/usr/bin/env python3

################################################################################
# YOLOv8 BPU Headless Detection Demo (无GUI版本)
################################################################################

import numpy as np
import cv2
import time
try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn


def main():
    print("="*60)
    print("YOLOv8 BPU Headless Detection Demo")
    print("="*60)
    
    # 加载模型
    print("Loading YOLOv8 model...")
    models = dnn.load('../models/yolov8_640x640_nv12.bin')
    
    # 获取输入尺寸
    pro = models[0].inputs[0].properties
    if pro.layout == "NCHW":
        input_height, input_width = pro.shape[2], pro.shape[3]
    else:
        input_height, input_width = pro.shape[1], pro.shape[2]
    
    print(f"Model loaded: {input_width}x{input_height}")
    print(f"Number of outputs: {len(models[0].outputs)}")
    
    # 创建测试图像
    print("\nCreating test image...")
    test_img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    cv2.imwrite('headless_test_input.jpg', test_img)
    
    # BGR转NV12函数
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
    
    # 预处理
    print("Preprocessing image...")
    resized = cv2.resize(test_img, (input_width, input_height), interpolation=cv2.INTER_AREA)
    nv12_data = bgr2nv12_opencv(resized)
    
    # 预热
    print("Warming up BPU...")
    for i in range(3):
        outputs = models[0].forward(nv12_data)
        print(f"  Warmup {i+1}/3 completed")
    
    # 性能测试
    print("\nStarting performance test...")
    num_iterations = 50
    inference_times = []
    
    for i in range(num_iterations):
        start_time = time.time()
        outputs = models[0].forward(nv12_data)
        end_time = time.time()
        
        inference_time = (end_time - start_time) * 1000  # ms
        inference_times.append(inference_time)
        
        if (i + 1) % 10 == 0:
            print(f"  Progress: {i + 1}/{num_iterations}")
    
    # 统计结果
    inference_times = np.array(inference_times)
    total_time = np.sum(inference_times)
    avg_time = np.mean(inference_times)
    min_time = np.min(inference_times)
    max_time = np.max(inference_times)
    std_time = np.std(inference_times)
    avg_fps = 1000 / avg_time
    
    print("\n" + "="*60)
    print("PERFORMANCE RESULTS")
    print("="*60)
    print(f"Test iterations: {num_iterations}")
    print(f"Total time: {total_time:.2f} ms")
    print(f"Average inference time: {avg_time:.2f} ms")
    print(f"Minimum inference time: {min_time:.2f} ms")
    print(f"Maximum inference time: {max_time:.2f} ms")
    print(f"Standard deviation: {std_time:.2f} ms")
    print(f"Average FPS: {avg_fps:.1f}")
    print(f"Theoretical max FPS: {1000/min_time:.1f}")
    
    # 显示输出信息
    print(f"\n" + "="*60)
    print("OUTPUT TENSOR INFORMATION")
    print("="*60)
    for i, output in enumerate(models[0].outputs):
        print(f"Output {i}:")
        print(f"  Shape: {output.properties.shape}")
        print(f"  Type: {output.properties.tensor_type}")
        print(f"  Data type: {output.properties.dtype}")
        
        # 获取输出数据范围
        output_buffer = np.frombuffer(output.buffer, dtype=output.properties.dtype)
        output_buffer = output_buffer.reshape(output.properties.shape)
        print(f"  Range: [{np.min(output_buffer):.3f}, {np.max(output_buffer):.3f}]")
        
        # 检查是否有检测框（简化检查）
        if np.any(output_buffer > 0):
            print(f"  Detection activity detected")
        else:
            print(f"  No significant detection activity")
        print()
    
    # BPU状态信息
    try:
        with open('/sys/devices/system/bpu/bpu0/ratio', 'r') as f:
            bpu_ratio = int(f.read().strip())
        print(f"Current BPU usage: {bpu_ratio}%")
    except:
        pass
    
    print("\n" + "="*60)
    print("DEMO COMPLETED SUCCESSFULLY")
    print("="*60)
    print("Files created:")
    print("  - headless_test_input.jpg (test input image)")
    print(f"  - Average FPS: {avg_fps:.1f}")
    print(f"  - Inference time: {avg_time:.2f} ms")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nDemo interrupted by user")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()