#!/usr/bin/env python3

import cv2
import dora
from dora import Node
import numpy as np
import pyarrow as pa
import time
try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn
import ctypes
import json

# ctypes结构体定义
class hbSysMem_t(ctypes.Structure):
    _fields_ = [
        ("phyAddr", ctypes.c_double),
        ("virAddr", ctypes.c_void_p),
        ("memSize", ctypes.c_int)
    ]

class hbDNNQuantiShift_yt(ctypes.Structure):
    _fields_ = [
        ("shiftLen", ctypes.c_int),
        ("shiftData", ctypes.c_char_p)
    ]

class hbDNNQuantiScale_t(ctypes.Structure):
    _fields_ = [
        ("scaleLen", ctypes.c_int),
        ("scaleData", ctypes.POINTER(ctypes.c_float)),
        ("zeroPointLen", ctypes.c_int),
        ("zeroPointData", ctypes.c_char_p)
    ]

class hbDNNTensorShape_t(ctypes.Structure):
    _fields_ = [
        ("dimensionSize", ctypes.c_int * 8),
        ("numDimensions", ctypes.c_int)
    ]

class hbDNNTensorProperties_t(ctypes.Structure):
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
    _fields_ = [
        ("sysMem", hbSysMem_t * 4),
        ("properties", hbDNNTensorProperties_t)
    ]

class Yolov5PostProcessInfo_t(ctypes.Structure):
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

# 加载后处理库
libpostprocess = ctypes.CDLL('/usr/lib/libpostprocess.so')
Yolov5doProcess = libpostprocess.Yolov5doProcess
Yolov5doProcess.argtypes = [hbDNNTensor_t, ctypes.POINTER(Yolov5PostProcessInfo_t), ctypes.c_int]
Yolov5doProcess.restype = ctypes.c_int

get_Postprocess_result = libpostprocess.Yolov5PostProcess
get_Postprocess_result.argtypes = [ctypes.POINTER(Yolov5PostProcessInfo_t)]
get_Postprocess_result.restype = ctypes.c_char_p

def get_TensorLayout(Layout):
    if Layout == "NCHW":
        return int(2)
    else:
        return int(0)

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

def main():
    print("[Detector] 启动检测节点")
    
    # 加载YOLOv10模型 (更小更快)
    model_path = "/opt/hobot/model/x5/basic/yolov10_640x640_nv12.bin"
    print(f"[Detector] 加载YOLOv5模型: {model_path}")
    model = dnn.load(model_path)[0]
    print(f"[Detector] ✅ 模型加载成功，输出数量: {len(model.outputs)}")
    
    node = Node("detector")
    frame_count = 0
    start_time = time.time()
    
    # 初始化后处理信息
    post_info = Yolov5PostProcessInfo_t()
    post_info.height = 640
    post_info.width = 640
    post_info.ori_height = 480
    post_info.ori_width = 640
    post_info.score_threshold = 0.5
    post_info.nms_threshold = 0.45
    post_info.nms_top_k = 20
    post_info.is_pad_resize = 0
    
    # 预分配输出张量数组
    output_tensors = (hbDNNTensor_t * len(model.outputs))()
    
    try:
        for event in node:
            if event["type"] == "INPUT":
                if event["id"] == "image":
                    # 重构图像数据
                    image_data = event["value"].to_numpy()
                    height = event["metadata"]["height"]
                    width = event["metadata"]["width"]
                    channels = event["metadata"]["channels"]
                    
                    # 从展平的数据重构图像
                    image = image_data.reshape(height, width, channels)
                    
                    # 调整图像大小以适应模型输入，使用更快的插值方法
                    resized_image = cv2.resize(image, (640, 640), interpolation=cv2.INTER_LINEAR)
                    
                    # 转换为NV12格式
                    nv12_data = bgr2nv12_opencv(resized_image)
                    
                    # BPU推理
                    inference_start = time.time()
                    outputs = model.forward(nv12_data)
                    inference_time = (time.time() - inference_start) * 1000  # 转换为毫秒
                    
                    # 后处理
                    for i in range(len(model.outputs)):
                        # 设置张量属性
                        output_tensors[i].properties.tensorLayout = get_TensorLayout(model.outputs[i].properties.layout)
                        
                        if len(model.outputs[i].properties.scale_data) == 0:
                            output_tensors[i].properties.quantiType = 0
                            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), 
                                ctypes.c_void_p)
                        else:
                            output_tensors[i].properties.quantiType = 2
                            output_tensors[i].properties.scale.scaleData = model.outputs[i].properties.scale_data.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)), 
                                ctypes.c_void_p)
                        
                        # 设置维度信息
                        for j in range(len(model.outputs[i].properties.shape)):
                            output_tensors[i].properties.validShape.dimensionSize[j] = model.outputs[i].properties.shape[j]
                        
                        # 执行后处理
                        Yolov5doProcess(output_tensors[i], ctypes.pointer(post_info), i)
                    
                    # 获取后处理结果
                    result_str = get_Postprocess_result(ctypes.pointer(post_info))
                    result_str = result_str.decode('utf-8')
                    
                    # 解析检测结果
                    detections = []
                    try:
                        if len(result_str) > 16:  # 跳过前16个字符的头部信息
                            data = json.loads(result_str[16:])
                            detections = data
                    except Exception as e:
                        print(f"[Detector] 解析结果失败: {e}")
                    
                    # 优化：只在有检测结果时才绘制检测框，减少处理开销
                    image_with_boxes = image.copy()
                    if len(detections) > 0:
                        for detection in detections:
                            bbox = detection['bbox']
                            score = detection['score']
                            name = detection['name']
                            
                            # 绘制边界框
                            x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
                            cv2.rectangle(image_with_boxes, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            
                            # 绘制标签
                            label = f'{name} {score:.2f}'
                            cv2.putText(image_with_boxes, label, (x1, y1 - 10), 
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    
                    # 发送结果
                    flattened_result = image_with_boxes.flatten()
                    result_metadata = {
                        "height": image_with_boxes.shape[0],
                        "width": image_with_boxes.shape[1],
                        "channels": image_with_boxes.shape[2],
                        "inference_time": inference_time,
                        "detection_count": len(detections)
                    }
                    
                    node.send_output(
                        "result",
                        pa.array(flattened_result),
                        result_metadata
                    )
                    
                    frame_count += 1
                    
                    # 每50帧输出一次性能信息（进一步减少输出频率以提高性能）
                    if frame_count % 50 == 0:
                        current_time = time.time()
                        fps = frame_count / (current_time - start_time)
                        print(f"[Detector] {frame_count:3d}帧 | FPS: {fps:5.1f} | 推理: {inference_time:5.1f}ms | 检测: {len(detections)}")
                    
    except KeyboardInterrupt:
        print("[Detector] 用户中断")
    except Exception as e:
        print(f"[Detector] 错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()