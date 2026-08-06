#!/usr/bin/env python3

import cv2
from dora import Node
import numpy as np
import pyarrow as pa
try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn
import ctypes
import json
import time

# ---------- ctypes 结构体定义 ----------

class hbSysMem_t(ctypes.Structure):
    _fields_ = [
        ("phyAddr", ctypes.c_double),
        ("virAddr", ctypes.c_void_p),
        ("memSize", ctypes.c_int)
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

# ---------- 加载后处理库 ----------

libpostprocess = ctypes.CDLL('/usr/lib/libpostprocess.so')
Yolov5doProcess = libpostprocess.Yolov5doProcess
Yolov5doProcess.argtypes = [hbDNNTensor_t, ctypes.POINTER(Yolov5PostProcessInfo_t), ctypes.c_int]
Yolov5doProcess.restype = ctypes.c_int

get_Postprocess_result = libpostprocess.Yolov5PostProcess
get_Postprocess_result.argtypes = [ctypes.POINTER(Yolov5PostProcessInfo_t)]
get_Postprocess_result.restype = ctypes.c_char_p


def get_TensorLayout(Layout):
    return int(2) if Layout == "NCHW" else int(0)


def bgr2nv12_opencv(image):
    """BGR -> NV12"""
    height, width = image.shape[0], image.shape[1]
    area = height * width
    yuv420p = cv2.cvtColor(image, cv2.COLOR_BGR2YUV_I420)
    flat = yuv420p.flatten()
    y = flat[:area]
    uv_planar = flat[area:].reshape((2, area // 4))
    nv12 = np.empty(area * 3 // 2, dtype=np.uint8)
    nv12[:area] = y
    nv12[area:] = uv_planar.T.flatten()
    return nv12


def preprocess(image, model_w=672, model_h=672):
    """预处理：resize + bgr2nv12，返回 (nv12_data, original_image)"""
    resized = cv2.resize(image, (model_w, model_h), interpolation=cv2.INTER_LINEAR)
    return bgr2nv12_opencv(resized)


def do_postprocess(outputs, output_tensors, post_info, model, tensor_layouts, has_scale):
    """对推理输出执行后处理，返回检测结果列表"""
    for i in range(len(model.outputs)):
        output_tensors[i].properties.tensorLayout = tensor_layouts[i]
        if not has_scale[i]:
            output_tensors[i].properties.quantiType = 0
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                ctypes.c_void_p)
        else:
            output_tensors[i].properties.quantiType = 2
            output_tensors[i].properties.scale.scaleData = (
                model.outputs[i].properties.scale_data
                .ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(
                outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
                ctypes.c_void_p)

        for j in range(len(model.outputs[i].properties.shape)):
            output_tensors[i].properties.validShape.dimensionSize[j] = \
                model.outputs[i].properties.shape[j]

        Yolov5doProcess(output_tensors[i], ctypes.pointer(post_info), i)

    result_str = get_Postprocess_result(ctypes.pointer(post_info)).decode('utf-8')
    try:
        if len(result_str) > 16:
            return json.loads(result_str[16:])
    except Exception as e:
        print(f"[ObjectDetection] 解析结果失败: {e}")
    return []


def draw_detections(image, detections, src_w, src_h, model_w=672, model_h=672):
    for det in detections:
        bbox = det['bbox']
        x1 = int(bbox[0] * src_w / model_w)
        y1 = int(bbox[1] * src_h / model_h)
        x2 = int(bbox[2] * src_w / model_w)
        y2 = int(bbox[3] * src_h / model_h)
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 1)
        cv2.putText(image, f'{det["name"]} {det["score"]:.2f}', (x1, max(y1 - 5, 0)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)


def main():
    print("[ObjectDetection] 启动YOLOv5检测节点")

    model_path = "/opt/hobot/model/x5/basic/yolov5s_672x672_nv12.bin"
    print(f"[ObjectDetection] 加载YOLOv5模型: {model_path}")
    model = dnn.load(model_path)[0]
    print(f"[ObjectDetection] ✅ 模型加载成功，输出数量: {len(model.outputs)}")

    post_info = Yolov5PostProcessInfo_t()
    post_info.height = 672
    post_info.width = 672
    post_info.ori_height = 480
    post_info.ori_width = 640
    post_info.score_threshold = 0.5
    post_info.nms_threshold = 0.45
    post_info.nms_top_k = 20
    post_info.is_pad_resize = 0

    output_tensors = (hbDNNTensor_t * len(model.outputs))()
    tensor_layouts = [get_TensorLayout(model.outputs[i].properties.layout)
                      for i in range(len(model.outputs))]
    has_scale = [len(model.outputs[i].properties.scale_data) > 0
                 for i in range(len(model.outputs))]

    node = Node("object_detection")
    frame_count = 0
    start_time = time.time()

    FRAME_W, FRAME_H = 640, 480
    EXPECTED_SIZE = FRAME_W * FRAME_H * 3
    VIS_W, VIS_H = 320, 240

    for event in node:
        if event["type"] != "INPUT" or event["id"] != "image":
            continue

        # ---------- 1. 图像解码 ----------
        image_array = event["value"]
        if not hasattr(image_array, 'to_numpy'):
            continue

        image_data = image_array.to_numpy(zero_copy_only=False).view(np.uint8)
        if image_data.size != EXPECTED_SIZE:
            if image_data.size < EXPECTED_SIZE:
                image_data = np.pad(image_data, (0, EXPECTED_SIZE - image_data.size))
            else:
                image_data = image_data[:EXPECTED_SIZE]
        current_image = image_data.reshape(FRAME_H, FRAME_W, 3)

        # ---------- 2. 预处理 ----------
        current_nv12 = preprocess(current_image)

        # ---------- 3. BPU 推理（同步）----------
        outputs = model.forward(current_nv12)

        # ---------- 4. 后处理 ----------
        detections = do_postprocess(
            outputs, output_tensors, post_info, model, tensor_layouts, has_scale
        )

        # ---------- 5. 可视化 ----------
        vis_image = cv2.resize(current_image, (VIS_W, VIS_H),
                               interpolation=cv2.INTER_NEAREST)
        if not vis_image.flags['WRITEABLE']:
            vis_image = vis_image.copy()
        draw_detections(vis_image, detections, src_w=VIS_W, src_h=VIS_H)

        frame_count += 1
        if frame_count % 30 == 0:
            fps = frame_count / (time.time() - start_time)
            print(f"[ObjectDetection] {frame_count:3d}帧 | FPS: {fps:5.1f} | 检测: {len(detections)}")

        # ---------- 6. 发送 ----------
        node.send_output(
            "image_vis",
            pa.array(vis_image.flatten(), type=pa.uint8()),
        )
        node.send_output(
            "bbox",
            pa.array([json.dumps(detections, ensure_ascii=False)], type=pa.string()),
        )


if __name__ == "__main__":
    main()
