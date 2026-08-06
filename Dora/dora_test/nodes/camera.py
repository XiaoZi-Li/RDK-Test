#!/usr/bin/env python3

import cv2
import dora
from dora import Node
import pyarrow as pa
import time

def main():
    print("[Camera] 启动高速摄像头节点")
    
    # 打开USB摄像头，设备序号为1，优化参数以提高帧率
    cap = cv2.VideoCapture(1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 减少缓冲区大小
    
    print(f"[Camera] 摄像头已启动: /dev/video1")
    
    node = Node("camera")
    frame_count = 0
    start_time = time.time()
    
    try:
        while True:
            ret, frame = cap.read()
            if ret:
                # 将BGR图像展平并发送
                flattened = frame.flatten()
                metadata = {
                    "height": frame.shape[0],
                    "width": frame.shape[1],
                    "channels": frame.shape[2]
                }
                
                node.send_output(
                    "image", 
                    pa.array(flattened), 
                    metadata
                )
                
                frame_count += 1
                
                # 每100帧输出一次FPS信息（进一步减少输出频率以提高性能）
                if frame_count % 100 == 0:
                    current_time = time.time()
                    fps = frame_count / (current_time - start_time)
                    print(f"[Camera] 已发送 {frame_count} 帧 | FPS: {fps:.1f}")
            else:
                print("[Camera] 读取帧失败")
                
    except KeyboardInterrupt:
        print("[Camera] 用户中断")
    finally:
        cap.release()
        print("[Camera] 摄像头已释放")

if __name__ == "__main__":
    main()