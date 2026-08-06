#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""双目避障状态 HTTP 桥接器

订阅 /stereo_avoidance/status (std_msgs/String, JSON 格式)，
在 8074 端口暴露 /status HTTP 接口，供浏览器页面轮询显示。
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """每个 HTTP 客户端一个线程"""
    daemon_threads = True
    allow_reuse_address = True


class StatusBridge(Node):
    def __init__(self, status_topic='/stereo_avoidance/status'):
        super().__init__('status_bridge')
        self.status_topic = status_topic
        self.lock = threading.Lock()
        self.latest = {
            'source': None,
            'left': None,
            'center': None,
            'right': None,
            'turn_lock': 0,
            'target_yaw': None,
            'integrated_yaw': None,
            'last_cmd': None,
            'stamp': 0.0,
        }
        self.create_subscription(String, status_topic, self.cb, 10)
        self.get_logger().info(f'Status bridge subscribed to {status_topic}')

    def cb(self, msg: String):
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError as e:
            self.get_logger().warn(f'Invalid JSON: {e}')
            return
        data['stamp'] = time.time()
        with self.lock:
            self.latest = data
        self.get_logger().debug(f'Status updated: {msg.data}')

    def get_latest(self):
        with self.lock:
            return dict(self.latest)


def make_handler(bridge: StatusBridge):
    class Handler(BaseHTTPRequestHandler):
        def _set_headers(self, code=200, content_type='application/json'):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.end_headers()

        def do_OPTIONS(self):
            self._set_headers()

        def do_GET(self):
            if self.path == '/health':
                self._set_headers(content_type='text/plain')
                self.wfile.write(b'OK\n')
                return

            if self.path == '/status':
                data = bridge.get_latest()
                age = time.time() - data.get('stamp', 0)
                # 超过 2 秒没有新数据，标记为 stale
                if age > 2.0:
                    data['_stale'] = True
                    data['_age_sec'] = round(age, 2)
                else:
                    data['_stale'] = False
                    data['_age_sec'] = round(age, 2)
                self._set_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
                return

            self._set_headers(404, content_type='text/plain')
            self.wfile.write(b'Not Found\n')

        def log_message(self, format, *args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8074)
    parser.add_argument('--topic', default='/stereo_avoidance/status')
    args = parser.parse_args()

    rclpy.init()
    bridge = StatusBridge(args.topic)

    spin_t = threading.Thread(target=rclpy.spin, args=(bridge,), daemon=True)
    spin_t.start()

    server = ThreadingHTTPServer(('0.0.0.0', args.port), make_handler(bridge))
    print(f'Status bridge ready: http://0.0.0.0:{args.port}/status <- {args.topic}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
