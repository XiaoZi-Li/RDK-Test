#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dashboard.py - 机器狗集成系统 Web 上位机监控面板

功能：
  - 实时显示各组件运行状态（进程/UDP端口/视频流）
  - 嵌入双目/深度/YOLO 视频流
  - 一键控制：启动/停止/重启全部、单独重启双目深度
  - 实时日志查看
  - 运动控制测试（手动发指令）

用法:
  python3 dashboard.py                    # 默认 8080 端口
  python3 dashboard.py --port 8888        # 自定义端口
  python3 dashboard.py --host 0.0.0.0     # 允许外部访问
"""
import argparse
import json
import os
import socket
import subprocess
import threading
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
import socket as _socket
from urllib.parse import urlparse, parse_qs

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = "/tmp/integrated_system"

# 组件定义：(显示名, 进程匹配模式, 类型)
COMPONENTS = [
    ("运动仲裁器", "motion_arbiter.py", "process"),
    ("双目深度+AI", "start_v2.sh|gs130w_ai_overlay|mipi_cam_dual", "process"),
    ("运动中枢 sit.py", "/app/pydev_demo/puppypi_control/sit.py", "process"),
    ("IMU 节点", "imu_node_ros2", "process"),
    ("WebSocket 桥", "ws_bridge_node", "process"),
    ("ROS/UDP 桥", "ros_udp_bridge", "process"),
    ("双目避障", "stereo_avoidance_node.py", "process"),
    ("YOLO 显示", "yolo_display.py", "process"),
    ("手势控制", "gesture_control.py", "process"),
    ("语音助手", "voice_assistant.py", "process"),
]

# UDP 端口检查
UDP_PORTS = [
    (5005, "仲裁器"),
    (5006, "sit.py"),
]

# 视频流端口
VIDEO_STREAMS = [
    (8071, "右眼"),
    (8072, "左眼"),
    (8073, "深度图"),
    (8093, "YOLO检测"),
    (8094, "手势识别"),
]


def check_process(pattern: str) -> bool:
    """检查进程是否存在"""
    try:
        # 用 | 分割多个模式
        for p in pattern.split("|"):
            result = subprocess.run(
                ["pgrep", "-f", p],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                return True
        return False
    except Exception:
        return False


def check_udp_port(port: int) -> bool:
    """检查 UDP 端口是否在监听"""
    try:
        result = subprocess.run(
            ["ss", "-ulnp"],
            capture_output=True, text=True, timeout=2
        )
        return f":{port} " in result.stdout
    except Exception:
        return False


def check_tcp_port(port: int) -> bool:
    """检查 TCP 端口是否在监听"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        result = s.connect_ex(("127.0.0.1", port))
        s.close()
        return result == 0
    except Exception:
        return False


def get_board_ip() -> str:
    """获取板子 IP"""
    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True, text=True, timeout=2
        )
        return result.stdout.strip().split()[0] if result.stdout.strip() else "127.0.0.1"
    except Exception:
        return "127.0.0.1"


def get_status() -> dict:
    """获取所有组件状态"""
    components = []
    for name, pattern, _ in COMPONENTS:
        running = check_process(pattern)
        components.append({"name": name, "running": running})

    udp = []
    for port, desc in UDP_PORTS:
        udp.append({"port": port, "desc": desc, "listening": check_udp_port(port)})

    video = []
    for port, desc in VIDEO_STREAMS:
        video.append({"port": port, "desc": desc, "online": check_tcp_port(port)})

    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "components": components,
        "udp_ports": udp,
        "video_streams": video,
        "board_ip": get_board_ip(),
    }


def tail_log(log_path: str, lines: int = 50) -> str:
    """读取日志末尾"""
    if not os.path.exists(log_path):
        return f"日志文件不存在: {log_path}"
    try:
        result = subprocess.run(
            ["tail", "-n", str(lines), log_path],
            capture_output=True, text=True, timeout=2
        )
        return result.stdout
    except Exception as e:
        return f"读取失败: {e}"


def send_udp_action(ip: str, port: int, action: str, source: str = "dashboard"):
    """发送运动控制指令"""
    payload = json.dumps({"action": action, "source": source}, ensure_ascii=False)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(payload.encode("utf-8"), (ip, port))
        sock.close()
        return True, f"已发送: {action} → {ip}:{port}"
    except Exception as e:
        return False, str(e)


def run_script(script: str, args: str = "") -> tuple:
    """运行脚本"""
    cmd = f"{script} {args}"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        return True, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "超时"
    except Exception as e:
        return False, str(e)


# ============ HTML 页面 ============
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>机器狗监控面板</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, 'Microsoft YaHei', sans-serif;
  background: #0d1117; color: #c9d1d9; min-height: 100vh;
  padding: 12px;
}
.header {
  text-align: center; padding: 12px 0; margin-bottom: 12px;
  border-bottom: 1px solid #30363d;
}
.header h1 { font-size: 22px; color: #58a6ff; }
.header .info { font-size: 13px; color: #8b949e; margin-top: 4px; }
.grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 12px; max-width: 1400px; margin: 0 auto;
}
.card {
  background: #161b22; border: 1px solid #30363d; border-radius: 8px;
  padding: 14px; overflow: hidden;
}
.card h2 {
  font-size: 15px; color: #58a6ff; margin-bottom: 10px;
  border-bottom: 1px solid #21262d; padding-bottom: 8px;
}
.status-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 5px 0; border-bottom: 1px solid #21262d;
}
.status-row:last-child { border-bottom: none; }
.dot {
  display: inline-block; width: 10px; height: 10px; border-radius: 50%;
  margin-right: 8px;
}
.dot.on { background: #3fb950; box-shadow: 0 0 6px #3fb950; }
.dot.off { background: #f85149; }
.label { flex: 1; font-size: 13px; }
.badge {
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
}
.badge.on { background: #1a3a2a; color: #3fb950; }
.badge.off { background: #3a1a1a; color: #f85149; }
.video-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
}
.video-item {
  text-align: center;
}
.video-item img {
  width: 100%; border-radius: 4px; border: 1px solid #30363d;
  background: #0d1117; min-height: 80px;
}
.video-item .label {
  font-size: 12px; color: #8b949e; margin-top: 4px;
}
.btn-group { display: flex; flex-wrap: wrap; gap: 6px; }
.btn {
  padding: 6px 14px; border: 1px solid #30363d; border-radius: 6px;
  background: #21262d; color: #c9d1d9; font-size: 13px; cursor: pointer;
  transition: all 0.15s;
}
.btn:hover { background: #30363d; border-color: #58a6ff; }
.btn.green { background: #1a3a2a; border-color: #3fb950; color: #3fb950; }
.btn.green:hover { background: #2a4a3a; }
.btn.red { background: #3a1a1a; border-color: #f85149; color: #f85149; }
.btn.red:hover { background: #4a2a2a; }
.btn.blue { background: #1a2a3a; border-color: #58a6ff; color: #58a6ff; }
.btn.blue:hover { background: #2a3a4a; }
.btn:disabled { opacity: 0.5; cursor: wait; }
.log-box {
  background: #0d1117; border: 1px solid #30363d; border-radius: 4px;
  padding: 8px; font-family: 'Cascadia Code', monospace; font-size: 11px;
  max-height: 300px; overflow-y: auto; white-space: pre-wrap;
  word-break: break-all; color: #8b949e;
}
.log-tabs { display: flex; gap: 4px; margin-bottom: 6px; flex-wrap: wrap; }
.log-tab {
  padding: 3px 10px; font-size: 12px; border-radius: 4px; cursor: pointer;
  background: #21262d; border: 1px solid #30363d; color: #8b949e;
}
.log-tab.active { background: #1a2a3a; color: #58a6ff; border-color: #58a6ff; }
.action-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px;
}
.action-btn {
  padding: 8px; text-align: center; font-size: 12px;
  border-radius: 6px; cursor: pointer; border: 1px solid #30363d;
  background: #21262d; color: #c9d1d9; transition: all 0.15s;
}
.action-btn:hover { background: #30363d; border-color: #58a6ff; }
.result-msg {
  margin-top: 8px; padding: 6px 10px; border-radius: 4px; font-size: 12px;
  display: none;
}
.result-msg.show { display: block; }
.result-msg.ok { background: #1a3a2a; color: #3fb950; }
.result-msg.err { background: #3a1a1a; color: #f85149; }
#refresh-indicator {
  font-size: 11px; color: #8b949e; margin-left: 8px;
}
</style>
</head>
<body>

<div class="header">
  <h1>🐕 机器狗集成监控面板</h1>
  <div class="info">
    <span id="board-ip">IP: ...</span> | 
    <span id="last-update">--</span>
    <span id="refresh-indicator"></span>
  </div>
</div>

<div class="grid">

  <!-- 组件状态 -->
  <div class="card">
    <h2>📊 组件状态</h2>
    <div id="components"></div>
  </div>

  <!-- UDP 端口 -->
  <div class="card">
    <h2>🔌 UDP 端口</h2>
    <div id="udp-ports"></div>
  </div>

  <!-- 系统控制 -->
  <div class="card">
    <h2>⚙️ 系统控制</h2>
    <div class="btn-group" style="margin-bottom:8px">
      <button class="btn green" onclick="sysCmd('start')">启动全部</button>
      <button class="btn red" onclick="sysCmd('stop')">停止全部</button>
      <button class="btn blue" onclick="sysCmd('restart')">重启全部</button>
    </div>
    <div class="btn-group" style="margin-bottom:8px">
      <button class="btn blue" onclick="restartStereo()">🔄 重启双目深度</button>
      <button class="btn blue" onclick="restartRobot()">🔄 重启运动中枢</button>
    </div>
    <div class="btn-group">
      <button class="btn" onclick="refreshStatus()">🔄 刷新状态</button>
      <label style="font-size:12px;color:#8b949e;display:flex;align-items:center;gap:4px">
        <input type="checkbox" id="auto-refresh" checked onchange="toggleAutoRefresh()"> 自动刷新(3s)
      </label>
    </div>
    <div id="sys-result" class="result-msg"></div>
  </div>

  <!-- 运动控制测试 -->
  <div class="card">
    <h2>🎮 运动控制测试</h2>
    <div class="action-grid">
      <div class="action-btn" onclick="sendAction('forward')">⬆️ 前进</div>
      <div class="action-btn" onclick="sendAction('backward')">⬇️ 后退</div>
      <div class="action-btn" onclick="sendAction('turn_left')">⬅️ 左转</div>
      <div class="action-btn" onclick="sendAction('turn_right')">➡️ 右转</div>
      <div class="action-btn" onclick="sendAction('sit')">🪑 坐下</div>
      <div class="action-btn" onclick="sendAction('stand')">🧍 站立</div>
      <div class="action-btn" onclick="sendAction('stop')">✋ 停止</div>
      <div class="action-btn" onclick="sendAction('walk')">🚶 行走</div>
    </div>
    <div id="action-result" class="result-msg"></div>
  </div>

  <!-- 视频流 -->
  <div class="card" style="grid-column: span 2">
    <h2>📹 视频流</h2>
    <div class="video-grid" id="video-grid"></div>
  </div>

  <!-- 日志查看 -->
  <div class="card" style="grid-column: span 2">
    <h2>📋 日志查看</h2>
    <div class="log-tabs" id="log-tabs"></div>
    <div class="log-box" id="log-content">选择日志标签查看...</div>
  </div>

</div>

<script>
const BOARD_IP = location.hostname;
let currentLog = '';
let autoRefresh = true;
let refreshTimer = null;

// 更新组件状态
async function refreshStatus() {
  try {
    const resp = await fetch('/api/status');
    const data = await resp.json();
    
    document.getElementById('board-ip').textContent = 'IP: ' + data.board_ip;
    document.getElementById('last-update').textContent = data.timestamp;
    
    // 组件
    let html = '';
    data.components.forEach(c => {
      html += `<div class="status-row">
        <span class="dot ${c.running?'on':'off'}"></span>
        <span class="label">${c.name}</span>
        <span class="badge ${c.running?'on':'off'}">${c.running?'运行中':'未运行'}</span>
      </div>`;
    });
    document.getElementById('components').innerHTML = html;
    
    // UDP
    html = '';
    data.udp_ports.forEach(u => {
      html += `<div class="status-row">
        <span class="dot ${u.listening?'on':'off'}"></span>
        <span class="label">UDP ${u.port} (${u.desc})</span>
        <span class="badge ${u.listening?'on':'off'}">${u.listening?'监听中':'未监听'}</span>
      </div>`;
    });
    document.getElementById('udp-ports').innerHTML = html;
    
    // 视频流
    html = '';
    data.video_streams.forEach(v => {
      const src = v.online ? `http://${BOARD_IP}:${v.port}` : '';
      const placeholder = v.online ? '' : '<div style="color:#f85149;font-size:12px;padding:20px">未在线</div>';
      html += `<div class="video-item">
        <img src="${src}" alt="${v.desc}" onerror="this.style.display='none';this.nextElementSibling.style.display='block'">
        <div style="display:none;color:#f85149;font-size:12px;padding:20px">连接失败</div>
        <div class="label">${v.desc} :${v.port} ${v.online?'✅':'❌'}</div>
      </div>`;
    });
    document.getElementById('video-grid').innerHTML = html;
    
  } catch(e) {
    document.getElementById('refresh-indicator').textContent = '⚠ 刷新失败';
  }
}

// 系统控制
async function sysCmd(cmd) {
  if(!confirm(`确认${cmd==='start'?'启动':cmd==='stop'?'停止':'重启'}全部组件？`)) return;
  showResult('sys-result', '正在执行...', '');
  try {
    const resp = await fetch(`/api/sys/${cmd}`, {method:'POST'});
    const data = await resp.json();
    showResult('sys-result', data.output || data.error, data.ok?'ok':'err');
    setTimeout(refreshStatus, 2000);
  } catch(e) {
    showResult('sys-result', e.message, 'err');
  }
}

async function restartStereo() {
  showResult('sys-result', '正在重启双目深度...', '');
  try {
    const resp = await fetch('/api/restart/stereo', {method:'POST'});
    const data = await resp.json();
    showResult('sys-result', data.output || data.error, data.ok?'ok':'err');
    setTimeout(refreshStatus, 3000);
  } catch(e) {
    showResult('sys-result', e.message, 'err');
  }
}

async function restartRobot() {
  showResult('sys-result', '正在重启运动中枢...', '');
  try {
    const resp = await fetch('/api/restart/robot', {method:'POST'});
    const data = await resp.json();
    showResult('sys-result', data.output || data.error, data.ok?'ok':'err');
    setTimeout(refreshStatus, 3000);
  } catch(e) {
    showResult('sys-result', e.message, 'err');
  }
}

// 运动控制
async function sendAction(action) {
  showResult('action-result', `发送: ${action}...`, '');
  try {
    const resp = await fetch(`/api/action/${action}`, {method:'POST'});
    const data = await resp.json();
    showResult('action-result', data.message || data.error, data.ok?'ok':'err');
  } catch(e) {
    showResult('action-result', e.message, 'err');
  }
}

function showResult(id, msg, type) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = 'result-msg show ' + type;
}

// 日志
const LOG_FILES = [
  ['arbiter', '仲裁器'],
  ['sit', '运动中枢'],
  ['start_v2', '双目深度'],
  ['start_avoidance', '避障'],
  ['robot_minimal', '机器人'],
  ['yolo_display', 'YOLO'],
  ['gesture_control', '手势'],
  ['voice_assistant', '语音助手'],
];

function initLogTabs() {
  let html = '';
  LOG_FILES.forEach(([key, name]) => {
    html += `<div class="log-tab" onclick="loadLog('${key}')">${name}</div>`;
  });
  document.getElementById('log-tabs').innerHTML = html;
}

async function loadLog(key) {
  currentLog = key;
  document.querySelectorAll('.log-tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('log-content').textContent = '加载中...';
  try {
    const resp = await fetch(`/api/log/${key}`);
    const data = await resp.json();
    document.getElementById('log-content').textContent = data.content || '空';
    document.getElementById('log-content').scrollTop = 999999;
  } catch(e) {
    document.getElementById('log-content').textContent = '加载失败: ' + e.message;
  }
}

// 自动刷新
function toggleAutoRefresh() {
  autoRefresh = document.getElementById('auto-refresh').checked;
  if(autoRefresh) {
    refreshTimer = setInterval(refreshStatus, 3000);
  } else {
    clearInterval(refreshTimer);
  }
}

// 初始化
initLogTabs();
refreshStatus();
toggleAutoRefresh();
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 静默日志

    def send_json(self, data: dict, code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_html(DASHBOARD_HTML)

        elif path == "/api/status":
            self.send_json(get_status())

        elif path.startswith("/api/log/"):
            log_key = path.split("/api/log/")[1]
            log_map = {
                "arbiter": f"{LOG_DIR}/arbiter.log",
                "sit": f"{LOG_DIR}/sit.log",
                "start_v2": f"{LOG_DIR}/start_v2.log",
                "start_avoidance": f"{LOG_DIR}/start_avoidance.log",
                "robot_minimal": f"{LOG_DIR}/robot_minimal.log",
                "yolo_display": f"{LOG_DIR}/yolo_display.log",
                "gesture_control": f"{LOG_DIR}/gesture_control.log",
                "voice_assistant": f"{LOG_DIR}/voice_assistant.log",
            }
            log_path = log_map.get(log_key, "")
            content = tail_log(log_path, 80) if log_path else "未知日志"
            self.send_json({"content": content})

        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/sys/start":
            ok, out = run_script("/app/integrated_system/start_all.sh", "start")
            self.send_json({"ok": ok, "output": out})

        elif path == "/api/sys/stop":
            ok, out = run_script("/app/integrated_system/start_all.sh", "stop")
            self.send_json({"ok": ok, "output": out})

        elif path == "/api/sys/restart":
            ok, out = run_script("/app/integrated_system/start_all.sh", "restart")
            self.send_json({"ok": ok, "output": out})

        elif path == "/api/restart/stereo":
            ok, out = run_script("/app/gs130w_stereo/scripts/start_v2.sh", "restart")
            self.send_json({"ok": ok, "output": out})

        elif path == "/api/restart/robot":
            ok, out = run_script("/app/integrated_system/start_robot_minimal.sh", "restart")
            self.send_json({"ok": ok, "output": out})

        elif path.startswith("/api/action/"):
            action = path.split("/api/action/")[1]
            ok, msg = send_udp_action("127.0.0.1", 5005, action, "dashboard")
            self.send_json({"ok": ok, "message": msg})

        elif path == "/api/move":
            # 持续运动控制 (遥控模式)
            # POST body: {"forward": 0.5, "turn": 0.1, "source": "remote"}
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b"{}"
            try:
                data = json.loads(body)
                fwd = float(data.get("forward", 0.0))
                trn = float(data.get("turn", 0.0))
                source = data.get("source", "remote")
                payload = json.dumps({
                    "mode": "follow_control",
                    "forward": max(-1.0, min(1.0, fwd)),
                    "turn": max(-1.0, min(1.0, trn)),
                    "source": source
                })
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.sendto(payload.encode("utf-8"), ("127.0.0.1", 5005))
                sock.close()
                self.send_json({"ok": True, "message": f"follow_control fwd={fwd} turn={trn}"})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})

        else:
            self.send_error(404)


def main():
    parser = argparse.ArgumentParser(description="机器狗监控面板")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    args = parser.parse_args()

    board_ip = get_board_ip()
    print("=" * 50)
    print(" 机器狗集成监控面板")
    print(f" 访问地址: http://{board_ip}:{args.port}")
    print(f" 本机访问: http://127.0.0.1:{args.port}")
    print("=" * 50)

    # 允许端口复用, 避免 "Address already in use"
    class ReuseHTTPServer(HTTPServer):
        allow_reuse_address = True

    # 先杀旧进程
    try:
        subprocess.run(["pkill", "-f", "dashboard.py"], timeout=2)
        time.sleep(0.5)
    except Exception:
        pass

    server = ReuseHTTPServer((args.host, args.port), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n退出")
        server.server_close()


if __name__ == "__main__":
    main()
