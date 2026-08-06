#!/usr/bin/env python3
"""USB 摄像头 MJPEG 网络推流服务.

后台线程从 /dev/video0 采集帧（YUYV 640x480），HTTP server 在 8093 端口
提供浏览器原生可看的 multipart/x-mixed-replace MJPEG 流。

路由:
  /         -> 内嵌 <img> 的 HTML 查看页
  /stream   -> MJPEG 流（可直接被 <img src> 或 VLC 拉取）
  /health   -> 状态文本（采集 fps、分辨率等）
  /snapshot -> 当前一帧 JPEG（便于保存截图）

用法:
  python usb_camera_mjpeg_server.py
  python usb_camera_mjpeg_server.py --device /dev/video0 --port 8093 --width 640 --height 480 --fps 30
"""
import argparse
import threading
import time
import cv2
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from http.server import HTTPServer


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """每个 HTTP 客户端一个线程，并发"""


class UsbCameraCapture:
    """后台线程持续采集 USB 摄像头最新一帧，缓存为 JPEG bytes 供 HTTP 取用"""

    def __init__(self, device, width, height, fps, quality=75):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.quality = int(quality)

        self.frame_cond = threading.Condition()
        self.latest_jpeg = None          # 最新一帧的 JPEG bytes
        self.frame_id = 0                # 帧序号，每产生一帧 +1

        # 统计
        self.capture_fps = 0.0
        self._frames = 0
        self._t0 = time.time()
        self._running = False
        self._cap = None

    def start(self):
        self._cap = cv2.VideoCapture(self.device)
        if not self._cap.isOpened():
            raise RuntimeError(f"无法打开摄像头: {self.device}")

        # 显式 YUYV（这颗 icspring 摄像头只支持 YUYV 4:2:2）
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('Y', 'U', 'Y', 'V'))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_FPS, self.fps)

        # 读回实际值（摄像头可能不接受请求参数，回落到实际值）
        self.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = self._cap.get(cv2.CAP_PROP_FPS)

        self._running = True
        t = threading.Thread(target=self._capture_loop, daemon=True)
        t.start()
        print(f"[capture] 已启动 {self.device} 实际={self.width}x{self.height}@{self.fps:.1f}fps",
              flush=True)

    def _capture_loop(self):
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
        while self._running:
            ret, frame = self._cap.read()
            if not ret or frame is None:
                # 读取失败，短暂等待后重试，避免 busy loop
                time.sleep(0.01)
                continue

            ok, buf = cv2.imencode('.jpg', frame, encode_param)
            if not ok:
                continue
            jpg = buf.tobytes()

            with self.frame_cond:
                self.latest_jpeg = jpg
                self.frame_id += 1
                self.frame_cond.notify_all()

            # fps 统计（每 5s 打印一次）
            self._frames += 1
            now = time.time()
            if now - self._t0 > 5:
                self.capture_fps = self._frames / (now - self._t0)
                print(f"[capture] fps={self.capture_fps:.1f}", flush=True)
                self._frames = 0
                self._t0 = now

    def get_frame(self, last_id=-1, timeout=2.0):
        """等待新帧并返回 (jpeg_bytes, frame_id)。
        last_id 为上次拿到的帧序号；若当前 frame_id > last_id 则立即返回，
        否则阻塞等待新帧到达或超时。"""
        with self.frame_cond:
            if self.frame_id <= last_id:
                self.frame_cond.wait(timeout=timeout)
            return self.latest_jpeg, self.frame_id

    def stop(self):
        self._running = False
        if self._cap is not None:
            self._cap.release()


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>USB 摄像头实时画面</title>
<style>
  body { margin:0; background:#111; color:#eee; font-family: sans-serif;
         display:flex; flex-direction:column; align-items:center; }
  h2 { margin: 14px 0 6px; }
  .bar { font-size: 13px; color:#9bd; margin-bottom: 10px; }
  img { border: 2px solid #333; background:#000; max-width: 95vw; max-height: 80vh; }
  .btns { margin: 10px 0 24px; }
  button { padding: 6px 14px; margin: 0 6px; font-size: 14px; cursor: pointer; }
</style>
</head>
<body>
  <h2>USB 摄像头实时画面</h2>
  <div class="bar">MJPEG 流地址: /stream &nbsp;|&nbsp; 截图: /snapshot</div>
  <img id="cam" src="/stream" alt="若画面未显示，请检查摄像头是否被占用">
  <div class="btns">
    <button onclick="document.getElementById('cam').src='/stream?t='+Date.now()">重新连接</button>
    <button onclick="location.href='/snapshot'">保存截图</button>
  </div>
</body>
</html>
"""


def make_handler(cam: UsbCameraCapture):
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
                msg = (f"OK device={cam.device} {cam.width}x{cam.height} "
                       f"fps={cam.capture_fps:.1f}\n")
                self.wfile.write(msg.encode('utf-8'))
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
                self.send_header('Content-Type',
                                 'multipart/x-mixed-replace; boundary=frame')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.end_headers()
                last_id = -1
                try:
                    while True:
                        frame, last_id = cam.get_frame(last_id=last_id, timeout=3.0)
                        if not frame:
                            continue
                        self.wfile.write(b'--frame\r\n')
                        self.wfile.write(b'Content-Type: image/jpeg\r\n')
                        self.wfile.write(f'Content-Length: {len(frame)}\r\n\r\n'.encode())
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                except Exception:
                    return
                return

            # 未知路径
            self.send_response(404)
            self.end_headers()

        def log_message(self, fmt, *args):
            # 静默默认访问日志，仅保留错误
            if args and '404' in str(args[0]):
                super().log_message(fmt, *args)

    return Handler


def main():
    p = argparse.ArgumentParser(description='USB 摄像头 MJPEG 网络推流服务')
    p.add_argument('--device', default='/dev/video0', help='视频设备节点，默认 /dev/video0')
    p.add_argument('--port', type=int, default=8093, help='HTTP 端口，默认 8093')
    p.add_argument('--width', type=int, default=640, help='请求分辨率宽，默认 640')
    p.add_argument('--height', type=int, default=480, help='请求分辨率高，默认 480')
    p.add_argument('--fps', type=int, default=30, help='请求帧率，默认 30')
    p.add_argument('--quality', type=int, default=75,
                   help='JPEG 编码质量 1-100，默认 75（降质量可提升帧率）')
    args = p.parse_args()

    cam = UsbCameraCapture(args.device, args.width, args.height, args.fps, args.quality)
    try:
        cam.start()
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        return

    server = ThreadingHTTPServer(('0.0.0.0', args.port), make_handler(cam))
    print(f"[server] MJPEG 推流已就绪: http://<板端IP>:{args.port}/", flush=True)
    print(f"[server] 直拉流地址:        http://<板端IP>:{args.port}/stream", flush=True)
    print(f"[server] 健康检查:          http://<板端IP>:{args.port}/health", flush=True)
    print(f"[server] 按 Ctrl+C 退出", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] 正在退出...")
    finally:
        cam.stop()
        server.server_close()


if __name__ == '__main__':
    main()
