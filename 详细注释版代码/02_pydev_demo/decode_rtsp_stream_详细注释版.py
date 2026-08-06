#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decode_rtsp_stream.py - RTSP流解码与实时目标检测系统
================================================================================

【程序功能】
本程序实现了一个完整的RTSP视频流实时处理系统，包含以下功能：
1. RTSP流接收与解码（支持H.264/H.265/MJPEG）
2. 视频图像处理与格式转换
3. 实时目标检测（使用FCOS模型）
4. 检测结果通过HDMI实时显示

【系统架构】
程序采用多线程并行架构，提高处理效率：

┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  DecodeThread   │────▶│  DisplayThread   │────▶│   HDMI显示       │
│  (RTSP解码)     │     │  (VPS处理)       │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                                               │
         │              ┌─────────────────┐               │
         └─────────────▶│  InferenceThread│◀──────────────┘
                        │  (AI推理)       │
                        └─────────────────┘

【线程说明】
1. DecodeThread：负责从RTSP流接收视频数据并解码为NV12格式
2. DisplayThread：负责图像处理（VPS）和HDMI显示
3. InferenceThread：负责AI推理和检测结果绘制

【运行方式】
# 基本用法（仅显示）
python3 decode_rtsp_stream.py

# 指定RTSP URL
python3 decode_rtsp_stream.py -u rtsp://127.0.0.1/1080P_test.h264

# 启用AI推理（必须同时启用显示）
python3 decode_rtsp_stream.py -u rtsp://127.0.0.1/1080P_test.h264 -a

# 多路RTSP流
python3 decode_rtsp_stream.py -u "rtsp://url1;rtsp://url2"

【参数说明】
-u, --rtsp_url: RTSP流地址，多个用分号分隔
-d: 是否启用显示（1=启用，0=禁用）
-a: 是否启用AI推理（启用时会自动开启显示）

================================================================================
"""

import sys
import os
import signal
import getopt
import numpy as np
import cv2
import colorsys
from time import time
from time import sleep
import threading
from queue import Queue
import multiprocessing
from threading import BoundedSemaphore

try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn
try:
    from hobot_vio import libsrcampy as srcampy
except ImportError:
    from hobot_vio_rdkx5 import libsrcampy as srcampy

import ctypes
import json


output_tensors = None

fcos_postprocess_info = None


# ================================================================================
# C结构体定义
# ================================================================================

class hbSysMem_t(ctypes.Structure):
    """BPU系统内存结构体"""
    _fields_ = [
        ("phyAddr",ctypes.c_double),
        ("virAddr",ctypes.c_void_p),
        ("memSize",ctypes.c_int)
    ]

class hbDNNQuantiShift_yt(ctypes.Structure):
    """量化位移参数"""
    _fields_ = [
        ("shiftLen",ctypes.c_int),
        ("shiftData",ctypes.c_char_p)
    ]

class hbDNNQuantiScale_t(ctypes.Structure):
    """量化比例参数"""
    _fields_ = [
        ("scaleLen",ctypes.c_int),
        ("scaleData",ctypes.POINTER(ctypes.c_float)),
        ("zeroPointLen",ctypes.c_int),
        ("zeroPointData",ctypes.c_char_p)
    ]

class hbDNNTensorShape_t(ctypes.Structure):
    """张量形状结构体"""
    _fields_ = [
        ("dimensionSize",ctypes.c_int * 8),
        ("numDimensions",ctypes.c_int)
    ]

class hbDNNTensorProperties_t(ctypes.Structure):
    """张量属性结构体"""
    _fields_ = [
        ("validShape",hbDNNTensorShape_t),
        ("alignedShape",hbDNNTensorShape_t),
        ("tensorLayout",ctypes.c_int),
        ("tensorType",ctypes.c_int),
        ("shift",hbDNNQuantiShift_yt),
        ("scale",hbDNNQuantiScale_t),
        ("quantiType",ctypes.c_int),
        ("quantizeAxis", ctypes.c_int),
        ("alignedByteSize",ctypes.c_int),
        ("stride",ctypes.c_int * 8)
    ]

class hbDNNTensor_t(ctypes.Structure):
    """BPU张量结构体"""
    _fields_ = [
        ("sysMem",hbSysMem_t * 4),
        ("properties",hbDNNTensorProperties_t)
    ]


class FcosPostProcessInfo_t(ctypes.Structure):
    """FCOS后处理参数结构体"""
    _fields_ = [
        ("height",ctypes.c_int),
        ("width",ctypes.c_int),
        ("ori_height",ctypes.c_int),
        ("ori_width",ctypes.c_int),
        ("score_threshold",ctypes.c_float),
        ("nms_threshold",ctypes.c_float),
        ("nms_top_k",ctypes.c_int),
        ("is_pad_resize",ctypes.c_int)
    ]


# ================================================================================
# 全局变量和后处理库加载
# ================================================================================

libpostprocess = ctypes.CDLL('/usr/lib/libpostprocess.so')

get_Postprocess_result = libpostprocess.FcosPostProcess
get_Postprocess_result.argtypes = [ctypes.POINTER(FcosPostProcessInfo_t)]
get_Postprocess_result.restype = ctypes.c_char_p

is_stop = False  # 全局停止标志

# ================================================================================
# 辅助函数
# ================================================================================

def get_TensorLayout(Layout):
    """Layout字符串转换为BPU内部整数值"""
    if Layout == "NCHW":
        return int(2)
    else:
        return int(0)

def get_display_res():
    """
    获取HDMI显示分辨率

    【返回值】
        (disp_w, disp_h): 显示分辨率
    """
    if os.path.exists("/usr/bin/get_hdmi_res") == False:
        return 1920, 1080

    import subprocess
    p = subprocess.Popen(["/usr/bin/get_hdmi_res"], stdout=subprocess.PIPE)
    result = p.communicate()
    res = result[0].split(b',')
    res[1] = max(min(int(res[1]), 1920), 0)
    res[0] = max(min(int(res[0]), 1080), 0)
    return int(res[1]), int(res[0])

disp_w, disp_h = get_display_res()

def print_properties(pro):
    """打印Tensor属性"""
    print("tensor type:", pro.tensor_type)
    print("data type:", pro.dtype)
    print("layout:", pro.layout)
    print("shape:", pro.shape)


def get_hw(pro):
    """从Tensor属性中获取高度和宽度"""
    if pro.layout == "NCHW":
        return pro.shape[2], pro.shape[3]
    else:
        return pro.shape[1], pro.shape[2]

def get_classes():
    """获取COCO数据集80类目标名称"""
    return np.array([
        "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
        "truck", "boat", "traffic light", "fire hydrant", "stop sign",
        "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
        "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
        "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
        "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
        "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
        "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
        "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
        "couch", "potted plant", "bed", "dining table", "toilet", "tv",
        "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
        "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
        "scissors", "teddy bear", "hair drier", "toothbrush"
    ])


# ================================================================================
# 多线程推理执行器
# ================================================================================

class ParallelExector(object):
    """
    并行推理执行器

    【功能】
        使用多进程池并行执行后处理任务，提高系统吞吐量
    """
    def __init__(self, parallel_num=4):
        self.parallel_num = parallel_num
        if parallel_num != 1:
            self._pool = multiprocessing.Pool(processes=self.parallel_num,
                                              maxtasksperchild=5)
            self.workers = BoundedSemaphore(self.parallel_num)

    def infer(self, output):
        """提交推理任务"""
        if self.parallel_num == 1:
            run(output)
        else:
            self.workers.acquire()
            self._pool.apply_async(func=run,
                                   args=(output, ),
                                   callback=self.task_done,
                                   error_callback=print)

    def task_done(self, *args, **kwargs):
        """任务完成回调，释放信号量"""
        self.workers.release()

    def close(self):
        """关闭进程池"""
        if hasattr(self, "_pool"):
            self._pool.close()
            self._pool.join()


# ================================================================================
# 目标检测后处理函数
# ================================================================================

def scale_bbox(bbox, input_w, input_h, output_w, output_h):
    """
    边界框坐标缩放

    【功能】
        将模型输出的边界框坐标缩放到显示分辨率
    """
    scale_x = output_w / input_w
    scale_y = output_h / input_h

    x1 = int(bbox[0] * scale_x)
    y1 = int(bbox[1] * scale_y)
    x2 = int(bbox[2] * scale_x)
    y2 = int(bbox[3] * scale_y)

    return [x1, y1, x2, y2]


def limit_display_cord(coor):
    """
    限制坐标在显示范围内

    【功能】
        确保边界框不会超出屏幕边界
    """
    coor[0] = max(min(disp_w, coor[0]), 0)
    coor[1] = max(min(disp_h, coor[1]), 2)  # 留出文字显示空间
    coor[2] = max(min(disp_w, coor[2]), 0)
    coor[3] = max(min(disp_h, coor[3]), 0)
    return coor


def run(outputs):
    """
    FCOS后处理和结果绘制函数

    【功能】
        1. 执行FCOS后处理
        2. 在HDMI上绘制检测结果
    """
    strides = [8, 16, 32, 64, 128]
    for i in range(len(strides)):
        if (output_tensors[i].properties.quantiType == 0):
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(outputs[i].ctypes.data_as(ctypes.POINTER(ctypes.c_float)), ctypes.c_void_p)
            output_tensors[i + 5].sysMem[0].virAddr = ctypes.cast(outputs[i + 5].ctypes.data_as(ctypes.POINTER(ctypes.c_float)), ctypes.c_void_p)
            output_tensors[i + 10].sysMem[0].virAddr = ctypes.cast(outputs[i + 10].ctypes.data_as(ctypes.POINTER(ctypes.c_float)), ctypes.c_void_p)
        else:
            output_tensors[i].sysMem[0].virAddr = ctypes.cast(outputs[i].ctypes.data_as(ctypes.POINTER(ctypes.c_int32)), ctypes.c_void_p)
            output_tensors[i + 5].sysMem[0].virAddr = ctypes.cast(outputs[i + 5].ctypes.data_as(ctypes.POINTER(ctypes.c_int32)), ctypes.c_void_p)
            output_tensors[i + 10].sysMem[0].virAddr = ctypes.cast(outputs[i + 10].ctypes.data_as(ctypes.POINTER(ctypes.c_int32)), ctypes.c_void_p)

        libpostprocess.FcosdoProcess(output_tensors[i], output_tensors[i + 5], output_tensors[i + 10], ctypes.pointer(fcos_postprocess_info), i)

    result_str = get_Postprocess_result(ctypes.pointer(fcos_postprocess_info))
    result_str = result_str.decode('utf-8')

    data = json.loads(result_str[14:])

    for index, result in enumerate(data):
        bbox = result['bbox']
        score = result['score']
        id = int(result['id'])
        name = result['name']

        bbox = scale_bbox(bbox, 512, 512, disp_w, disp_h)
        coor = limit_display_cord(bbox)
        coor = [round(i) for i in coor]
        score = float(score)
        bbox_string = '%s: %.2f' % (name, score)
        bbox_string = bbox_string.encode('gb2312')

        box_color = colors[id]
        color_base = 0xFF000000
        box_color_ARGB = color_base | (box_color[0]) << 16 | (box_color[1]) << 8 | (box_color[2])

        # 在HDMI上绘制检测框和文字
        if index == 0:
            disp.set_graph_rect(coor[0], coor[1], coor[2], coor[3], 3, 1, box_color_ARGB)
            disp.set_graph_word(coor[0], coor[1] - 2, bbox_string, 3, 1, box_color_ARGB)
        else:
            disp.set_graph_rect(coor[0], coor[1], coor[2], coor[3], 3, 0, box_color_ARGB)
            disp.set_graph_word(coor[0], coor[1] - 2, bbox_string, 3, 0, box_color_ARGB)


# ================================================================================
# H.264/H.265 NAL单元解析
# ================================================================================

def get_nalu_pos(byte_stream):
    """
    解析H.264/H.265码流中的NAL单元位置

    【参数】
        byte_stream: 原始码流数据

    【返回值】
        NAL单元位置列表 [(start, end, is4bytes, fb, nri, type), ...]
    """
    size = byte_stream.__len__()
    nals = []
    retnals = []

    startCodePrefixShort = b"\x00\x00\x01"

    pos = 0
    while pos < size:
        is4bytes = False
        retpos = byte_stream.find(startCodePrefixShort, pos)
        if retpos == -1:
            break
        if byte_stream[retpos - 1] == 0:
            retpos -= 1
            is4bytes = True
        if is4bytes:
            pos = retpos + 4
        else:
            pos = retpos + 3
        val = hex(byte_stream[pos])
        val = "{:d}".format(byte_stream[pos], 4)
        val = int(val)
        fb = (val >> 7) & 0x1
        nri = (val >> 5) & 0x3
        type = val & 0x1f
        nals.append((pos, is4bytes, fb, nri, type))

    for i in range(0, len(nals) - 1):
        start = nals[i][0]
        if nals[i + 1][1]:
            end = nals[i + 1][0] - 5
        else:
            end = nals[i + 1][0] - 4
        retnals.append((start, end, nals[i][1], nals[i][2], nals[i][3], nals[i][4]))

    start = nals[-1][0]
    end = byte_stream.__len__() - 1
    retnals.append((start, end, nals[-1][1], nals[-1][2], nals[-1][3], nals[-1][4]))
    return retnals

def get_h264_nalu_type(byte_stream):
    """获取H.264码流的NAL单元类型列表"""
    nalu_types = []
    nalu_pos = get_nalu_pos(byte_stream)

    for idx, (start, end, is4bytes, fb, nri, type) in enumerate(nalu_pos):
        nalu_types.append(type)

    return nalu_types


# ================================================================================
# 编码格式检测
# ================================================================================

def fourcc_int_to_string(fourcc):
    """将FourCC整数转换为字符串"""
    try:
        return bytes([
            fourcc & 0xFF,
            (fourcc >> 8) & 0xFF,
            (fourcc >> 16) & 0xFF,
            (fourcc >> 24) & 0xFF
        ]).decode('ascii').lower()
    except UnicodeDecodeError:
        return 'unknown'

def detect_codec_via_nal_units(byte_stream):
    """
    通过解析NAL单元检测编码类型

    【返回值】
        'h264' 或 'h265'
    """
    start_code_prefix_short = b"\x00\x00\x01"
    start_code_prefix_long = b"\x00\x00\x00\x01"
    pos = 0

    while pos < len(byte_stream):
        short_pos = byte_stream.find(start_code_prefix_short, pos)
        long_pos = byte_stream.find(start_code_prefix_long, pos)

        if short_pos == -1 and long_pos == -1:
            break

        if long_pos != -1 and (short_pos == -1 or long_pos < short_pos):
            start = long_pos
            nalu_start = start + 4
        else:
            start = short_pos
            nalu_start = start + 3

        if nalu_start >= len(byte_stream):
            break

        first_byte = byte_stream[nalu_start]

        # H.265检测
        nal_type_h265 = (first_byte >> 1) & 0x3F
        if 32 <= nal_type_h265 <= 34:
            return 'h265'

        # H.264检测
        nal_type_h264 = first_byte & 0x1F
        if nal_type_h264 in [7, 8]:
            return 'h264'

        pos = nalu_start + 1

    return 'h264'


# ================================================================================
# RTSP流解码线程
# ================================================================================

class DecodeRtspStream(threading.Thread):
    """
    RTSP流解码线程

    【功能】
        1. 连接RTSP流
        2. 自动检测编码格式（H.264/H.265/MJPEG）
        3. 解码视频流为NV12格式
        4. 将解码后的帧放入队列供其他线程使用
    """
    def __init__(self, rtsp_url):
        threading.Thread.__init__(self)
        self.rtsp_url = rtsp_url
        self.is_running = True
        self.frame_queue = Queue(maxsize=2)  # 限制队列大小，防止内存占用过大
        self.stabilization_complete = False

    def open(self, dec_chn=0, dec_type=1):
        """
        打开RTSP流并初始化解码器

        【参数】
            dec_chn: 解码通道号
            dec_type: 解码类型（1=H.264, 2=H.265, 3=MJPEG）

            【返回值】
                0=成功，其他=失败
        """
        self.dec_chn = dec_chn
        self.dec_type = dec_type
        cap = cv2.VideoCapture(self.rtsp_url)
        cap.set(cv2.CAP_PROP_FORMAT, -1)

        if not cap.isOpened():
            print("fail to open rtsp: {}".format(self.rtsp_url))
            return -1
        self.cap = cap

        # 自动检测编码格式
        fourcc_int = int(self.cap.get(cv2.CAP_PROP_FOURCC))
        fourcc_str = fourcc_int_to_string(fourcc_int)

        if fourcc_str in ['h264', 'hevc', 'h265', 'mjpg']:
            if fourcc_str == 'h264':
                dec_type = 1
            elif fourcc_str in ['hevc', 'h265']:
                dec_type = 2
            elif fourcc_str == 'mjpg':
                dec_type = 3
            print(f"Encoding detected via FourCC: {fourcc_str}, dec_type: {dec_type}")
        else:
            # 手动解析NAL单元
            ret, stream_frame = self.cap.read()
            if not ret:
                print("Failed to read frame, unable to detect encoding.")
                return -1

            codec_type = detect_codec_via_nal_units(stream_frame.tobytes())
            if codec_type == 'h264':
                dec_type = 1
            elif codec_type == 'h265':
                dec_type = 2
            else:
                print("Unsupported encoding type.")
                return -1

            print(f"Encoding detected via NAL unit: {codec_type}, dec_type: {dec_type}")

            # 重置VideoCapture
            self.cap.release()
            self.cap = cv2.VideoCapture(self.rtsp_url)
            self.cap.set(cv2.CAP_PROP_FORMAT, -1)
            if not self.cap.isOpened():
                print("Failed to reopen RTSP stream.")
                return -1

        self.dec_type = dec_type

        print("RTSP stream frame_width:{:.0f}, frame_height:{:.0f}"
              .format(cap.get(cv2.CAP_PROP_FRAME_WIDTH),
                      cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # 初始化解码器
        self.dec = srcampy.Decoder()
        ret = self.dec.decode("", dec_chn, dec_type, self.width, self.height)
        print("Decoder(%d, %d) return:%d frame count: %d" %(dec_chn, dec_type, ret[0], ret[1]))

        return ret[0]

    def close(self):
        """关闭解码线程"""
        self.is_running = False
        self.join()
        self.dec.close()
        self.cap.release()

    def run(self):
        """主循环：读取视频帧并解码"""
        global is_stop
        start_time = time()
        image_count = 0
        skip_count = 0
        find_pps_sps = 0
        stabilization_count = 80
        self.stabilization_complete = False

        while not is_stop:
            ret, stream_frame = self.cap.read()

            if not ret:
                # 连接断开时尝试重连
                self.dec.close()
                self.cap.release()
                ret = self.open(self.dec_chn, self.dec_type)
                if ret != 0:
                    return ret
                start_time = time()
                image_count = 0
                skip_count = 0
                find_pps_sps = 0
                continue

            # 获取NAL单元类型
            nalu_types = get_h264_nalu_type(stream_frame.tobytes())

            # 确保首帧是关键帧（包含SPS/PPS）
            if (nalu_types[0] in [1, 5]) and find_pps_sps == 0:
                continue

            if find_pps_sps == 0:
                find_pps_sps = 1
                print("Found keyframe parameters, starting stabilization period")

            if stream_frame is not None:
                ret = self.dec.set_img(stream_frame.tobytes(), self.dec_chn)
                if ret != 0:
                    return ret

                # 跳过前8帧（解码器启动期）
                if skip_count < 8:
                    skip_count += 1
                    continue

                frame = self.dec.get_img()

                if frame is not None:
                    # 等待解码器稳定
                    if not self.stabilization_complete:
                        if stabilization_count > 0:
                            stabilization_count -= 1
                            if stabilization_count % 10 == 0:
                                print(f"Stabilization in progress: {stabilization_count} frames remaining")
                        else:
                            self.stabilization_complete = True
                            print("Stabilization complete, starting normal processing")

                    # 稳定期结束后，将帧放入队列
                    if self.stabilization_complete:
                        if not self.frame_queue.full():
                            self.frame_queue.put(frame)

            # FPS计算
            if self.stabilization_complete:
                image_count += 1
                current_time = time()
                elapsed = current_time - start_time
                if elapsed >= 3.0:
                    fps = image_count / elapsed
                    print(f"Decode CHAN: {self.dec_chn} FPS: {fps:.2f}")
                    start_time = current_time
                    image_count = 0

    def get_frame(self):
        """从队列获取解码后的帧"""
        if (self.frame_queue.empty() == True) and (not self.stabilization_complete):
            return None
        return self.frame_queue.get()


# ================================================================================
# 视频显示线程
# ================================================================================

class VideoDisplay(threading.Thread):
    """
    视频显示线程

    【功能】
        1. 从解码线程获取帧
        2. 使用VPS进行图像处理（缩放、格式转换）
        3. 通过HDMI显示
    """
    def __init__(self, streamer, vps_group):
        threading.Thread.__init__(self)
        self.streamer = streamer
        self.vps_group = vps_group
        self.frame_queue = Queue(maxsize=2)
        self.is_running = True
        global disp_w, disp_h

        # 获取HDMI显示对象
        self.disp = srcampy.Display()
        resolution_list = self.disp.get_display_res()

        if (disp_w, disp_h) in resolution_list:
            print(f"Resolution {disp_w}x{disp_h} exists in the list.")
        else:
            print(f"Resolution {disp_w}x{disp_h} does not exist in the list.")
            for res in resolution_list:
                if res[0] == 0 | res[1] == 0:
                    break
                disp_w = res[0]
                disp_h = res[1]

        self.disp.display(0, disp_w, disp_h)
        self.disp.display(3, disp_w, disp_h)  # 用于OSD叠加

        # 启动VPS
        self.vps = srcampy.Camera()
        ret = self.vps.open_vps(self.vps_group, 1, self.streamer.width, self.streamer.height,
                                [1920, 512, disp_w], [1080, 512, disp_h])
        print("Camera vps return:%d" % ret)

        # 绑定VPS和显示，实现硬件级联
        srcampy.bind(self.vps, self.disp)

    def close(self):
        """关闭显示线程"""
        self.is_running = False
        self.join()
        print("dis stop success")
        self.disp.close()
        self.vps.close_cam()
        srcampy.unbind(self.vps, self.disp)


    def run(self):
        """主循环：获取帧并显示"""
        global is_stop
        disp_start_time = time()
        disp_image_count = 0

        while not is_stop:
            frame = self.streamer.get_frame()
            if frame is None:
                sleep(0.01)
                continue

            self.vps.set_img(frame)

            if self.frame_queue.full() == False:
                sleep(0.001)  # 必要的延时
                nv12_img = self.vps.get_img(2, 512, 512)
                self.frame_queue.put(nv12_img)

            disp_finish_time = time()
            disp_image_count += 1
            if disp_finish_time - disp_start_time > 3:
                print("Display FPS: {:.2f}".format(disp_image_count / (disp_finish_time - disp_start_time)))
                disp_start_time = disp_finish_time
                disp_image_count = 0

        self.disp.close()

    def get_frame(self):
        """从队列获取处理后的帧"""
        if self.frame_queue.empty() == True:
            return None
        return self.frame_queue.get()


# ================================================================================
# AI推理线程
# ================================================================================

class AiInference(threading.Thread):
    """
    AI推理线程

    【功能】
        1. 从显示线程获取帧
        2. 执行目标检测推理（FCOS）
        3. 并行执行后处理
    """
    def __init__(self, video_display, models):
        threading.Thread.__init__(self)
        self.video_display = video_display
        self.models = models

    def close(self):
        """关闭推理线程"""
        pass


    def run(self):
        """主循环：执行AI推理"""
        parallel_exe = ParallelExector()
        global is_stop
        ai_start_time = time()
        ai_image_count = 0

        while not is_stop:
            img = self.video_display.get_frame()
            if img is None:
                sleep(0.02)
                continue

            # 转换为numpy数组
            img = np.frombuffer(img, dtype=np.uint8)

            # 执行推理
            outputs = self.models[0].forward(img)

            # 准备输出数据
            output_array = []
            for item in outputs:
                output_array.append(item.buffer)

            # 并行执行后处理
            parallel_exe.infer(output_array)

            ai_finish_time = time()
            ai_image_count += 1
            if ai_finish_time - ai_start_time > 3:
                print("AI FPS: {:.2f}".format(ai_image_count / (ai_finish_time - ai_start_time)))
                ai_start_time = ai_finish_time
                ai_image_count = 0


# ================================================================================
# 信号处理器
# ================================================================================

def signal_handler(sig, frame):
    """处理Ctrl+C信号，优雅退出"""
    print("Ctrl+C received. Closing app.")
    global is_stop
    is_stop = True


# ================================================================================
# 主程序入口
# ================================================================================

if __name__ == '__main__':
    rtsp_urls = ["rtsp://127.0.0.1/1080P_test.h264"]

    enable_display = 1
    enable_ai_inference = 0

    signal.signal(signal.SIGINT, signal_handler)

    # 解析命令行参数
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hu:d:a", ["rtsp_url="])
    except getopt.GetoptError:
        print('./decode_rtsp_stream.py [-u <rtsp_url>] [-d] [-a]')
        print('./decode_rtsp_stream.py [-u <rtsp_url;rtsp_url2>] [-d] [-a]')
        sys.exit(2)

    for opt, arg in opts:
        if opt == '-h':
            print('./decode_rtsp_stream.py [-u <rtsp_url>] [-d] [-a]')
            sys.exit()
        elif opt in ("-u", "--rtsp_url"):
            rtsp_urls = arg.split(";")
        elif opt in ("-d"):
            enable_display = int(arg)
        elif opt in ("-a"):
            enable_display = 1  # AI推理需要显示
            enable_ai_inference = 1

    print(rtsp_urls)

    # ==========================================================================
    # 启动RTSP流解码
    # ==========================================================================
    vdec_chan = 0
    rtsp_streams = []

    for rtsp_url in rtsp_urls:
        rtsp_stream = DecodeRtspStream(rtsp_url)
        ret = rtsp_stream.open(vdec_chan)
        if ret != 0:
            quit(ret)
        rtsp_stream.start()
        rtsp_streams.append(rtsp_stream)
        vdec_chan += 1

    # ==========================================================================
    # 启动视频显示
    # ==========================================================================
    if enable_display == 1:
        video_display = VideoDisplay(rtsp_streams[0], 1)
        video_display.start()

    # ==========================================================================
    # 启动AI推理
    # ==========================================================================
    if enable_ai_inference == 1:
        # 准备颜色表
        classes = get_classes()
        num_classes = len(classes)
        hsv_tuples = [(1.0 * x / num_classes, 1., 1.) for x in range(num_classes)]
        colors = list(map(lambda x: colorsys.hsv_to_rgb(*x), hsv_tuples))
        colors = list(
            map(lambda x: (int(x[0] * 255), int(x[1] * 255), int(x[2] * 255)),
                colors))

        global disp
        disp = video_display.disp

        # 加载FCOS模型
        models = dnn.load('../models/fcos_512x512_nv12.bin')

        h, w = get_hw(models[0].inputs[0].properties)
        input_shape = (h, w)

        for output in models[0].outputs:
            print_properties(output.properties)

        # 配置后处理参数
        global fcos_postprocess_info
        fcos_postprocess_info = FcosPostProcessInfo_t()
        fcos_postprocess_info.height = h
        fcos_postprocess_info.width = w
        fcos_postprocess_info.ori_height = disp_h
        fcos_postprocess_info.ori_width = disp_w
        fcos_postprocess_info.score_threshold = 0.5
        fcos_postprocess_info.nms_threshold = 0.6
        fcos_postprocess_info.nms_top_k = 5
        fcos_postprocess_info.is_pad_resize = 0

        global output_tensors
        output_tensors = (hbDNNTensor_t * len(models[0].outputs))()

        for i in range(len(models[0].outputs)):
            output_tensors[i].properties.tensorLayout = get_TensorLayout(models[0].outputs[i].properties.layout)

            if (len(models[0].outputs[i].properties.scale_data) == 0):
                output_tensors[i].properties.quantiType = 0
            else:
                output_tensors[i].properties.quantiType = 2
                scale_data_tmp = models[0].outputs[i].properties.scale_data.reshape(1, 1, 1, models[0].outputs[i].properties.shape[3])
                output_tensors[i].properties.scale.scaleData = scale_data_tmp.ctypes.data_as(ctypes.POINTER(ctypes.c_float))

            for j in range(len(models[0].outputs[i].properties.shape)):
                output_tensors[i].properties.validShape.dimensionSize[j] = models[0].outputs[i].properties.shape[j]
                output_tensors[i].properties.alignedShape.dimensionSize[j] = models[0].outputs[i].properties.shape[j]

        ai_inference = AiInference(video_display, models)
        ai_inference.start()

# ================================================================================
# 【程序架构总结】
# ================================================================================
# 本程序展示了一个完整的视频流实时处理系统，包含：
#
# 1. 多线程架构
#    - DecodeThread：RTSP流解码（阻塞IO密集型）
#    - DisplayThread：图像处理和显示（计算密集型）
#    - InferenceThread：AI推理（计算密集型）
#
# 2. 生产者-消费者模式
#    - 使用Queue进行线程间通信
#    - 队列大小限制防止内存溢出
#
# 3. 编码格式自动检测
#    - 通过FourCC和NAL单元解析
#    - 支持H.264/H.265/MJPEG
#
# 4. 实时性能监控
#    - 解码FPS统计
#    - 显示FPS统计
#    - AI推理FPS统计
#
# 5. 优雅退出机制
#    - Ctrl+C信号处理
#    - 资源正确释放
