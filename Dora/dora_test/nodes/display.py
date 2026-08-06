#!/usr/bin/env python3

import cv2
import dora
from dora import Node
import numpy as np
import time

def main():
    print("[Display] 启动显示节点")
    
    node = Node("display")
    frame_count = 0
    start_time = time.time()
    last_time = start_time
    
    # 创建OpenCV显示窗口
    cv2.namedWindow("RDK X5 BPU Detection", cv2.WINDOW_AUTOSIZE)
    
    try:
        for event in node:
            if event["type"] == "INPUT":
                if event["id"] == "result":
                    # 重构图像数据
                    image_data = event["value"].to_numpy()
                    height = event["metadata"]["height"]
                    width = event["metadata"]["width"]
                    channels = event["metadata"]["channels"]
                    inference_time = event["metadata"]["inference_time"]
                    detection_count = event["metadata"]["detection_count"]
                    
                    # 从展平的数据重构图像
                    image = image_data.reshape(height, width, channels)
                    
                    # 添加性能信息到图像上
                    current_time = time.time()
                    fps = 1.0 / (current_time - last_time) if (current_time - last_time) > 0 else 0
                    last_time = current_time
                    
                    # 确保图像数据可写，优化内存使用
                    if not image.flags['WRITEABLE']:
                        image = np.copy(image, order='C')
                    
                    # 在图像上绘制FPS和推理时间信息
                    cv2.putText(image, f"FPS: {fps:.1f}", (10, 30),
                               cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                    cv2.putText(image, f"Inference: {inference_time:.1f}ms", (10, 70),
                               cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                    cv2.putText(image, f"Detections: {detection_count}", (10, 110),
                               cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                    
                    # 显示图像
                    cv2.imshow("RDK X5 BPU Detection", image)
                    
                    frame_count += 1
                    
                    # 每100帧输出一次统计信息（进一步减少输出频率以提高性能）
                    if frame_count % 100 == 0:
                        elapsed_time = current_time - start_time
                        avg_fps = frame_count / elapsed_time if elapsed_time > 0 else 0
                        print(f"[Display] Frame: {frame_count} | FPS: {avg_fps:.1f} | Detection: {detection_count} | Inference: {inference_time:.1f}ms")
                    
                    # 检查按键退出
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                        
    except KeyboardInterrupt:
        print("[Display] 用户中断")
    finally:
        cv2.destroyAllWindows()
        # 输出最终统计信息
        end_time = time.time()
        total_time = end_time - start_time
        avg_fps = frame_count / total_time if total_time > 0 else 0
        print(f"[Display] 总结: {frame_count} 帧, 平均FPS: {avg_fps:.2f}")

if __name__ == "__main__":
    main()