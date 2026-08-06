#!/usr/bin/env python3

import cv2
from dora import Node
import numpy as np
import time
import os
import threading
import queue
import pyarrow as pa

VIS_W, VIS_H = 320, 240
EXPECTED_SIZE = VIS_W * VIS_H * 3

HAS_DISPLAY = bool(os.environ.get("DISPLAY", "").strip())


def put_text_with_shadow(img, text, pos, scale, color):
    cv2.putText(img, text, (pos[0] + 1, pos[1] + 1),
                cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 2)
    cv2.putText(img, text, pos,
                cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1)


def receiver_thread(node, frame_queue: queue.Queue, stop_event: threading.Event,
                    stats: dict):
    """
    子线程：专门跑 dora 事件循环接收图像，放入队列。
    队列最多保留 2 帧，旧帧直接丢弃（始终显示最新帧）。
    """
    frame_count = 0
    start_time = time.time()

    try:
        for event in node:
            if stop_event.is_set():
                break
            if event["type"] != "INPUT" or event["id"] != "image_vis":
                continue

            image_data = event["value"].to_numpy(zero_copy_only=False).view(np.uint8)
            if image_data.size != EXPECTED_SIZE:
                if image_data.size < EXPECTED_SIZE:
                    image_data = np.zeros(EXPECTED_SIZE, dtype=np.uint8)
                else:
                    image_data = image_data[:EXPECTED_SIZE]

            frame_count += 1
            elapsed = time.time() - start_time
            avg_fps = frame_count / elapsed if elapsed > 0 else 0
            stats["fps"] = avg_fps
            stats["frame"] = frame_count

            if frame_count % 30 == 0:
                print(f"[Plot] Frame: {frame_count} | 平均FPS: {avg_fps:.1f}")

            # 队列满则丢掉最老的帧，保持低延迟
            if frame_queue.full():
                try:
                    frame_queue.get_nowait()
                except queue.Empty:
                    pass
            frame_queue.put_nowait(image_data.reshape(VIS_H, VIS_W, 3).copy())

    except Exception as e:
        print(f"[Plot] 接收线程异常: {e}")
    finally:
        stop_event.set()


def main():
    print("[Plot] 启动绘图节点")

    node = Node("plot")
    stop_event = threading.Event()
    # 队列深度 2：接收线程不被 imshow 阻塞，同时显示延迟可控
    frame_queue = queue.Queue(maxsize=2)
    stats = {"fps": 0.0, "frame": 0}

    # dora 事件循环放子线程，OpenCV GUI 保留在主线程（解决 SIGABRT）
    t = threading.Thread(
        target=receiver_thread,
        args=(node, frame_queue, stop_event, stats),
        daemon=True
    )
    t.start()

    if HAS_DISPLAY:
        print("[Plot] 检测到 DISPLAY，在主线程运行显示窗口")
        cv2.namedWindow("RDK X5 YOLOv5 Detection", cv2.WINDOW_AUTOSIZE)

    start_time = time.time()

    try:
        while not stop_event.is_set():
            if HAS_DISPLAY:
                try:
                    frame = frame_queue.get(timeout=0.1)
                    display = np.array(frame, copy=True)
                    put_text_with_shadow(display, f"FPS: {stats['fps']:.1f}", (8, 20), 0.6, (0, 255, 0))
                    put_text_with_shadow(display, f"Frame: {stats['frame']}", (8, 40), 0.5, (255, 255, 255))
                    put_text_with_shadow(display, "BPU Detection Running", (8, 58), 0.4, (180, 180, 180))
                    cv2.imshow("RDK X5 YOLOv5 Detection", display)
                except queue.Empty:
                    pass  # 没有新帧，继续等

                # waitKey 必须在主线程调用
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    stop_event.set()
                    break
            else:
                # 无显示环境：主线程只等子线程结束
                t.join(timeout=1.0)

    except KeyboardInterrupt:
        print("[Plot] 用户中断")
    finally:
        stop_event.set()
        t.join(timeout=2.0)
        if HAS_DISPLAY:
            cv2.destroyAllWindows()
        total_time = time.time() - start_time
        fps = stats["frame"] / total_time if total_time > 0 else 0
        print(f"[Plot] 总结: {stats['frame']} 帧, 平均FPS: {fps:.2f}")


if __name__ == "__main__":
    main()
