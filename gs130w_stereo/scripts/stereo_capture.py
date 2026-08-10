#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stereo_capture.py - 双目拍摄标定工具 (不做深度, 只拍左右眼图)

订阅 mipi_cam 的 /image_combine_jpeg (上下拼接 1280x2176, 上半=右眼 下半=左眼),
网页实时显示左右眼画面, 点"拍摄"把当前左右眼图像存盘,
供后续离线深度计算 + 人工标定 (每张图标注 左转/右转/直行), 用于矫正避障判断。

保存文件 (每次拍摄 4 个, 目录默认 /app/stereo_captures):
  <时间戳>_left_raw.jpg    左眼原始方向 (= stereonet 深度算法实际输入方向)
  <时间戳>_right_raw.jpg   右眼原始方向
  <时间戳>_left_view.jpg   左眼 180° 旋转 (人眼观看方向, 相机物理倒装)
  <时间戳>_right_view.jpg  右眼 180° 旋转
标定结果: <目录>/labels.csv  (ts,label,labeled_at)

用法 (推荐用 start_capture.sh 一键启动, 它会先起 mipi_cam):
  python3 stereo_capture.py --port 8095 --dir /app/stereo_captures
"""
import argparse
import csv
import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import CompressedImage

TOPIC_COMBINED = '/image_combine_jpeg'
LABELS = ('左转', '右转', '直行')


class StereoCaptureNode(Node):
    """订阅双目拼接图, 缓存最新帧, 按需解码切分左右眼"""

    def __init__(self):
        super().__init__('stereo_capture')
        sensor_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=2,
        )
        self.create_subscription(CompressedImage, TOPIC_COMBINED, self.cb, sensor_qos)
        self._cond = threading.Condition()
        self._raw = None            # 最新拼接 JPEG 字节
        self._frame_id = 0
        self.last_stamp = 0.0
        self.fps = 0.0
        self._count = 0
        self._t0 = time.time()
        # 解码缓存 (按 frame_id 失效)
        self._decoded_id = -1
        self._left_raw_img = None   # ndarray, 原始方向 (深度算法输入)
        self._right_raw_img = None
        self._left_view = None      # jpeg bytes, 180° 旋转后人眼方向
        self._right_view = None
        self.get_logger().info(f'订阅 {TOPIC_COMBINED}, 等待双目画面...')

    def cb(self, msg):
        with self._cond:
            self._raw = bytes(msg.data)
            self._frame_id += 1
            self.last_stamp = time.time()
            self._count += 1
            now = time.time()
            if now - self._t0 >= 5.0:
                self.fps = self._count / (now - self._t0)
                self._count = 0
                self._t0 = now
            self._cond.notify_all()

    def wait_new_frame(self, last_id: int, timeout: float = 2.0) -> int:
        with self._cond:
            if self._frame_id == last_id:
                self._cond.wait(timeout)
            return self._frame_id

    def get_frames(self):
        """返回 (left_raw, right_raw, left_view_jpg, right_view_jpg, frame_id)
        left/right_raw 为 ndarray 原始方向; view 为旋转后 JPEG 字节。无帧返回 None"""
        with self._cond:
            raw = self._raw
            fid = self._frame_id
            if raw is None:
                return None
            if fid == self._decoded_id:
                return (self._left_raw_img, self._right_raw_img,
                        self._left_view, self._right_view, fid)
        # 锁外解码 (10fps, 每帧只解一次)
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        h = img.shape[0]
        right_raw = img[:h // 2]       # 上半 = 右眼
        left_raw = img[h // 2:]        # 下半 = 左眼
        # 相机物理倒装 180°, 显示方向 = 旋转 180°
        left_view_img = cv2.flip(left_raw, -1)
        right_view_img = cv2.flip(right_raw, -1)
        ok_l, lb = cv2.imencode('.jpg', left_view_img,
                                [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        ok_r, rb = cv2.imencode('.jpg', right_view_img,
                                [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not (ok_l and ok_r):
            return None
        with self._cond:
            self._decoded_id = fid
            self._left_raw_img = left_raw
            self._right_raw_img = right_raw
            self._left_view = lb.tobytes()
            self._right_view = rb.tobytes()
        return left_raw, right_raw, lb.tobytes(), rb.tobytes(), fid

    def save_capture(self, out_dir: str) -> str:
        """把当前帧的左右眼图存盘 (raw 高质量 + view 旋转版), 返回时间戳 ID"""
        frames = self.get_frames()
        if frames is None:
            raise RuntimeError('还没有相机画面 (mipi_cam 未出图?)')
        left_raw, right_raw, _, _, _ = frames
        now = datetime.now()
        ts = now.strftime('%Y%m%d_%H%M%S_') + f'{int(now.microsecond / 1000):03d}'
        os.makedirs(out_dir, exist_ok=True)
        q = [int(cv2.IMWRITE_JPEG_QUALITY), 95]
        cv2.imwrite(os.path.join(out_dir, f'{ts}_left_raw.jpg'), left_raw, q)
        cv2.imwrite(os.path.join(out_dir, f'{ts}_right_raw.jpg'), right_raw, q)
        cv2.imwrite(os.path.join(out_dir, f'{ts}_left_view.jpg'),
                    cv2.flip(left_raw, -1), q)
        cv2.imwrite(os.path.join(out_dir, f'{ts}_right_view.jpg'),
                    cv2.flip(right_raw, -1), q)
        self.get_logger().info(f'拍摄保存: {ts} ({out_dir})')
        return ts


# ============ 标定结果 labels.csv ============
def load_labels(csv_path: str) -> dict:
    labels = {}
    if os.path.exists(csv_path):
        with open(csv_path, 'r', encoding='utf-8') as f:
            for row in csv.reader(f):
                if len(row) >= 2 and row[0] != 'ts':
                    labels[row[0]] = row[1]
    return labels


def save_label(csv_path: str, ts: str, label: str):
    labels = load_labels(csv_path)
    if label:
        labels[ts] = label
    else:
        labels.pop(ts, None)
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['ts', 'label', 'labeled_at'])
        for k in sorted(labels):
            w.writerow([k, labels[k], datetime.now().strftime('%Y-%m-%d %H:%M:%S')])


def list_captures(out_dir: str) -> list:
    """扫描目录里的拍摄记录 [{ts, label}]"""
    csv_path = os.path.join(out_dir, 'labels.csv')
    labels = load_labels(csv_path)
    items = []
    if os.path.isdir(out_dir):
        for name in sorted(os.listdir(out_dir), reverse=True):
            if name.endswith('_left_raw.jpg'):
                ts = name[:-len('_left_raw.jpg')]
                items.append({'ts': ts, 'label': labels.get(ts, '')})
    return items


# ============ HTML 页面 ============
PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>双目拍摄标定</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,'Microsoft YaHei',sans-serif; background:#0d1117;
  color:#c9d1d9; padding:12px; }
h1 { font-size:20px; color:#58a6ff; text-align:center; margin-bottom:10px; }
h2 { font-size:15px; color:#58a6ff; margin:14px 0 8px; }
.bar { display:flex; align-items:center; gap:10px; flex-wrap:wrap;
  max-width:1100px; margin:0 auto 10px; }
#cap { padding:10px 28px; font-size:16px; border-radius:8px; border:1px solid #3fb950;
  background:#1a3a2a; color:#3fb950; cursor:pointer; }
#cap:hover { background:#2a4a3a; }
#cap:disabled { opacity:.5; cursor:wait; }
#msg { font-size:13px; color:#8b949e; }
#stat { font-size:12px; color:#8b949e; margin-left:auto; }
.streams { display:grid; grid-template-columns:1fr 1fr; gap:8px;
  max-width:1100px; margin:0 auto; }
.streams .cell { text-align:center; }
.streams img { width:100%; border-radius:6px; border:1px solid #30363d;
  background:#000; }
.streams .lab { font-size:13px; color:#8b949e; margin-top:4px; }
#gallery { max-width:1100px; margin:0 auto; display:grid;
  grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:10px; }
.shot { background:#161b22; border:1px solid #30363d; border-radius:8px;
  padding:8px; }
.shot .imgs { display:grid; grid-template-columns:1fr 1fr; gap:4px; }
.shot img { width:100%; border-radius:4px; border:1px solid #21262d; cursor:pointer; }
.shot .meta { font-size:11px; color:#8b949e; margin:6px 0; word-break:break-all; }
.shot .btns { display:flex; gap:6px; }
.lbtn { flex:1; padding:5px 0; font-size:12px; border-radius:5px; cursor:pointer;
  border:1px solid #30363d; background:#21262d; color:#c9d1d9; }
.lbtn:hover { border-color:#58a6ff; }
.lbtn.cur { background:#1a2a3a; border-color:#58a6ff; color:#58a6ff;
  font-weight:bold; }
.hint { max-width:1100px; margin:6px auto 0; font-size:12px; color:#8b949e; }
</style>
</head>
<body>
<h1>📷 双目拍摄标定工具</h1>
<div class="bar">
  <button id="cap" onclick="capture()">📸 拍摄</button>
  <span id="msg">点击拍摄, 保存当前左右眼图像</span>
  <span id="stat">--</span>
</div>
<div class="streams">
  <div class="cell"><img src="/stream_left" alt="left"><div class="lab">左眼画面 (左相机)</div></div>
  <div class="cell"><img src="/stream_right" alt="right"><div class="lab">右眼画面 (右相机)</div></div>
</div>
<div class="hint">保存目录: <span id="dir"></span> | 每次拍摄存 4 个文件:
*_left_raw.jpg / *_right_raw.jpg (原始方向=深度算法输入) + *_left_view.jpg / *_right_view.jpg (人眼方向)。
拍完在下方给每张图标定正确决策 (左转/右转/直行), 结果存 labels.csv。</div>
<h2>已拍摄 <span id="cnt">0</span> 组</h2>
<div id="gallery"></div>
<script>
async function capture() {
  const btn = document.getElementById('cap');
  const msg = document.getElementById('msg');
  btn.disabled = true; msg.textContent = '拍摄中...';
  try {
    const r = await fetch('/api/capture', {method:'POST'});
    const d = await r.json();
    msg.textContent = d.ok ? ('已保存: ' + d.ts) : ('失败: ' + d.error);
  } catch(e) { msg.textContent = '失败: ' + e.message; }
  btn.disabled = false;
  loadList();
}
async function setLabel(ts, label) {
  await fetch('/api/label', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ts: ts, label: label})});
  loadList();
}
async function loadList() {
  const r = await fetch('/api/list');
  const d = await r.json();
  document.getElementById('cnt').textContent = d.items.length;
  document.getElementById('dir').textContent = d.dir;
  const g = document.getElementById('gallery');
  let html = '';
  d.items.forEach(it => {
    html += `<div class="shot">
      <div class="imgs">
        <img src="/captures/${it.ts}_left_view.jpg" title="左眼" onclick="window.open(this.src)">
        <img src="/captures/${it.ts}_right_view.jpg" title="右眼" onclick="window.open(this.src)">
      </div>
      <div class="meta">${it.ts}</div>
      <div class="btns">
        ${['左转','右转','直行'].map(l =>
          `<button class="lbtn ${it.label===l?'cur':''}"
            onclick="setLabel('${it.ts}','${it.label===l?'':l}')">${l}</button>`).join('')}
      </div>
    </div>`;
  });
  g.innerHTML = html || '<div style="color:#8b949e;font-size:13px">还没有拍摄记录</div>';
}
async function stat() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    document.getElementById('stat').textContent =
      d.online ? `相机在线 ${d.fps.toFixed(1)}fps` : '⚠ 无相机画面';
  } catch(e) {}
}
loadList(); stat(); setInterval(stat, 3000);
</script>
</body>
</html>"""


class CaptureHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    node: StereoCaptureNode = None
    out_dir: str = ''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    # ---------- 工具 ----------
    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict, code: int = 200):
        self._send(code, 'application/json; charset=utf-8',
                   __import__('json').dumps(data, ensure_ascii=False).encode('utf-8'))

    @property
    def node(self) -> StereoCaptureNode:
        return self.server.node

    @property
    def out_dir(self) -> str:
        return self.server.out_dir

    # ---------- GET ----------
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ('/', '/index.html'):
            self._send(200, 'text/html; charset=utf-8', PAGE_HTML.encode('utf-8'))
        elif path == '/stream_left':
            self._mjpeg('left')
        elif path == '/stream_right':
            self._mjpeg('right')
        elif path == '/snapshot_left':
            self._snapshot('left')
        elif path == '/snapshot_right':
            self._snapshot('right')
        elif path == '/api/status':
            age = time.time() - self.node.last_stamp if self.node.last_stamp else -1
            self._json({'online': 0 <= age < 2.0,
                        'fps': self.node.fps,
                        'frame_age': round(age, 2)})
        elif path == '/api/list':
            self._json({'dir': self.out_dir, 'items': list_captures(self.out_dir)})
        elif path.startswith('/captures/'):
            self._serve_file(path[len('/captures/'):])
        else:
            self.send_error(404)

    def _serve_file(self, name: str):
        name = os.path.basename(name)
        if not name.endswith('.jpg'):
            self.send_error(403)
            return
        fpath = os.path.join(self.out_dir, name)
        if not os.path.isfile(fpath):
            self.send_error(404)
            return
        with open(fpath, 'rb') as f:
            self._send(200, 'image/jpeg', f.read())

    def _snapshot(self, eye: str):
        frames = self.node.get_frames()
        if frames is None:
            self.send_error(503, 'no frame')
            return
        _, _, lv, rv, _ = frames
        self._send(200, 'image/jpeg', lv if eye == 'left' else rv)

    def _mjpeg(self, eye: str):
        self.send_response(200)
        self.send_header('Content-Type',
                         'multipart/x-mixed-replace; boundary=frame')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()
        last_id = -1
        try:
            while True:
                fid = self.node.wait_new_frame(last_id, timeout=3.0)
                frames = self.node.get_frames()
                if frames is None:
                    continue
                _, _, lv, rv, cur_id = frames
                last_id = cur_id if fid != last_id else last_id
                jpg = lv if eye == 'left' else rv
                self.wfile.write(b'--frame\r\n')
                self.wfile.write(b'Content-Type: image/jpeg\r\n')
                self.wfile.write(f'Content-Length: {len(jpg)}\r\n\r\n'.encode())
                self.wfile.write(jpg)
                self.wfile.write(b'\r\n')
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------- POST ----------
    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/capture':
            try:
                ts = self.node.save_capture(self.out_dir)
                self._json({'ok': True, 'ts': ts})
            except Exception as e:
                self._json({'ok': False, 'error': str(e)})
        elif path == '/api/label':
            try:
                cl = int(self.headers.get('Content-Length', 0))
                body = __import__('json').loads(self.rfile.read(cl) or b'{}')
                ts = str(body.get('ts', '')).strip()
                label = str(body.get('label', '')).strip()
                if not ts:
                    self._json({'ok': False, 'error': 'ts 为空'}, 400)
                    return
                if label and label not in LABELS:
                    self._json({'ok': False, 'error': f'label 必须是 {LABELS}'}, 400)
                    return
                save_label(os.path.join(self.out_dir, 'labels.csv'), ts, label)
                self._json({'ok': True})
            except Exception as e:
                self._json({'ok': False, 'error': str(e)})
        else:
            self.send_error(404)


def main():
    parser = argparse.ArgumentParser(description='双目拍摄标定工具')
    parser.add_argument('--port', type=int, default=8095, help='HTTP 端口')
    parser.add_argument('--dir', default='/app/stereo_captures', help='图片保存目录')
    args = parser.parse_args()

    os.makedirs(args.dir, exist_ok=True)

    rclpy.init()
    node = StereoCaptureNode()
    spin_t = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spin_t.start()

    server = CaptureHTTPServer(('0.0.0.0', args.port), Handler)
    server.node = node
    server.out_dir = args.dir

    board_ip = os.popen('hostname -I 2>/dev/null').read().strip().split()
    board_ip = board_ip[0] if board_ip else '127.0.0.1'
    print('=' * 50)
    print(' 双目拍摄标定工具')
    print(f' 访问: http://{board_ip}:{args.port}')
    print(f' 保存目录: {args.dir}')
    print(f' 标定文件: {os.path.join(args.dir, "labels.csv")}')
    print('=' * 50, flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
