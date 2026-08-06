#!/usr/bin/env python3

################################################################################
# Simple YOLOv8 BPU GUI Demo (实际推理版本)
################################################################################

import numpy as np
import cv2
import time
import threading
try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn


class SimpleYOLOv8GUI:
    def __init__(self):
        # 加载YOLOv8模型
        print("Loading YOLOv8 model...")
        self.models = dnn.load('../models/yolov8_640x640_nv12.bin')
        self.input_height, self.input_width = self.get_input_shape()
        
        # 性能统计
        self.inference_times = []
        self.fps_counter = 0
        self.last_fps_time = time.time()
        self.current_fps = 0
        
        print(f"Model loaded: {self.input_width}x{self.input_height}")

    def get_input_shape(self):
        pro = self.models[0].inputs[0].properties
        if pro.layout == "NCHW":
            return pro.shape[2], pro.shape[3]
        else:
            return pro.shape[1], pro.shape[2]

    def bgr2nv12_opencv(self, image):
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

    def infer(self, image):
        """执行BPU推理"""
        # 预处理
        resized = cv2.resize(image, (self.input_width, self.input_height), interpolation=cv2.INTER_AREA)
        nv12_data = self.bgr2nv12_opencv(resized)
        
        # BPU推理
        start_time = time.time()
        outputs = self.models[0].forward(nv12_data)
        inference_time = (time.time() - start_time) * 1000
        
        # 统计性能
        self.inference_times.append(inference_time)
        if len(self.inference_times) > 100:
            self.inference_times.pop(0)
        
        # 更新FPS
        self.fps_counter += 1
        current_time = time.time()
        if current_time - self.last_fps_time >= 1.0:
            self.current_fps = self.fps_counter
            self.fps_counter = 0
            self.last_fps_time = current_time
        
        return outputs, inference_time

    def create_demo_display(self):
        """创建演示界面"""
        # 创建不同类型的测试图像
    def create_test_scene(self):
        """创建测试场景"""
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (40, 40, 60)  # 深蓝色背景
        
        # 绘制一些几何图形模拟检测对象
        cv2.rectangle(img, (100, 100), (200, 200), (0, 255, 0), -1)
        cv2.rectangle(img, (300, 150), (400, 350), (255, 0, 0), -1)
        cv2.circle(img, (500, 300), 50, (0, 0, 255), -1)
        cv2.ellipse(img, (150, 350), (80, 40), 45, 0, 360, (255, 255, 0), -1)
        
        # 添加文字
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(img, 'YOLOv8 BPU Demo', (180, 50), font, 1, (255, 255, 255), 2)
        cv2.putText(img, 'Press ESC to quit', (220, 420), font, 0.7, (200, 200, 200), 2)
        
        return img

    def draw_inference_info(self, img, inference_time):
        """绘制推理信息"""
        # 计算平均推理时间
        if self.inference_times:
            avg_time = np.mean(self.inference_times[-10:])  # 最近10次的平均值
            min_time = np.min(self.inference_times[-10:])
            max_time = np.max(self.inference_times[-10:])
        else:
            avg_time = min_time = max_time = 0
        
        # 获取BPU使用率
        try:
            with open('/sys/devices/system/bpu/bpu0/ratio', 'r') as f:
                bpu_ratio = int(f.read().strip())
        except:
            bpu_ratio = 0
        
        # 创建信息面板背景
        panel = np.zeros((120, 250, 3), dtype=np.uint8)
        panel[:] = (20, 20, 20)
        
        # 绘制信息文字
        font = cv2.FONT_HERSHEY_SIMPLEX
        info_lines = [
            f"FPS: {self.current_fps}",
            f"Inference: {inference_time:.1f}ms",
            f"Average: {avg_time:.1f}ms",
            f"Min/Max: {min_time:.1f}/{max_time:.1f}ms",
            f"BPU Usage: {bpu_ratio}%"
        ]
        
        for i, line in enumerate(info_lines):
            cv2.putText(panel, line, (10, 20 + i*20), font, 0.5, (0, 255, 0), 1)
        
        # 将面板叠加到主图像
        h, w = panel.shape[:2]
        img[10:h+10, 10:w+10] = panel
        
        # 绘制BPU使用率条形图
        bar_width = int(200 * bpu_ratio / 100.0)
        cv2.rectangle(img, (10, 140), (10+200, 150), (50, 50, 50), -1)
        cv2.rectangle(img, (10, 140), (10+bar_width, 150), (0, 255, 0), -1)
        
        return img

    def run_simple_demo(self):
        """运行简单演示"""
        print("Starting Simple YOLOv8 BPU Demo...")
        print("Press ESC to quit")
        
        # 创建窗口
        cv2.namedWindow('YOLOv8 BPU Real-time Demo', cv2.WINDOW_AUTOSIZE)
        
        # 主循环
        frame_count = 0
        last_inference_time = 0
        
        while True:
            # 创建测试场景
            img = self.create_test_scene()
            
            # 每5帧进行一次推理（保持流畅显示）
            if frame_count % 5 == 0:
                try:
                    _, inference_time = self.infer(img)
                    last_inference_time = inference_time
                except Exception as e:
                    print(f"Inference error: {e}")
                    last_inference_time = 0
            
            # 绘制推理信息
            img = self.draw_inference_info(img, last_inference_time)
            
            # 添加帧计数器
            cv2.putText(img, f"Frame: {frame_count}", (550, 460), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            # 显示图像
            cv2.imshow('YOLOv8 BPU Real-time Demo', img)
            frame_count += 1
            
            # 退出检测
            key = cv2.waitKey(30) & 0xFF
            if key == 27:  # ESC键
                break
        
        cv2.destroyAllWindows()
        self.print_final_stats()

    def run_camera_demo(self):
        """运行摄像头演示（如果可用）"""
        print("Trying camera...")
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            print("Camera not available, running demo mode instead...")
            self.run_simple_demo()
            return
        
        print("Camera found! Press ESC to quit")
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # 调整大小以提高性能
            frame = cv2.resize(frame, (640, 480))
            
            # 每10帧推理一次
            if frame_count % 10 == 0:
                try:
                    _, inference_time = self.infer(frame)
                except Exception as e:
                    print(f"Inference error: {e}")
                    inference_time = 0
            
            # 绘制信息
            frame = self.draw_inference_info(frame, inference_time)
            
            cv2.imshow('YOLOv8 BPU Camera Demo', frame)
            frame_count += 1
            
            if cv2.waitKey(30) & 0xFF == 27:
                break
        
        cap.release()
        cv2.destroyAllWindows()

    def print_final_stats(self):
        """打印最终统计"""
        if self.inference_times:
            times = np.array(self.inference_times)
            print("\n" + "="*50)
            print("YOLOv8 BPU Performance Statistics")
            print("="*50)
            print(f"Total inferences: {len(times)}")
            print(f"Average FPS: {self.current_fps}")
            print(f"Average inference time: {np.mean(times):.2f} ms")
            print(f"Min inference time: {np.min(times):.2f} ms")
            print(f"Max inference time: {np.max(times):.2f} ms")
            print(f"Standard deviation: {np.std(times):.2f} ms")
            print("="*50)


if __name__ == '__main__':
    try:
        gui = SimpleYOLOv8GUI()
        
        # 检查是否有摄像头
        import sys
        if len(sys.argv) > 1 and sys.argv[1] == 'camera':
            gui.run_camera_demo()
        else:
            gui.run_simple_demo()
            
    except KeyboardInterrupt:
        print("\nDemo stopped by user")
    except Exception as e:
        print(f"Error: {e}")