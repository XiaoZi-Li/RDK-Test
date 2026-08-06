import sys
import time
import json
import ctypes
import numpy as np
import socket

# --- 1. 导入底层库 ---
try:
    from hobot_vio import libsrcampy as srcampy
except ImportError:
    from hobot_vio_rdkx5 import libsrcampy as srcampy
try:
    from hobot_dnn import pyeasy_dnn as dnn
except ImportError:
    from hobot_dnn_rdkx5 import pyeasy_dnn as dnn

# --- 2. C++ 结构体映射 (保持不变) ---
class hbSysMem_t(ctypes.Structure):
    _fields_ = [("phyAddr",ctypes.c_double), ("virAddr",ctypes.c_void_p), ("memSize",ctypes.c_int)]
class hbDNNQuantiShift_yt(ctypes.Structure):
    _fields_ = [("shiftLen",ctypes.c_int), ("shiftData",ctypes.c_char_p)]
class hbDNNQuantiScale_t(ctypes.Structure):
    _fields_ = [("scaleLen",ctypes.c_int), ("scaleData",ctypes.POINTER(ctypes.c_float)), ("zeroPointLen",ctypes.c_int), ("zeroPointData",ctypes.c_char_p)]    
class hbDNNTensorShape_t(ctypes.Structure):
    _fields_ = [("dimensionSize",ctypes.c_int * 8), ("numDimensions",ctypes.c_int)]
class hbDNNTensorProperties_t(ctypes.Structure):
    _fields_ = [
        ("validShape",hbDNNTensorShape_t), ("alignedShape",hbDNNTensorShape_t),
        ("tensorLayout",ctypes.c_int), ("tensorType",ctypes.c_int),
        ("shift",hbDNNQuantiShift_yt), ("scale",hbDNNQuantiScale_t),
        ("quantiType",ctypes.c_int), ("quantizeAxis", ctypes.c_int),
        ("alignedByteSize",ctypes.c_int), ("stride",ctypes.c_int * 8)
    ]
class hbDNNTensor_t(ctypes.Structure):
    _fields_ = [("sysMem",hbSysMem_t * 4), ("properties",hbDNNTensorProperties_t)]
class Yolov5PostProcessInfo_t(ctypes.Structure):
    _fields_ = [
        ("height",ctypes.c_int), ("width",ctypes.c_int),
        ("ori_height",ctypes.c_int), ("ori_width",ctypes.c_int),
        ("score_threshold",ctypes.c_float), ("nms_threshold",ctypes.c_float),
        ("nms_top_k",ctypes.c_int), ("is_pad_resize",ctypes.c_int)
    ]

libpostprocess = ctypes.CDLL('/usr/lib/libpostprocess.so') 
get_Postprocess_result = libpostprocess.Yolov5PostProcess
get_Postprocess_result.argtypes = [ctypes.POINTER(Yolov5PostProcessInfo_t)]  
get_Postprocess_result.restype = ctypes.c_char_p  

def get_TensorLayout(Layout):
    return int(2) if Layout == "NCHW" else int(0)

# --- 3. 核心主程序 ---
def main():
    print("🧠 正在加载机器狗的 AI 大脑 (YOLOv5)...")
    models = dnn.load('/app/model/basic/yolov5s_672x672_nv12.bin')
    
    print("👁️ 正在唤醒摄像头的视觉神经...")
    cam = srcampy.Camera()
    cam.open_cam(0, -1, -1, [672, 1920], [672, 1080], 1080, 1920)
    
    print("📺 正在连接 HDMI 显示器...")
    disp = srcampy.Display()
    disp.display(0, 1920, 1080)  
    disp.display(3, 1920, 1080)  
    srcampy.bind(cam, disp)
    
    # 建立 UDP 通信客户端
    UDP_IP = "127.0.0.1"
    UDP_PORT = 5005
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"🔗 左脑视觉已连接到右脑运动中枢 (UDP 端口 {UDP_PORT})")

    # 初始化解析配置
    h, w = 672, 672
    post_info = Yolov5PostProcessInfo_t()
    post_info.height, post_info.width = h, w
    post_info.ori_height = 1080
    post_info.ori_width = 1920
    post_info.score_threshold = 0.25   # 🌟 降低阈值，提升识别率
    post_info.nms_threshold = 0.45
    post_info.nms_top_k = 20
    post_info.is_pad_resize = 1        # 🌟 解决画面拉伸变形导致识别不准的核心开关！

    print("\n🚀 机器狗已睁开双眼！防撞系统在线！(按 Ctrl+C 停止)\n")
    print("-" * 50)
    
    box_color_ARGB = 0xFF00FF00

    # 👻 ==========================================
    # 👻 幽灵记忆机制状态变量初始化
    # ==========================================
    last_person_time = 0.0     # 上次看到人的时间戳
    last_person_area = 0.0     # 上次看到人时的面积占比
    ghost_memory_time = 3.0    # 记忆保持时间（秒）：人消失后，保持警戒3秒钟
    
    try:
        while True:
            img_bytes = cam.get_img(2, h, w)
            if img_bytes is None:
                continue
                
            img_nv12 = np.frombuffer(img_bytes, dtype=np.uint8)
            outputs = models[0].forward(img_nv12)
            
            output_tensors = (hbDNNTensor_t * len(models[0].outputs))()
            for i in range(len(models[0].outputs)):
                output_tensors[i].properties.tensorLayout = get_TensorLayout(outputs[i].properties.layout)
                if (len(outputs[i].properties.scale_data) == 0):
                    output_tensors[i].properties.quantiType = 0
                    output_tensors[i].sysMem[0].virAddr = ctypes.cast(outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), ctypes.c_void_p)
                else:
                    output_tensors[i].properties.quantiType = 2       
                    output_tensors[i].properties.scale.scaleData = outputs[i].properties.scale_data.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                    output_tensors[i].sysMem[0].virAddr = ctypes.cast(outputs[i].buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)), ctypes.c_void_p)
                for j in range(len(outputs[i].properties.shape)):
                    output_tensors[i].properties.validShape.dimensionSize[j] = outputs[i].properties.shape[j]
                libpostprocess.Yolov5doProcess(output_tensors[i], ctypes.pointer(post_info), i)

            result_str = get_Postprocess_result(ctypes.pointer(post_info)).decode('utf-8')  
            data = json.loads(result_str[16:])  
            
            # 当前帧是否看到人的标志位
            person_detected_this_frame = False
            
            if len(data) == 0:
                disp.set_graph_rect(0, 0, 0, 0, 3, 1, 0)
            
            for index, result in enumerate(data):  
                name = result['name']
                if name != "person":
                    continue # 只关心人
                    
                bbox = result['bbox']    
                score = result['score']  
                
                x1 = max(0, int(bbox[0]))
                y1 = max(2, int(bbox[1]))
                x2 = min(1920, int(bbox[2]))
                y2 = min(1080, int(bbox[3]))
                
                x_center = (x1 + x2) / 2
                box_area = (x2 - x1) * (y2 - y1)
                area_ratio = box_area / (1920 * 1080)
                
                # 🌟 更新状态机：看到了人，刷新记忆时间戳和面积
                person_detected_this_frame = True
                last_person_time = time.time()
                last_person_area = area_ratio
                
                action = "stop"
                
                # 距离与追踪逻辑
                if area_ratio > 0.35: 
                    action = "stop" 
                    print(f"⚠️ 距离过近 (面积占比 {area_ratio:.2f}) -> 动作: {action}")
                elif area_ratio < 0.15: 
                    if x_center < 700:
                        action = "turn_left"
                    elif x_center > 1220:
                        action = "turn_right"
                    else:
                        action = "walk"
                    print(f"🎯 追踪靠近 (面积占比 {area_ratio:.2f}) -> 动作: {action}")
                else:
                    if x_center < 700:
                        action = "turn_left"
                    elif x_center > 1220:
                        action = "turn_right"
                    else:
                        action = "stop"
                    print(f"✅ 原地锁定 (面积占比 {area_ratio:.2f}) -> 动作: {action}")

                sock.sendto(action.encode('utf-8'), (UDP_IP, UDP_PORT))
                
                # 画框
                label_text = f"{name}: {score:.2f}".encode('gb2312')
                flush_flag = 1 if index == 0 else 0
                disp.set_graph_rect(x1, y1, x2, y2, 3, flush_flag, 0xFF00FF00)
                disp.set_graph_word(x1, y1 - 2, label_text, 3, flush_flag, 0xFF00FF00)
            
            # 👻 ==========================================
            # 👻 幽灵记忆逻辑执行区
            # ==========================================
            if not person_detected_this_frame:
                time_since_last_seen = time.time() - last_person_time
                
                # 如果人刚刚消失不到 3 秒，并且消失前面积很大（> 0.35说明已经贴脸了）
                if time_since_last_seen < ghost_memory_time and last_person_area > 0.35:
                    print(f"👻 [幽灵记忆触发] 目标贴脸消失！判定为距离极近盲区，强制刹车保命！(剩余记忆 {ghost_memory_time - time_since_last_seen:.1f}s)")
                    sock.sendto(b"stop", (UDP_IP, UDP_PORT))
                else:
                    # 真正丢失目标（人走远了消失，或者时间已过）
                    sock.sendto(b"stop", (UDP_IP, UDP_PORT))
            
    finally:
        print("\n🛑 正在安全关闭摄像头硬件释放资源...")
        cam.close_cam()
        disp.close()

if __name__ == '__main__':
    main()