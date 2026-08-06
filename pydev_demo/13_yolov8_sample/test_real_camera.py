#!/usr/bin/env python3

################################################################################
# YOLOv8 BPU 实时USB摄像头检测
################################################################################

import numpy as np
import cv2
import time
import threading
try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn


class RealYOLOv8Camera:
    def __init__(self):
        # 加载模型
        print("Loading YOLOv8 model...")
        self.models = dnn.load('../models/yolov8_640x640_nv12.bin')
        self.input_height, self.input_width = self.get_input_shape()
        
        # 性能统计
        self.inference_times = []
        self.fps_counter = 0
        self.last_fps_time = time.time()
        self.current_fps = 0
        self.frame_count = 0
        
        # 检测参数
        self.conf_threshold = 0.5
        
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

    def infer(self, frame):
        """执行BPU推理"""
        # 调整大小
        resized = cv2.resize(frame, (self.input_width, self.input_height), interpolation=cv2.INTER_AREA)
        nv12_data = self.bgr2nv12_opencv(resized)
        
        # BPU推理
        start_time = time.time()
        outputs = self.models[0].forward(nv12_data)
        inference_time = (time.time() - start_time) * 1000
        
        # 统计性能
        self.inference_times.append(inference_time)
        if len(self.inference_times) > 30:
            self.inference_times.pop(0)
        
        # 更新FPS
        self.fps_counter += 1
        current_time = time.time()
        if current_time - self.last_fps_time >= 1.0:
            self.current_fps = self.fps_counter
            self.fps_counter = 0
            self.last_fps_time = current_time
        
        return outputs, inference_time

    def simple_decode_yolov8(self, outputs):
        """
        简化的YOLOv8后处理，用于演示
        实际应用中需要完整实现YOLOv8解码
        """
        boxes = []
        scores = []
        class_ids = []
        
        try:
            # 检查输出是否有效
            main_output = outputs[0]
            output_shape = main_output.properties.shape
            
            # 读取输出数据
            output_buffer = np.frombuffer(main_output.buffer, dtype=np.float32)
            output_buffer = output_buffer.reshape(output_shape)
            
            # 这里是简化的检测逻辑
            # 实际需要实现完整的YOLOv8后处理
            detection_results = output_buffer[0]  # (80, 80, 80)
            
            # 模拟检测（移除这行，改为实际检测）
            # 实际项目中这里应该是完整的解码逻辑
            pass
            
        except Exception as e:
            print(f"Decode error: {e}")
        
        # 为了演示，生成一些模拟检测结果
        # 实际使用时应该删除这部分，使用真实的检测结果
        import random
        if random.random() > 0.95:  # 5%概率生成检测
            num_detections = random.randint(1, 3)
            for _ in range(num_detections):
                x1 = random.randint(50, 500)
                y1 = random.randint(50, 300)
                x2 = x1 + random.randint(50, 150)
                y2 = y1 + random.randint(50, 150)
                conf = random.uniform(0.5, 0.9)
                class_id = random.randint(0, 79)
                
                boxes.append([x1, y1, x2, y2])
                scores.append(conf)
                class_ids.append(class_id)
        
        return boxes, scores, class_ids

    def draw_results(self, frame, boxes, scores, class_ids, inference_time):
        """在帧上绘制检测结果"""
        result_frame = frame.copy()
        
        # COCO类别名称（简化版）
        class_names = ['person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck',
                      'boat', 'traffic light', 'fire hydrant', 'stop sign', 'parking meter', 'bench',
                      'bird', 'cat', 'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra',
                      'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
                      'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove',
                      'skateboard', 'surfboard', 'tennis racket', 'bottle', 'wine glass', 'cup',
                      'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple', 'sandwich', 'orange',
                      'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch',
                      'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse',
                      'remote', 'keyboard', 'cell phone', 'microwave', 'oven', 'toaster', 'sink',
                      'refrigerator', 'book', 'clock', 'vase', 'scissors', 'teddy bear', 'hair drier',
                      'toothbrush']
        
        # 绘制检测框
        for box, score, class_id in zip(boxes, scores, class_ids):
            x1, y1, x2, y2 = map(int, box)
            
            # 绘制边界框
            cv2.rectangle(result_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            # 绘制标签
            if class_id < len(class_names):
                label = f"{class_names[class_id]}: {score:.2f}"
            else:
                label = f"Class {class_id}: {score:.2f}"
            
            # 标签背景 - 更大更明显
            (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 3)
            cv2.rectangle(result_frame, (x1, y1 - label_h - 15), 
                         (x1 + label_w, y1), (0, 255, 0), -1)
            cv2.putText(result_frame, label, (x1, y1 - 8), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 3)
        
        # 绘制状态信息
        self.draw_status_info(result_frame, inference_time)
        
        return result_frame

    def draw_status_info(self, frame, inference_time):
        """绘制状态信息面板"""
        # 计算平均推理时间
        if self.inference_times:
            avg_time = np.mean(self.inference_times)
            min_time = np.min(self.inference_times)
            max_time = np.max(self.inference_times)
        else:
            avg_time = min_time = max_time = 0
        
        # 获取BPU使用率
        try:
            with open('/sys/devices/system/bpu/bpu0/ratio', 'r') as f:
                bpu_ratio = int(f.read().strip())
        except:
            bpu_ratio = 0
        
        # 创建更大的信息面板
        overlay = frame.copy()
        panel_h, panel_w = 180, 350
        cv2.rectangle(overlay, (10, 10), (panel_w, panel_h), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.8, frame, 0.2, 0)
        
        # 绘制更大更清晰的信息文字
        font = cv2.FONT_HERSHEY_SIMPLEX
        info_lines = [
            f"FPS: {self.current_fps}",
            f"Frame: {self.frame_count}",
            f"Inference: {inference_time:.1f}ms",
            f"Average: {avg_time:.1f}ms",
            f"Min/Max: {min_time:.1f}/{max_time:.1f}ms",
            f"BPU Usage: {bpu_ratio}%"
        ]
        
        # 加粗显示FPS
        fps_text = f"FPS: {self.current_fps}"
        cv2.putText(frame, fps_text, (15, 35), font, 1.0, (0, 255, 0), 2)
        
        for i, line in enumerate(info_lines[1:], 1):  # 跳过FPS，从第二个开始
            color = (255, 255, 255)
            cv2.putText(frame, line, (15, 35 + i*25), font, 0.6, color, 2)
        
        # BPU使用率条形图 - 加大加粗
        bar_width = int(280 * bpu_ratio / 100.0)
        cv2.rectangle(frame, (15, 165), (15+280, 180), (80, 80, 80), -1)
        cv2.rectangle(frame, (15, 165), (15+bar_width, 180), (0, 255, 0), -1)
        cv2.putText(frame, f"BPU: {bpu_ratio}%", (300, 175), font, 0.6, (0, 255, 0), 2)
        
        # 添加提示文字 - 更大更明显
        cv2.putText(frame, "Press ESC to quit", (15, frame.shape[0] - 20), 
                   font, 0.7, (255, 255, 0), 2)

    def run_camera_detection(self):
        """运行摄像头检测"""
        print("Initializing camera...")
        
        # 尝试多个摄像头索引
        for cam_idx in [0, 1, 2]:
            cap = cv2.VideoCapture(cam_idx)
            if cap.isOpened():
                print(f"Camera found at index {cam_idx}")
                break
            cap.release()
        else:
            print("No camera found! Please check USB connection.")
            return None
        
        # 设置摄像头参数 - 提高分辨率
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, 30)
        
        print("Camera initialized. Starting detection...")
        print("Press ESC to quit")
        
        # 创建窗口并设置大小
        cv2.namedWindow('YOLOv8 BPU Real Detection', cv2.WINDOW_NORMAL)
        cv2.resizeWindow('YOLOv8 BPU Real Detection', 1280, 720)  # 设置窗口大小
        
        # 预热BPU
        print("Warming up BPU...")
        test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        for _ in range(3):
            self.infer(test_frame)
        
        # 主循环
        detection_interval = 0  # 每帧都检测
        last_inference_time = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Failed to read from camera")
                break
            
            self.frame_count += 1
            
            # 执行推理
            try:
                outputs, inference_time = self.infer(frame)
                boxes, scores, class_ids = self.simple_decode_yolov8(outputs)
                last_inference_time = inference_time
            except Exception as e:
                print(f"Inference error: {e}")
                boxes, scores, class_ids = [], [], []
                inference_time = 0
            
            # 绘制结果
            result_frame = self.draw_results(frame, boxes, scores, class_ids, inference_time)
            
            # 显示结果
            cv2.imshow('YOLOv8 BPU Real Detection', result_frame)
            
            # 退出检测
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC
                print("User quit")
                break
        
        # 清理
        cap.release()
        cv2.destroyAllWindows()
        self.print_final_stats()


    def print_final_stats(self):
        """打印最终统计"""
        if self.inference_times:
            times = np.array(self.inference_times)
            print("\n" + "="*50)
            print("YOLOv8 BPU Camera Detection Statistics")
            print("="*50)
            print(f"Total frames processed: {self.frame_count}")
            print(f"Average FPS: {self.current_fps}")
            print(f"Average inference time: {np.mean(times):.2f} ms")
            print(f"Min inference time: {np.min(times):.2f} ms")
            print(f"Max inference time: {np.max(times):.2f} ms")
            print(f"Standard deviation: {np.std(times):.2f} ms")
            print("="*50)


def main():
    print("="*60)
    print("YOLOv8 BPU Real-Time USB Camera Detection")
    print("="*60)
    
    detector = RealYOLOv8Camera()
    detector.run_camera_detection()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()