# 机器狗集成系统 - 上位机 API 接口文档

> 基地址: `http://<板子IP>:8080`
> 所有接口返回 JSON，编码 UTF-8

---

## 1. 获取系统状态

### GET /api/status

返回所有组件运行状态、UDP 端口、视频流、板子 IP。

**响应示例:**

```json
{
  "timestamp": "2026-08-07 18:50:14",
  "board_ip": "192.168.1.10",
  "components": [
    {"name": "运动仲裁器", "running": true},
    {"name": "双目深度+AI", "running": true},
    {"name": "运动中枢 sit.py", "running": true},
    {"name": "IMU 节点", "running": true},
    {"name": "WebSocket 桥", "running": true},
    {"name": "ROS/UDP 桥", "running": true},
    {"name": "双目避障", "running": true},
    {"name": "YOLO 显示", "running": true},
    {"name": "手势控制", "running": true},
    {"name": "语音助手", "running": true},
    {"name": "监控面板", "running": true}
  ],
  "udp_ports": [
    {"port": 5005, "desc": "仲裁器", "listening": true},
    {"port": 5006, "desc": "sit.py", "listening": true}
  ],
  "video_streams": [
    {"port": 8071, "desc": "右眼", "online": true},
    {"port": 8072, "desc": "左眼", "online": true},
    {"port": 8073, "desc": "深度图", "online": true},
    {"port": 8093, "desc": "YOLO检测", "online": true},
    {"port": 8094, "desc": "手势识别", "online": true}
  ]
}
```

**建议轮询间隔:** 2-3 秒

---

## 2. 运动控制

### 2.1 离散动作控制

#### POST /api/action/{action}

发送离散动作指令到运动仲裁器 (UDP 5005)，优先级为语音级。

**路径参数:**

| action | 说明 |
|---|---|
| `forward` | 前进 |
| `backward` | 后退 |
| `turn_left` | 左转 |
| `turn_right` | 右转 |
| `sit` | 坐下 |
| `stand` | 站立 |
| `stop` | 停止 |
| `walk` | 行走 |

**响应:**

```json
{"ok": true, "message": "已发送: forward → 127.0.0.1:5005"}
```

**示例:**

```bash
curl -X POST http://192.168.1.10:8080/api/action/forward
curl -X POST http://192.168.1.10:8080/api/action/stop
```

### 2.2 连续运动控制 (遥控模式)

#### POST /api/move

发送 follow_control 连续控制指令，适合遥控摇杆场景。
需要持续发送 (建议 5-10Hz)，停止发送后仲裁器 0.3s 自动降级。

**请求体:**

```json
{
  "forward": 0.5,    // 前进速度 [-1.0, 1.0], 正=前进, 负=后退
  "turn": 0.1,       // 转向速度 [-1.0, 1.0], 正=左转, 负=右转
  "source": "remote" // 来源标识 (可选, 默认 "remote")
}
```

**响应:**

```json
{"ok": true, "message": "follow_control fwd=0.5 turn=0.1"}
```

**示例:**

```bash
# 前进
curl -X POST http://192.168.1.10:8080/api/move \
  -H "Content-Type: application/json" \
  -d '{"forward": 0.5, "turn": 0.0}'

# 停止
curl -X POST http://192.168.1.10:8080/api/move \
  -H "Content-Type: application/json" \
  -d '{"forward": 0.0, "turn": 0.0}'
```

**运动控制优先级:** 避障(P0) > 语音(P1) > 手势/遥控(P2)

> 当避障系统检测到障碍物时，会自动覆盖遥控指令执行避障。

---

## 3. 系统控制

### 3.1 启动全部

#### POST /api/sys/start

```bash
curl -X POST http://192.168.1.10:8080/api/sys/start
```

**响应:**

```json
{"ok": true, "output": "...启动日志..."}
```

### 3.2 停止全部

#### POST /api/sys/stop

```bash
curl -X POST http://192.168.1.10:8080/api/sys/stop
```

### 3.3 重启全部

#### POST /api/sys/restart

```bash
curl -X POST http://192.168.1.10:8080/api/sys/restart
```

### 3.4 单独重启双目深度

#### POST /api/restart/stereo

当深度图出不来时使用，不影响运动中枢和语音助手。

```bash
curl -X POST http://192.168.1.10:8080/api/restart/stereo
```

### 3.5 单独重启运动中枢

#### POST /api/restart/robot

```bash
curl -X POST http://192.168.1.10:8080/api/restart/robot
```

---

## 4. 日志查看

### GET /api/log/{log_key}

返回指定日志末尾 80 行。

**路径参数:**

| log_key | 说明 |
|---|---|
| `arbiter` | 运动仲裁器日志 |
| `sit` | 运动中枢日志 |
| `start_v2` | 双目深度日志 |
| `start_avoidance` | 避障日志 |
| `robot_minimal` | 机器人系统日志 |
| `yolo_display` | YOLO 显示日志 |
| `gesture_control` | 手势控制日志 |
| `voice_assistant` | 语音助手日志 |

**响应:**

```json
{"content": "...日志内容..."}
```

**示例:**

```bash
curl http://192.168.1.10:8080/api/log/voice_assistant
```

---

## 5. 视频流

直接在 `<img>` 标签或 OpenCV 中引用：

| 流 | URL | 说明 |
|---|---|---|
| 右眼 | `http://<IP>:8071` | 双目右摄像头 |
| 左眼 | `http://<IP>:8072` | 双目左摄像头 |
| 深度图 | `http://<IP>:8073` | 视差/深度伪彩色图 |
| YOLO 检测 | `http://<IP>:8093/stream` | YOLO 目标检测标注画面 |
| 手势识别 | `http://<IP>:8094/stream` | 手势骨骼标注画面 |

**HTML 嵌入:**

```html
<img src="http://192.168.1.10:8093/stream" alt="YOLO">
```

**OpenCV 读取:**

```python
cap = cv2.VideoCapture("http://192.168.1.10:8093/stream")
```

**健康检查:**

```
GET http://<IP>:8093/health    → 200 OK
```

---

## 6. 运动仲裁器协议 (UDP)

如果上位机需要直接通过 UDP 控制机器狗 (不经过 HTTP API)：

### 6.1 离散动作

发送到 `127.0.0.1:5005` (仲裁器):

```json
{"action": "forward", "source": "remote"}
```

### 6.2 连续控制

发送到 `127.0.0.1:5005`:

```json
{"mode": "follow_control", "forward": 0.5, "turn": 0.1, "source": "remote"}
```

### 6.3 仲裁器优先级

| 优先级 | source | 说明 |
|---|---|---|
| P0 (最高) | `stereo_avoid` | 避障，检测到障碍时自动覆盖 |
| P1 | `voice` | 语音指令 (LLM 意图识别 / 快速匹配) |
| P2 (最低) | `gesture` / `remote` / `dashboard` | 手势 / 遥控 / 面板 |

- 高优先级通道活跃时，低优先级指令被忽略
- 各通道超时后自动降级 (避障 0.3s, 语音 1.0s, 手势 0.5s)
- 所有通道静默时，仲裁器发送 `stop`

---

## 7. 上位机开发建议

### 技术选型

- **Web 端**: Vue/React + WebSocket (轮询 /api/status)
- **桌面端**: Electron / Flutter / PyQt
- **手机端**: Flutter / React Native

### 核心功能

1. **状态监控面板**: 轮询 `/api/status`，显示组件状态灯
2. **视频墙**: 嵌入 5 路 MJPEG 流
3. **遥控手柄**: 摇杆 → `/api/move` (5-10Hz)
4. **快捷按钮**: 前进/后退/左转/右转/坐下/站立/停止
5. **日志查看器**: 选择日志源 → `/api/log/{key}`
6. **系统控制**: 启动/停止/重启 + 单独重启双目/中枢

### 遥控模式示例 (Python)

```python
import requests
import time

BASE = "http://192.168.1.10:8080"

# 持续前进 2 秒
for _ in range(20):
    requests.post(f"{BASE}/api/move", json={"forward": 0.5, "turn": 0.0})
    time.sleep(0.1)

# 停止
requests.post(f"{BASE}/api/move", json={"forward": 0.0, "turn": 0.0})
# 或
requests.post(f"{BASE}/api/action/stop")
```
