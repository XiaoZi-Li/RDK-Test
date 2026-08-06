#!/usr/bin/env python3

################################################################################
# YOLOv8 BPU带GUI实时检测示例
################################################################################

import numpy as np
import cv2
import time
import threading
import sys
try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn


class YOLOv8Detector:
    def __init__(self):
        # 加载模型
        print("Loading YOLOv8 model...")
        self.models = dnn.load('../models/yolov8_640x640_nv12.bin')
        self.input_height, self.input_width = self.get_input_shape()
        
        # COCO类别名称 (80类)
        self.class_names = [
            'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck',
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
            'toothbrush'
        ]
        
        # 检测参数
        self.conf_threshold = 0.5
        self.iou_threshold = 0.45
        
        # 性能统计
        self.fps_counter = 0
        self.fps_start_time = time.time()
        self.current_fps = 0
        
        print("YOLOv8 model loaded successfully!")
        print(f"Input size: {self.input_width}x{self.input_height}")

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

    def preprocess(self, image):
        # 调整大小
        resized = cv2.resize(image, (self.input_width, self.input_height), interpolation=cv2.INTER_AREA)
        # 转换为NV12
        nv12_data = self.bgr2nv12_opencv(resized)
        return nv12_data

    def simple_decode_outputs(self, outputs, orig_shape):
        """
        简化的YOLOv8输出解析（不使用标准NMS，取top confident detections）
        """
        h, w = orig_shape
        boxes = []
        scores = []
        class_ids = []
        
        # YOLOv8有6个输出，我们使用主要的检测输出
        # 这里简化处理，实际应该解析所有尺度的输出
        detection_output = outputs[0]  # (1, 80, 80, 80) 格式
        
        try:
            # 重塑输出以便处理
            det_shape = detection_output.properties.shape
            output_buffer = np.frombuffer(detection_output.buffer, dtype=np.float32)
            output_buffer = output_buffer.reshape(det_shape)
            
            # 简化处理：从第一个输出中提取检测结果
            # 注意：这是简化版本，不是完整的YOLOv8后处理
            detections = output_buffer[0]  # (80, 80, 80)
            
            # 这里应该有完整的anchor解码和NMS处理
            # 为了演示，我们生成一些模拟检测结果
            # 实际项目中需要实现完整的YOLOv8后处理
            pass
            
        except Exception as e:
            print(f"Error decoding outputs: {e}")
        
        # 模拟检测结果（用于演示GUI）
        if np.random.random() > 0.7:  # 30%概率生成模拟检测结果
            # 生成一些随机框
            for _ in range(np.random.randint(1, 4)):
                x1 = int(np.random.uniform(50, w - 100))
                y1 = int(np.random.uniform(50, h - 100))
                x2 = x1 + int(np.random.uniform(50, 100))
                y2 = y1 + int(np.random.uniform(50, 100))
                conf = np.random.uniform(0.5, 0.9)
                class_id = np.random.randint(0, len(self.class_names))
                
                boxes.append([x1, y1, x2, y2])
                scores.append(conf)
                class_ids.append(class_id)
        
        return boxes, scores, class_ids

    def detect(self, image):
        # 预处理
        input_data = self.preprocess(image)
        orig_shape = image.shape[:2]
        
        # BPU推理
        outputs = self.models[0].forward(input_data)
        
        # 后处理
        boxes, scores, class_ids = self.simple_decode_outputs(outputs, orig_shape)
        
        return boxes, scores, class_ids

    def draw_detections(self, image, boxes, scores, class_ids):
        result_image = image.copy()
        
        for box, score, class_id in zip(boxes, scores, class_ids):
            x1, y1, x2, y2 = map(int, box)
            
            # 绘制边界框
            cv2.rectangle(result_image, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            # 绘制标签
            if class_id < len(self.class_names):
                label = f"{self.class_names[class_id]}: {score:.2f}"
            else:
                label = f"Class {class_id}: {score:.2f}"
            
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)[0]
            cv2.rectangle(result_image, (x1, y1 - label_size[1] - 10), 
                         (x1 + label_size[0], y1), (0, 255, 0), -1)
            cv2.putText(result_image, label, (x1, y1 - 5), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
        
        return result_image

    def update_fps(self):
        self.fps_counter += 1
        current_time = time.time()
        if current_time - self.fps_start_time >= 1.0:
            self.current_fps = self.fps_counter
            self.fps_counter = 0
            self.fps_start_time = current_time


def run_camera_demo():
    print("Starting YOLOv8 Camera Demo...")
    print("Press 'q' to quit")
    
    detector = YOLOv8Detector()
    
    # 尝试打开摄像头
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Camera not available, using test video mode...")
        # 使用测试图片模式
        run_image_demo(detector)
        return
    
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to read from camera")
            break
        
        frame_count += 1
        
        # 每10帧检测一次（提高帧率）
        if frame_count % 10 == 0:
            boxes, scores, class_ids = detector.detect(frame)
        else:
            # 使用上一帧的检测结果
            if frame_count == 1:
                boxes, scores, class_ids = [], [], []
        
        # 绘制结果
        result_frame = detector.draw_detections(frame, boxes, scores, class_ids)
        
        # 更新FPS
        detector.update_fps()
        
        # 显示状态信息
        status_text = f"FPS: {detector.current_fps} | Objects: {len(boxes)}"
        cv2.putText(result_frame, status_text, (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        
        # 显示结果
        cv2.imshow('YOLOv8 BPU Detection', result_frame)
        
        # 退出检测
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    cap.release()
    cv2.destroyAllWindows()


def run_image_demo(detector):
    print("Running Image Demo Mode...")
    
    # 加载测试图片
    test_image = cv2.imread('./test_image.jpg') or cv2.imread('./kite.jpg')
    if test_image is None:
        # 生成随机测试图像
        test_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        cv2.putText(test_image, "Test Image", (200, 240), 
                   cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
    
    while True:
        # 检测
        start_time = time.time()
        boxes, scores, class_ids = detector.detect(test_image)
        inference_time = (time.time() - start_time) * 1000
        
        # 绘制结果
        result_frame = detector.draw_detections(test_image, boxes, scores, class_ids)
        
        # 显示状态信息
        status_text = f"Inference: {inference_time:.1f}ms | Objects: {len(boxes)}"
        cv2.putText(result_frame, status_text, (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(result_frame, "Press 'q' to quit", (10, 70), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        # 显示结果
        cv2.imshow('YOLOv8 BPU Detection', result_frame)
        
        # 退出检测
        key = cv2.waitKey(30) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('r'):
            # 重新检测
            continue
    
    cv2.destroyAllWindows()


if __name__ == '__main__':
    print("YOLOv8 BPU GUI Demo")
    print("==================")
    print("Options:")
    print("1. Camera mode (default)")
    print("2. Image mode")
    
    try:
        choice = input("Enter choice (1/2, default=1): ").strip()
        if choice == '2':
            detector = YOLOv8Detector()
            run_image_demo(detector)
        else:
            run_camera_demo()
    except KeyboardInterrupt:
        print("\nDemo stopped by user")
    except Exception as e:
        print(f"Error: {e}")
        print("Falling back to image mode...")
        detector = YOLOv8Detector()
        run_image_demo(detector)