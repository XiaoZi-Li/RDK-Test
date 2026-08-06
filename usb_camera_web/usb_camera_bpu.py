#!/usr/bin/env python3
"""usb_camera_bpu.py - USB + BPU yolov5 + BPU 手势 (TROS) + MJPEG 推流
基于原 /app/usb_camera_web/usb_camera_mjpeg_server.py 升级。
"""
import sys, time, threading, argparse
sys.path.append('/app/pydev_demo')
sys.path.append('/app/pydev_demo/07_usb_camera_sample')

import cv2, numpy as np
import hbm_runtime
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import Image
from ai_msgs.msg import PerceptionTargets
import utils.preprocess_utils as pre_utils
import utils.postprocess_utils as post_utils
import utils.common_utils as common
import utils.draw_utils as draw
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

STRIDES = np.array([8, 16, 32], dtype=np.int32)
ANCHORS = np.array([[10,13],[16,30],[33,23],[30,61],[62,45],[59,119],
                     [116,90],[156,198],[373,326]], dtype=np.float32).reshape(3,3,2)
MODEL_PATH = '/app/model/basic/yolov5s_672x672_nv12.bin'
LABEL_PATH = '/app/pydev_demo/07_usb_camera_sample/coco_classes.names'
SCORE_THRES, NMS_THRES, CLASSES_NUM = 0.30, 0.45, 80

GESTURE_TO_INFO = {
    2.0: ('ThumbUp', 'sit'), 12.0: ('ThumbLeft', 'turn_left'),
    13.0: ('ThumbRight', 'turn_right'),
    3.0: ('Victory', None), 4.0: ('Mute', None), 5.0: ('Palm', None),
    11.0: ('Okay', None), 14.0: ('Awesome', None),
}
HAND_EDGES = [
    (0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),
    (5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),(15,16),
    (13,17),(17,18),(18,19),(19,20),(0,17),
]

# ROS bridge
class RosBridge(Node):
    def __init__(self):
        super().__init__('usb_camera_bpu_ros')
        qos = QoSProfile(reliability=QoSReliabilityPolicy.BEST_EFFORT,
                        history=QoSHistoryPolicy.KEEP_LAST, depth=2)
        self.image_pub = self.create_publisher(Image, '/image_combine_raw', qos)
        self.lmk_sub = self.create_subscription(
            PerceptionTargets, '/hobot_hand_lmk_detection', self._lmk_cb, qos)
        self.gesture_sub = self.create_subscription(
            PerceptionTargets, '/hobot_hand_gesture_detection', self._gesture_cb, qos)
        self.lock = threading.Lock()
        self.latest_lmk_norm = None
        self.latest_gesture_name = None
        self.latest_gesture_value = None
        self.lmk_n = 0
        self.last_lmk_time = 0.0

    def publish_frame(self, bgr):
        h, w = bgr.shape[:2]
        y, uv = pre_utils.bgr_to_nv12_planes(bgr)
        nv12 = np.concatenate((y.reshape(-1), uv.reshape(-1))).astype(np.uint8)
        msg = Image()
        msg.height, msg.width = h, w
        msg.encoding = 'nv12'
        msg.step = w
        msg.data = nv12.tobytes()
        self.image_pub.publish(msg)

    def _lmk_cb(self, msg):
        for target in msg.targets:
            for pt in target.points:
                if pt.type == 'hand_kps' and len(pt.point) == 21:
                    with self.lock:
                        self.latest_lmk_norm = [(p.x, p.y) for p in pt.point]
                        self.lmk_n += 1
                        self.last_lmk_time = time.time()
                    return
        with self.lock:
            self.latest_lmk_norm = None

    def _gesture_cb(self, msg):
        for target in msg.targets:
            for attr in target.attributes:
                if attr.type == 'gesture':
                    try:
                        v = float(attr.value)
                    except Exception:
                        continue
                    info = GESTURE_TO_INFO.get(v, ('?', None))
                    with self.lock:
                        self.latest_gesture_name = info[0]
                        self.latest_gesture_value = v
                    return


# BPU capture
class BpuYoloCapture:
    def __init__(self, device, width, height, fps, jpeg_quality=60):
        self.device = device
        self.jpeg_quality = int(jpeg_quality)

        self.model = hbm_runtime.HB_HBMRuntime(MODEL_PATH)
        self.model_name = self.model.model_names[0]
        self.input_name = self.model.input_names[self.model_name][0]
        self.output_names = self.model.output_names[self.model_name]
        self.output_quants = self.model.output_quants[self.model_name]
        input_shape = self.model.input_shapes[self.model_name][self.input_name]
        self.input_H, self.input_W = input_shape[2], input_shape[3]
        self.model.set_scheduling_params(priority={self.model_name: 0}, bpu_cores={self.model_name: [0]})
        self.coco_names = common.load_class_names(LABEL_PATH)
        common.print_model_info(self.model)

        rclpy.init()
        self.ros = RosBridge()
        threading.Thread(target=rclpy.spin, args=(self.ros,), daemon=True).start()

        self._cap = cv2.VideoCapture(device)
        if not self._cap.isOpened():
            raise RuntimeError(f'无法打开 {device}')
        self._cap.set(cv2.CAP_PROP_FOURCC,
                     cv2.VideoWriter_fourcc('Y', 'U', 'Y', 'V'))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._cap.set(cv2.CAP_PROP_FPS, fps)
        self.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = self._cap.get(cv2.CAP_PROP_FPS)

        self.lock = threading.Condition()
        self.latest_jpeg = None
        self.frame_id = 0
        self.capture_fps = 0.0
        self.infer_fps = 0.0
        self.last_summary = '(none)'
        self._frames = self._infer_frames = 0
        self._t0 = time.time()
        self._running = False

    def start(self):
        print(f'[capture+infer] USB {self.device} {self.width}x{self.height}'
              f'@{self.fps:.1f} | BPU yolov5s {self.input_W}x{self.input_H}'
              f' | MJPEG q={self.jpeg_quality} | port=8093', flush=True)
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        while self._running:
            ret, frame = self._cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue
            self._frames += 1
            # 每 5 帧才 publish 给 TROS 一次 (避免 ROS 阻塞主循环)
            if self._frames % 5 == 0:
                try:
                    self.ros.publish_frame(frame)
                except Exception:
                    pass
            try:
                inp = self._infer_preprocess(frame)
                outputs = self.model.run(inp)
                boxes, cls_ids, scores = self._infer_postprocess(
                    outputs, frame.shape[1], frame.shape[0])
                self._infer_frames += 1
            except Exception as _e:
                import traceback; traceback.print_exc()
                boxes = np.zeros((0, 4))
                cls_ids = np.zeros((0,))
                scores = np.zeros((0,))
            if len(boxes) > 0:
                self.last_summary = ', '.join(
                    [self.coco_names[int(c)] for c in cls_ids][:5])
            vis = draw.draw_boxes(
                frame.copy(), boxes, cls_ids, scores,
                self.coco_names, common.rdk_colors)
            with self.ros.lock:
                lmk = self.ros.latest_lmk_norm
                gest = self.ros.latest_gesture_name
                gv = self.ros.latest_gesture_value
                lmk_n = self.ros.lmk_n
                lmk_age = (time.time() - self.ros.last_lmk_time
                           if self.ros.last_lmk_time > 0 else -1)
            if lmk is not None and len(lmk) == 21:
                pts_px = [(int(nx * self.width), int(ny * self.height))
                           for nx, ny in lmk]
                for a, b in HAND_EDGES:
                    cv2.line(vis, pts_px[a], pts_px[b], (0, 255, 0), 2)
                for i, (x, y) in enumerate(pts_px):
                    color = (0, 255, 255) if i == 0 else (0, 200, 255)
                    cv2.circle(vis, (x, y), 5, color, -1)
            cv2.rectangle(vis, (0, 0), (self.width, 30), (0, 0, 0), -1)
            cv2.putText(vis,
                f'BPU yolov5s {self.input_W}x{self.input_H} | '
                f'infer={self._infer_frames}/{self._frames} '
                f'lmk={lmk_n} age={lmk_age:.1f}s',
                (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
            cv2.rectangle(vis, (0, self.height - 60), (self.width, self.height),
                          (0, 0, 0), -1)
            if gest:
                info = GESTURE_TO_INFO.get(
                    gv if isinstance(gv, (int, float)) else -1, ('?', None))
                action_str = f' -> {info[1]}' if info[1] else ''
                cv2.putText(vis,
                    f'GESTURE: {gest} (val={gv}){action_str}',
                    (10, self.height - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (0, 255, 0), 2)
            else:
                cv2.putText(vis, 'GESTURE: (waiting)',
                    (10, self.height - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (128, 128, 128), 1)
            cv2.putText(vis,
                f'last: {self.last_summary[:80]}',
                (10, self.height - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (255, 200, 0), 1)
            ok, buf = cv2.imencode('.jpg', vis, encode_param)
            if ok:
                with self.lock:
                    self.latest_jpeg = buf.tobytes()
                    self.frame_id += 1
                    self.lock.notify_all()
            now = time.time()
            if now - self._t0 > 5:
                self.capture_fps = self._frames / (now - self._t0)
                self.infer_fps = self._infer_frames / (now - self._t0)
                self._frames = self._infer_frames = 0
                self._t0 = now
                print(f'[loop] capture={self.capture_fps:.1f}fps '
                      f'infer={self.infer_fps:.1f}fps', flush=True)

    def _infer_preprocess(self, bgr):
        resize = pre_utils.resized_image(bgr, self.input_W, self.input_H, 1)
        y, uv = pre_utils.bgr_to_nv12_planes(resize)
        nv12 = np.concatenate(
            (y.reshape(-1), uv.reshape(-1))).reshape(
                (1, self.input_H * 3 // 2, self.input_W, 1))
        return {self.model_name: {self.input_name: nv12}}

    def _infer_postprocess(self, outputs, img_w, img_h):
        fp32 = post_utils.dequantize_outputs(outputs, self.output_quants)
        pred = post_utils.decode_outputs(
            self.output_names, fp32, STRIDES, ANCHORS, CLASSES_NUM)
        xyxy, score, cls = post_utils.filter_predictions(pred, SCORE_THRES)
        if len(xyxy) == 0:
            return np.zeros((0, 4)), np.zeros((0,)), np.zeros((0,))
        keep = post_utils.NMS(xyxy, score, cls, NMS_THRES)
        if len(keep) == 0:
            return np.zeros((0, 4)), np.zeros((0,)), np.zeros((0,))
        xyxy = post_utils.scale_coords_back(
            xyxy[keep], img_w, img_h, self.input_W, self.input_H, 1)
        return xyxy, cls[keep], score[keep]

    def get_frame(self, last_id=-1, timeout=2.0):
        with self.lock:
            if self.frame_id <= last_id:
                self.lock.wait(timeout=timeout)
            return self.latest_jpeg, self.frame_id

    def stop(self):
        self._running = False
        if self._cap is not None:
            self._cap.release()


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>USB + BPU YOLOv5s + 手势实时画面</title>
<style>
body{margin:0;background:#111;color:#eee;font-family:sans-serif;
     display:flex;flex-direction:column;align-items:center}
h2{margin:14px 0 6px}
.bar{font-size:13px;color:#9bd;margin-bottom:10px}
img{border:2px solid #333;background:#000;max-width:95vw;max-height:80vh}
.btns{margin:10px 0 24px}
button{padding:6px 14px;margin:0 6px;font-size:14px;cursor:pointer}
</style></head>
<body>
<h2>USB 摄像头 + BPU YOLOv5s + BPU 手势 (TROS) 实时画面</h2>
<div class="bar">MJPEG /stream &nbsp;|&nbsp; 截图 /snapshot &nbsp;|&nbsp; 健康 /health</div>
<img id="cam" src="/stream" alt="...">
<div class="btns">
<button onclick="document.getElementById('cam').src='/stream?t='+Date.now()">重新连接</button>
<button onclick="location.href='/snapshot'">保存截图</button>
</div>
</body></html>"""


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    pass


def make_handler(cam):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/' or self.path.startswith('/?'):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(INDEX_HTML.encode('utf-8'))
                return
            if self.path.startswith('/health'):
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(
                    (f"OK {cam.width}x{cam.height} capture={cam.capture_fps:.1f}"
                     f" infer={cam.infer_fps:.1f}\n").encode())
                return
            if self.path.startswith('/snapshot'):
                frame, _ = cam.get_frame(timeout=3.0)
                if not frame:
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(b'no frame')
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(frame)))
                self.end_headers()
                self.wfile.write(frame)
                return
            if self.path.startswith('/stream'):
                self.send_response(200)
                self.send_header(
                    'Content-Type',
                    'multipart/x-mixed-replace; boundary=frame')
                self.send_header(
                    'Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.end_headers()
                last_id = -1
                try:
                    while True:
                        frame, last_id = cam.get_frame(
                            last_id=last_id, timeout=3.0)
                        if not frame:
                            continue
                        self.wfile.write(b'--frame\r\n')
                        self.wfile.write(b'Content-Type: image/jpeg\r\n')
                        self.wfile.write(
                            f'Content-Length: {len(frame)}\r\n\r\n'.encode())
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                except Exception:
                    return
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, fmt, *args):
            if args and '404' in str(args[0]):
                super().log_message(fmt, *args)

    return Handler


def main():
    p = argparse.ArgumentParser(
        description='USB + BPU yolov5 + 手势 + MJPEG 推流')
    p.add_argument('--device', default='/dev/video0')
    p.add_argument('--port', type=int, default=8093)
    p.add_argument('--width', type=int, default=640)
    p.add_argument('--height', type=int, default=480)
    p.add_argument('--fps', type=int, default=30)
    p.add_argument('--quality', type=int, default=60,
                   help='JPEG 编码质量 1-100 (默认 60 比 75 提速)')
    args = p.parse_args()
    cam = BpuYoloCapture(
        args.device, args.width, args.height, args.fps, args.quality)
    try:
        cam.start()
    except RuntimeError as e:
        print(f'[ERROR] {e}')
        return
    server = ThreadingHTTPServer(('0.0.0.0', args.port), make_handler(cam))
    print(f'[server] MJPEG: http://<板端IP>:{args.port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n[server] 退出中...')
    finally:
        cam.stop()
        server.server_close()


if __name__ == '__main__':
    main()
