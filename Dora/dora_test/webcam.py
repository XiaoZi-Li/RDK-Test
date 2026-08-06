#!/usr/bin/env python3

import cv2
from dora import Node
import numpy as np
import time
import pyarrow as pa

FRAME_WIDTH = 640
FRAME_HEIGHT = 480

def main():
    print("[Webcam] 启动摄像头节点")

    cap = cv2.VideoCapture(1)
    # 尝试 MJPG 格式（压缩，USB带宽需求低），如果失败再回退 YUYV
    # V4L2 格式代码: MJPG = 0x47504A4D, YUYV = 0x56595559
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 减少摄像头内部缓冲，降低延迟

    actual_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    actual_height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    # 读取实际使用的格式
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    fmt = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)])
    print(f"[Webcam] 摄像头已启动: /dev/video1 @ {actual_width:.0f}x{actual_height:.0f}, {actual_fps:.0f}fps, 格式: {fmt}")

    node = Node("webcam")
    frame_count = 0
    start_time = time.time()

    # 预分配 metadata，避免每帧构建
    metadata = {"width": FRAME_WIDTH, "height": FRAME_HEIGHT, "encoding": "bgr8"}

    try:
        for event in node:
            if event["type"] == "INPUT" and event["id"] == "tick":
                ret, frame = cap.read()
                if not ret:
                    print("[Webcam] 读取帧失败")
                    continue

                # 如果摄像头返回了非预期分辨率，才做 resize
                if frame.shape[1] != FRAME_WIDTH or frame.shape[0] != FRAME_HEIGHT:
                    frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))

                # 关键优化：指定 type=pa.uint8()
                # 默认 pa.array 会把 numpy uint8 推断为 int64，数据量暴增 8 倍！
                node.send_output(
                    "image",
                    pa.array(frame.flatten(), type=pa.uint8()),
                    metadata,
                )

                frame_count += 1
                if frame_count % 50 == 0:
                    fps = frame_count / (time.time() - start_time)
                    print(f"[Webcam] 已发送 {frame_count} 帧 | FPS: {fps:.1f}")

    except KeyboardInterrupt:
        print("[Webcam] 用户中断")
    finally:
        cap.release()
        print("[Webcam] 摄像头已释放")


if __name__ == "__main__":
    main()
