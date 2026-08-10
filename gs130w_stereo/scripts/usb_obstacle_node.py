#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""usb_obstacle_node.py - USB 摄像头障碍物语义检测 (双目避障的补充感知)

为什么需要这个节点:
  双目深度的已知盲区 — 透明瓶测距偏远 (~1.5x)、黑色无纹理物体立体匹配失败。
  USB 摄像头 (手势识别那路) 加一个 BPU 语义检测器做兜底:
  双目漏检但 USB 看到大件障碍 → 仍然触发避障。

数据流:
  gesture_control.py (独占 /dev/video0) 的 :8094/snapshot JPEG
    → 本节点 ~4Hz 拉帧 (绝不再开 video0, 与 vision Q&A 同一条官方取帧路径)
    → BPU ppyolo_trashdet 416x416 (X5 Bayes-e 可用, 单类 "trash":
      对瓶子/罐子/纸盒等手持障碍物敏感)
    → 最大目标框的面积/方位 → UDP 5009 查询应答

通信 (与避障节点约定):
  UDP 127.0.0.1:5009, 收到任意报文 → 回复 JSON:
    {"online": true,  "side": "left"/"center"/"right"/null,
     "area": 0.0~1.0, "score": 0.55, "label": "trash", "ts": 1786396404.0}
    online=false 表示取不到 USB 帧 (手势节点没起), side 恒为 null

启动:
  python3 -u usb_obstacle_node.py            # 前台调试
  由 start_avoidance.sh 自动拉起 (随避障节点同生共死)
"""
import json
import socket
import threading
import time
import urllib.request

import cv2
import numpy as np

SNAPSHOT_URL = 'http://127.0.0.1:8094/snapshot'
MODEL_PATH = '/opt/tros/humble/lib/mono2d_trash_detection/config/ppyolo_trashdet_416x416_nv12.bin'
UDP_PORT = 5009
POLL_HZ = 4.0
FRAME_W, FRAME_H = 640, 480        # gesture_control 输出 640x480

# 模型配置 (ppyoloworkconfig.json: yolov3 parser, 1 类)
IMG_SIZE = 416
STRIDES = (32, 16)
ANCHORS = (((2.53125, 2.5625), (4.21875, 5.28125), (10.75, 9.96875)),
           ((0.625, 0.875), (1.4375, 1.6875), (2.3125, 3.625)))
SCORE_TH = 0.40
NMS_TH = 0.45

# 障碍判定: 目标框面积占比 ≥ 3% (近处手持物必然大) 才算障碍
AREA_TH = 0.03


# ---------------- YOLOv3 解码 (class_num=1) ----------------
def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def decode(outputs, score_th=SCORE_TH):
    """outputs: [stride32_feat, stride16_feat] PyDNNTensor, NHWC (1,g,g,3*6)
    返回 [(x1,y1,x2,y2,score), ...] 模型输入坐标系 (416x416)"""
    dets = []
    for out, stride, anchors in zip(outputs, STRIDES, ANCHORS):
        feat = np.array(out.buffer)[0]           # (g,g,18)
        g = feat.shape[0]
        feat = feat.reshape(g, g, 3, 6)
        for gy in range(g):
            for gx in range(g):
                for a in range(3):
                    tx, ty, tw, th, conf, cls = feat[gy, gx, a]
                    score = _sigmoid(conf) * _sigmoid(cls)
                    if score < score_th:
                        continue
                    aw, ah = anchors[a]
                    cx = (_sigmoid(tx) + gx) * stride
                    cy = (_sigmoid(ty) + gy) * stride
                    bw = np.exp(tw) * aw * stride
                    bh = np.exp(th) * ah * stride
                    dets.append((cx - bw / 2, cy - bh / 2,
                                 cx + bw / 2, cy + bh / 2, float(score)))
    return _nms(dets, NMS_TH)


def _nms(dets, iou_th):
    if not dets:
        return []
    dets = sorted(dets, key=lambda d: -d[4])
    keep = []
    while dets:
        best = dets.pop(0)
        keep.append(best)
        dets = [d for d in dets if _iou(best, d) < iou_th]
    return keep


def _iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / max(1e-6, area_a + area_b - inter)


def bgr_to_nv12(bgr):
    h, w = bgr.shape[:2]
    yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420)
    y = yuv[:h, :].reshape(-1)
    u = yuv[h:h + h // 4, :].reshape(-1)
    v = yuv[h + h // 4:, :].reshape(-1)
    uv = np.empty(u.size * 2, dtype=np.uint8)
    uv[0::2] = u
    uv[1::2] = v
    return y.tobytes() + uv.tobytes()


class UsbObstacleNode:
    def __init__(self):
        from hobot_dnn import pyeasy_dnn as dnn
        # BPU 可能被刚启动的 stereonet 短暂占用, 重试 5 次
        last_err = None
        for attempt in range(5):
            try:
                self.model = dnn.load(MODEL_PATH)[0]
                break
            except Exception as e:
                last_err = e
                print(f'[WARN] 模型加载失败(第{attempt+1}次), 2s后重试: {e}', flush=True)
                time.sleep(2.0)
        else:
            raise RuntimeError(f'BPU 模型加载失败: {last_err}')
        self._lock = threading.Lock()
        self._result = {'online': False, 'side': None, 'area': 0.0,
                        'score': 0.0, 'label': 'trash', 'ts': 0.0}
        self._stop = False

    # ---------------- 检测循环 ----------------
    def run_detect(self):
        period = 1.0 / POLL_HZ
        while not self._stop:
            t0 = time.time()
            try:
                self._tick()
            except Exception as e:
                print(f'[WARN] detect tick: {e}', flush=True)
            dt = time.time() - t0
            if dt < period:
                time.sleep(period - dt)

    def _tick(self):
        try:
            with urllib.request.urlopen(SNAPSHOT_URL, timeout=1.0) as resp:
                jpg = resp.read()
        except Exception:
            with self._lock:
                self._result['online'] = False
                self._result['side'] = None
            return

        arr = np.frombuffer(jpg, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return
        src_h, src_w = img.shape[:2]
        inp = cv2.resize(img, (IMG_SIZE, IMG_SIZE))
        nv12 = np.frombuffer(bgr_to_nv12(inp), dtype=np.uint8)
        outputs = self.model.forward([nv12])
        dets = decode(outputs)
        if not dets:
            with self._lock:
                self._result = {'online': True, 'side': None, 'area': 0.0,
                                'score': 0.0, 'label': 'trash', 'ts': time.time()}
            return

        # 取最大目标框, 映射回原图坐标
        best = max(dets, key=lambda d: (d[2] - d[0]) * (d[3] - d[1]))
        x1, y1, x2, y2, score = best
        bw, bh = x2 - x1, y2 - y1
        area = (bw * bh) / float(IMG_SIZE * IMG_SIZE)
        cx_ratio = ((x1 + x2) / 2.0) / IMG_SIZE

        side = None
        if area >= AREA_TH:
            if cx_ratio < 0.4:
                side = 'left'
            elif cx_ratio > 0.6:
                side = 'right'
            else:
                side = 'center'
        with self._lock:
            self._result = {'online': True, 'side': side,
                            'area': round(area, 4), 'score': round(score, 3),
                            'label': 'trash', 'ts': time.time(),
                            'src': f'{src_w}x{src_h}'}

    # ---------------- UDP 应答 ----------------
    def run_udp(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', UDP_PORT))
        print(f'[READY] USB 障碍检测 UDP :{UDP_PORT} (查询应答式)', flush=True)
        while not self._stop:
            try:
                data, addr = sock.recvfrom(256)
            except Exception:
                break
            with self._lock:
                payload = dict(self._result)
            # 结果超过 1.5s 视为过期
            if time.time() - payload.get('ts', 0) > 1.5:
                payload['online'] = False
                payload['side'] = None
            try:
                sock.sendto(json.dumps(payload).encode('utf-8'), addr)
            except Exception:
                pass

    def start(self):
        threading.Thread(target=self.run_detect, daemon=True).start()
        self.run_udp()   # 主线程跑 UDP

    def stop(self):
        self._stop = True


def main():
    print('=' * 52, flush=True)
    print(' USB 障碍语义检测 (双目避障补充)', flush=True)
    print(f' 模型: {MODEL_PATH}', flush=True)
    print(f' 取帧: {SNAPSHOT_URL} @ {POLL_HZ}Hz', flush=True)
    print(f' 判定: 面积>{AREA_TH*100:.0f}% → 左/中/右', flush=True)
    print('=' * 52, flush=True)
    node = UsbObstacleNode()
    try:
        node.start()
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()


if __name__ == '__main__':
    main()
