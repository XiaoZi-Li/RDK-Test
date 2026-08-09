#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dashboard_lite.py - 轻量版监控面板 (不加载视频流, 降低 CPU 和带宽)

与 dashboard.py 的区别:
  - 不嵌入任何 MJPEG 视频流 (避免浏览器持续拉流占 CPU)
  - 只保留: 组件状态 / UDP端口 / 系统控制 / 运动控制 / 日志查看
  - 视频流仅显示在线状态, 不拉取画面
  - 页面更小, 刷新更快

用法:
  python3 dashboard_lite.py                 # 默认 8090 端口
  python3 dashboard_lite.py --port 8888
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

LOG_DIR = "/tmp/integrated_system"
DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))

COMPONENTS = [
    ("运动仲裁器", "motion_arbiter.py"),
    ("双目深度", "mipi_cam|stereonet_model_node"),
    ("运动中枢 sit.py", "/app/pydev_demo/puppypi_control/sit.py"),
    ("IMU 节点", "imu_node_ros2"),
    ("WebSocket 桥", "ws_bridge_node"),
    ("ROS/UDP 桥", "ros_udp_bridge"),
    ("双目避障", "stereo_avoidance_node.py"),
    ("手势控制", "gesture_control_lite.py"),
    ("语音助手", "voice_assistant.py"),
]

UDP_PORTS = [(5005, "仲裁器"), (5006, "sit.py")]

# 轻量模式: 视频流全部不启动 (省 CPU/带宽), 面板只显示说明
VIDEO_STREAMS = []


def check_process(pattern):
    try:
        for p in pattern.split("|"):
            r = subprocess.run(["pgrep", "-f", p], capture_output=True, text=True, timeout=2)
            if r.returncode == 0 and r.stdout.strip():
                return True
        return False
    except Exception:
        return False


def check_udp_port(port):
    try:
        r = subprocess.run(["ss", "-ulnp"], capture_output=True, text=True, timeout=2)
        return f":{port} " in r.stdout
    except Exception:
        return False


def check_tcp_port(port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        r = s.connect_ex(("127.0.0.1", port))
        s.close()
        return r == 0
    except Exception:
        return False


def get_board_ip():
    try:
        r = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=2)
        return r.stdout.strip().split()[0] if r.stdout.strip() else "127.0.0.1"
    except Exception:
        return "127.0.0.1"


def get_status():
    components = [{"name": n, "running": check_process(p)} for n, p in COMPONENTS]
    udp = [{"port": p, "desc": d, "listening": check_udp_port(p)} for p, d in UDP_PORTS]
    video = [{"port": p, "desc": d, "online": check_tcp_port(p)} for p, d in VIDEO_STREAMS]
    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "components": components,
        "udp_ports": udp,
        "video_streams": video,
        "board_ip": get_board_ip(),
    }


def tail_log(path, lines=50):
    if not os.path.exists(path):
        return f"日志文件不存在: {path}"
    try:
        r = subprocess.run(["tail", "-n", str(lines), path], capture_output=True, text=True, timeout=2)
        return r.stdout
    except Exception as e:
        return f"读取失败: {e}"


def send_udp_action(ip, port, action, source="dashboard"):
    payload = json.dumps({"action": action, "source": source}, ensure_ascii=False)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(payload.encode("utf-8"), (ip, port))
        s.close()
        return True, f"已发送: {action}"
    except Exception as e:
        return False, str(e)


# ============ LLM 对话控制 (与完整版 dashboard 同一套逻辑) ============
_llm = None
_llm_init_lock = threading.Lock()
_llm_call_lock = threading.Lock()    # LlmDialogue.chat 非线程安全, 串行调用
_action_lock = threading.Lock()      # 动作序列串行执行, 前一组没做完就排队等
_motion_cfg = {"arbiter_ip": "127.0.0.1", "arbiter_port": 5005,
               "move_duration_sec": 2.5, "discrete_wait_sec": 2.0}


def get_llm():
    """延迟初始化 LLM 对话管理器 (复用 voice_assistant 的配置与动作执行逻辑)"""
    global _llm
    with _llm_init_lock:
        if _llm is None:
            if DASHBOARD_DIR not in sys.path:
                sys.path.insert(0, DASHBOARD_DIR)
            cfg_path = os.path.join(DASHBOARD_DIR, "config.json")
            with open(cfg_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            _motion_cfg.update(config.get("motion", {}))
            from llm_dialogue import LlmDialogue
            _llm = LlmDialogue(config)
    return _llm


def run_actions_bg(actions):
    """后台线程执行动作序列, 与语音助手走同一仲裁通道 (source=voice)"""
    def _run():
        from voice_assistant import execute_action_sequence
        with _action_lock:
            execute_action_sequence(
                actions,
                _motion_cfg["arbiter_ip"],
                int(_motion_cfg["arbiter_port"]),
                move_duration=float(_motion_cfg["move_duration_sec"]),
                discrete_wait=float(_motion_cfg["discrete_wait_sec"]),
            )
    threading.Thread(target=_run, daemon=True).start()


def run_script(script, args=""):
    try:
        r = subprocess.run(f"{script} {args}", shell=True, capture_output=True, text=True, timeout=30)
        return True, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return False, "超时"
    except Exception as e:
        return False, str(e)


HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>机器狗监控 (Lite)</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Microsoft YaHei',sans-serif;background:#0d1117;color:#c9d1d9;padding:10px}
.header{text-align:center;padding:8px 0;margin-bottom:10px;border-bottom:1px solid #30363d}
.header h1{font-size:18px;color:#58a6ff}
.header .info{font-size:12px;color:#8b949e;margin-top:3px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px;max-width:1200px;margin:0 auto}
.card{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:10px}
.card h2{font-size:13px;color:#58a6ff;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #21262d}
.row{display:flex;align-items:center;justify-content:space-between;padding:3px 0;border-bottom:1px solid #21262d}
.row:last-child{border-bottom:none}
.dot{width:8px;height:8px;border-radius:50%;margin-right:6px;display:inline-block}
.dot.on{background:#3fb950;box-shadow:0 0 4px #3fb950}
.dot.off{background:#f85149}
.label{flex:1;font-size:12px}
.badge{font-size:10px;padding:1px 6px;border-radius:8px}
.badge.on{background:#1a3a2a;color:#3fb950}
.badge.off{background:#3a1a1a;color:#f85149}
.btns{display:flex;flex-wrap:wrap;gap:4px}
.btn{padding:5px 10px;border:1px solid #30363d;border-radius:4px;background:#21262d;color:#c9d1d9;font-size:12px;cursor:pointer}
.btn:hover{background:#30363d;border-color:#58a6ff}
.btn.green{background:#1a3a2a;border-color:#3fb950;color:#3fb950}
.btn.red{background:#3a1a1a;border-color:#f85149;color:#f85149}
.btn.blue{background:#1a2a3a;border-color:#58a6ff;color:#58a6ff}
.act{display:grid;grid-template-columns:repeat(4,1fr);gap:4px}
.act div{text-align:center;padding:6px;font-size:11px;border-radius:4px;cursor:pointer;border:1px solid #30363d;background:#21262d;color:#c9d1d9}
.act div:hover{background:#30363d;border-color:#58a6ff}
.log{background:#0d1117;border:1px solid #30363d;border-radius:4px;padding:6px;font-family:monospace;font-size:10px;max-height:250px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;color:#8b949e}
.ltab{display:flex;gap:3px;margin-bottom:4px;flex-wrap:wrap}
.ltab div{padding:2px 8px;font-size:11px;border-radius:3px;cursor:pointer;background:#21262d;border:1px solid #30363d;color:#8b949e}
.ltab div.act{background:#1a2a3a;color:#58a6ff;border-color:#58a6ff}
.msg{margin-top:6px;padding:4px 8px;border-radius:3px;font-size:11px;display:none}
.msg.show{display:block}
.msg.ok{background:#1a3a2a;color:#3fb950}
.msg.err{background:#3a1a1a;color:#f85149}
/* LLM 对话框 */
.chat-box{background:#0d1117;border:1px solid #30363d;border-radius:4px;padding:8px;height:220px;overflow-y:auto;margin-bottom:6px;display:flex;flex-direction:column;gap:5px}
.chat-msg{max-width:85%;padding:5px 9px;border-radius:7px;font-size:12px;line-height:1.5;white-space:pre-wrap;word-break:break-word}
.chat-msg.user{align-self:flex-end;background:#1a2a3a;color:#58a6ff;border:1px solid #264a6b}
.chat-msg.assistant{align-self:flex-start;background:#21262d;color:#c9d1d9;border:1px solid #30363d}
.chat-msg .actions-tag{display:block;margin-top:3px;font-size:10px;color:#3fb950}
.chat-input{display:flex;gap:5px}
.chat-input input{flex:1;padding:6px 9px;border-radius:5px;border:1px solid #30363d;background:#0d1117;color:#c9d1d9;font-size:12px;outline:none}
.chat-input input:focus{border-color:#58a6ff}
.chat-hint{font-size:10px;color:#8b949e;margin-top:5px}
.vid-note{font-size:12px;color:#8b949e;line-height:1.8;padding:6px 2px}
</style>
</head>
<body>
<div class="header">
  <h1>🐕 机器狗监控 (Lite)</h1>
  <div class="info"><span id="ip">IP: ...</span> | <span id="ts">--</span></div>
</div>
<div class="grid">
  <div class="card"><h2>组件状态</h2><div id="comp"></div></div>
  <div class="card"><h2>UDP 端口</h2><div id="udp"></div></div>
  <div class="card"><h2>视频流</h2>
    <div class="vid-note">轻量模式：所有视频流已关闭（不起 codec / websocket / MJPEG 桥 / 手势推流），以降低 CPU 和延迟。<br>需要画面请用完整版面板 <b>:8081</b>（需完整版启动）。</div>
  </div>
  <div class="card">
    <h2>系统控制</h2>
    <div class="btns" style="margin-bottom:6px">
      <button class="btn green" onclick="sys('start')">启动</button>
      <button class="btn red" onclick="sys('stop')">停止</button>
      <button class="btn blue" onclick="sys('restart')">重启</button>
    </div>
    <div class="btns" style="margin-bottom:6px">
      <button class="btn blue" onclick="sys2('stereo')">重启双目</button>
      <button class="btn blue" onclick="sys2('robot')">重启中枢</button>
    </div>
    <div class="btns">
      <button class="btn" onclick="rf()">刷新</button>
      <label style="font-size:11px;color:#8b949e;display:flex;align-items:center;gap:3px">
        <input type="checkbox" id="ar" checked onchange="tar()"> 自动(3s)
      </label>
    </div>
    <div id="sr" class="msg"></div>
  </div>
  <div class="card">
    <h2>运动控制</h2>
    <div class="act">
      <div onclick="act('forward')">前进</div>
      <div onclick="act('backward')">后退</div>
      <div onclick="act('turn_left')">左转</div>
      <div onclick="act('turn_right')">右转</div>
      <div onclick="act('sit')">坐下</div>
      <div onclick="act('stand')">站立</div>
      <div onclick="act('stop')">停止</div>
      <div onclick="act('walk')">行走</div>
    </div>
    <div id="ar2" class="msg"></div>
  </div>
  <div class="card" style="grid-column:span 2">
    <h2>💬 大模型对话控制</h2>
    <div class="chat-box" id="chat-box">
      <div class="chat-msg assistant">你好，我是小狗。输入文字指令即可控制我，比如「先坐下再站起来」「前进两秒然后左转」。</div>
    </div>
    <div class="chat-input">
      <input id="chat-text" type="text" placeholder="输入指令或聊天内容，回车发送..." autocomplete="off">
      <button class="btn blue" id="chat-send" onclick="sendChat()">发送</button>
    </div>
    <div class="chat-hint">与语音助手共用同一个 DeepSeek 模型和动作执行通道（source=voice），支持多动作序列和时长控制</div>
  </div>
  <div class="card" style="grid-column:span 2">
    <h2>日志</h2>
    <div class="ltab" id="lt"></div>
    <div class="log" id="lc">选择日志...</div>
  </div>
</div>
<script>
const IP=location.hostname;
let curLog='',timer=null;
async function rf(){
  try{
    const r=await fetch('/api/status');const d=await r.json();
    document.getElementById('ip').textContent='IP: '+d.board_ip;
    document.getElementById('ts').textContent=d.timestamp;
    let h='';d.components.forEach(c=>{h+=`<div class="row"><span class="dot ${c.running?'on':'off'}"></span><span class="label">${c.name}</span><span class="badge ${c.running?'on':'off'}">${c.running?'运行':'停止'}</span></div>`});
    document.getElementById('comp').innerHTML=h;
    h='';d.udp_ports.forEach(u=>{h+=`<div class="row"><span class="dot ${u.listening?'on':'off'}"></span><span class="label">UDP ${u.port} (${u.desc})</span><span class="badge ${u.listening?'on':'off'}">${u.listening?'监听':'未监听'}</span></div>`});
    document.getElementById('udp').innerHTML=h;
  }catch(e){}
}
async function sys(c){if(!confirm('确认'+c+'?'))return;show('sr','执行中...','');try{const r=await fetch('/api/sys/'+c,{method:'POST'});const d=await r.json();show('sr',d.output||d.error,d.ok?'ok':'err');setTimeout(rf,2000)}catch(e){show('sr',e.message,'err')}}
async function sys2(c){show('sr','重启中...','');try{const r=await fetch('/api/restart/'+c,{method:'POST'});const d=await r.json();show('sr',d.output||d.error,d.ok?'ok':'err');setTimeout(rf,3000)}catch(e){show('sr',e.message,'err')}}
async function act(a){show('ar2','发送:'+a,'');try{const r=await fetch('/api/action/'+a,{method:'POST'});const d=await r.json();show('ar2',d.message||d.error,d.ok?'ok':'err')}catch(e){show('ar2',e.message,'err')}}
function show(id,m,t){const e=document.getElementById(id);e.textContent=m;e.className='msg show '+t}
// LLM 对话
function appendChat(role,text){const box=document.getElementById('chat-box');const div=document.createElement('div');div.className='chat-msg '+role;div.textContent=text;box.appendChild(div);box.scrollTop=box.scrollHeight;return div}
async function sendChat(){
  const input=document.getElementById('chat-text');const btn=document.getElementById('chat-send');
  const text=input.value.trim();if(!text)return;
  appendChat('user',text);input.value='';btn.disabled=true;
  const thinking=appendChat('assistant','思考中...');
  try{
    const resp=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:text})});
    const data=await resp.json();
    if(data.ok){
      thinking.textContent=data.reply||'(无回复)';
      if(data.actions&&data.actions.length){
        const tag=document.createElement('span');tag.className='actions-tag';
        tag.textContent='⚡ 动作序列: '+data.actions.map(a=>a.action+(a.duration!=null?' '+a.duration+'s':'')).join(' → ');
        thinking.appendChild(tag);
      }
    }else{thinking.textContent='❌ '+(data.error||'请求失败')}
  }catch(e){thinking.textContent='❌ 网络错误: '+e.message}
  btn.disabled=false;input.focus();
}
document.getElementById('chat-text').addEventListener('keydown',function(e){if(e.key==='Enter')sendChat()});
const LF=[['arbiter','仲裁器'],['sit','中枢'],['start_v2','双目'],['start_avoidance','避障'],['robot_minimal','机器人'],['gesture_control','手势'],['voice_assistant','语音']];
function initLT(){let h='';LF.forEach(([k,n])=>{h+=`<div onclick="ll('${k}',this)">${n}</div>`});document.getElementById('lt').innerHTML=h}
async function ll(k,e){curLog=k;document.querySelectorAll('.ltab div').forEach(t=>t.classList.remove('act'));e.classList.add('act');document.getElementById('lc').textContent='加载中...';try{const r=await fetch('/api/log/'+k);const d=await r.json();document.getElementById('lc').textContent=d.content||'空';document.getElementById('lc').scrollTop=999999}catch(e){document.getElementById('lc').textContent='失败'}}
function tar(){if(document.getElementById('ar').checked){timer=setInterval(rf,3000)}else{clearInterval(timer)}}
initLT();rf();tar();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            self._html(HTML)
        elif p == "/api/status":
            self._json(get_status())
        elif p.startswith("/api/log/"):
            key = p.split("/api/log/")[1]
            m = {
                "arbiter": f"{LOG_DIR}/arbiter.log",
                "sit": f"{LOG_DIR}/sit.log",
                "start_v2": f"{LOG_DIR}/start_v2_lite.log",
                "start_avoidance": f"{LOG_DIR}/start_avoidance.log",
                "robot_minimal": f"{LOG_DIR}/robot_minimal.log",
                "gesture_control": f"{LOG_DIR}/gesture_control_lite.log",
                "voice_assistant": f"{LOG_DIR}/voice_assistant.log",
            }
            self._json({"content": tail_log(m.get(key, ""))})
        else:
            self.send_error(404)

    def do_POST(self):
        p = urlparse(self.path).path
        # 轻量面板控制独立的轻量系统 (不带视频流)
        if p == "/api/sys/start":
            ok, out = run_script("/app/integrated_system/start_all_lite.sh", "start")
            self._json({"ok": ok, "output": out})
        elif p == "/api/sys/stop":
            ok, out = run_script("/app/integrated_system/start_all_lite.sh", "stop")
            self._json({"ok": ok, "output": out})
        elif p == "/api/sys/restart":
            ok, out = run_script("/app/integrated_system/start_all_lite.sh", "restart")
            self._json({"ok": ok, "output": out})
        elif p == "/api/restart/stereo":
            ok, out = run_script("/app/gs130w_stereo/scripts/start_v2_lite.sh", "restart")
            self._json({"ok": ok, "output": out})
        elif p == "/api/restart/robot":
            ok, out = run_script("/app/integrated_system/start_robot_minimal.sh", "restart")
            self._json({"ok": ok, "output": out})
        elif p == "/api/chat":
            # LLM 对话控制: {"text": "..."} → {"reply", "actions"}
            cl = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(cl) if cl else b"{}"
            try:
                d = json.loads(body)
                text = str(d.get("text", "")).strip()
            except Exception:
                self._json({"ok": False, "error": "请求体不是合法 JSON"}, 400)
                return
            if not text:
                self._json({"ok": False, "error": "text 为空"}, 400)
                return
            try:
                llm = get_llm()
            except Exception as e:
                self._json({"ok": False, "error": f"LLM 初始化失败: {e}"})
                return
            try:
                with _llm_call_lock:
                    reply, actions = llm.chat(text)
            except Exception as e:
                self._json({"ok": False, "error": f"LLM 调用失败: {e}"})
                return
            if actions:
                run_actions_bg(actions)
            self._json({"ok": True, "reply": reply, "actions": actions})
        elif p.startswith("/api/action/"):
            action = p.split("/api/action/")[1]
            ok, msg = send_udp_action("127.0.0.1", 5005, action, "dashboard")
            self._json({"ok": ok, "message": msg})
        elif p == "/api/move":
            cl = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(cl) if cl else b"{}"
            try:
                d = json.loads(body)
                fwd = max(-1.0, min(1.0, float(d.get("forward", 0))))
                trn = max(-1.0, min(1.0, float(d.get("turn", 0))))
                src = d.get("source", "remote")
                payload = json.dumps({"mode": "follow_control", "forward": fwd, "turn": trn, "source": src})
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.sendto(payload.encode("utf-8"), ("127.0.0.1", 5005))
                s.close()
                self._json({"ok": True, "message": f"fwd={fwd} turn={trn}"})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})
        else:
            self.send_error(404)


def main():
    parser = argparse.ArgumentParser(description="轻量版监控面板")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    # 用 ThreadingHTTPServer: LLM 对话请求耗时数秒, 单线程会卡住状态刷新
    class S(ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    # 清理旧的 dashboard_lite 进程 (排除自己)
    try:
        my_pid = os.getpid()
        result = subprocess.run(
            ["pgrep", "-f", "dashboard_lite.py"],
            capture_output=True, text=True, timeout=2
        )
        for pid_str in result.stdout.strip().split("\n"):
            pid_str = pid_str.strip()
            if pid_str and pid_str != str(my_pid):
                try:
                    os.kill(int(pid_str), 9)
                except Exception:
                    pass
        time.sleep(0.3)
    except Exception:
        pass

    ip = get_board_ip()
    print(f"轻量监控面板: http://{ip}:{args.port}")
    server = S((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
