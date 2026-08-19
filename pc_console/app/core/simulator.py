# -*- coding: utf-8 -*-
"""simulator.py - 板端模拟数据源（演示模式）

在无法连接真实机器狗板端时，为上位机提供一套完整的模拟数据：
  - 组件/端口/视频流状态的动态模拟
  - 各路视频画面的实时合成（用 QPainter 绘制仿真图像）
  - 避障状态机的动态模拟
  - 大模型对话的模拟回复（含动作序列）
  - 日志内容模拟

演示模式用于：软件功能演示、用户手册截图、比赛答辩展示与开发调试。

本模块实现与 ApiClient 相同的方法签名，
界面层无需感知数据来自真实板端还是模拟器。
"""

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPen

from ..core.models import (AvoidStatus, ComponentStatus, SystemStatus,
                           UdpPortStatus, VideoStreamStatus)

# 演示模式模拟的组件清单（与板端 integrated_system 保持一致）
_DEMO_COMPONENTS = [
    "运动仲裁器", "双目深度+AI", "运动中枢 sit.py", "IMU 节点",
    "WebSocket 桥", "ROS/UDP 桥", "双目避障", "手势控制", "语音助手",
]


class DemoBoard:
    """板端模拟器：提供与 ApiClient 一致的方法签名"""

    def __init__(self, board_host: str = "192.168.1.10"):
        self.board_host = board_host
        self._start_time = time.time()
        # 避障演示状态
        self._avoid_mode = True
        self._avoid_phase = 0
        # 对话历史（用于模拟多轮对话）
        self._chat_history = []

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def get_status(self) -> dict:
        """模拟 GET /api/status：大部分组件在线，个别组件随机抖动"""
        elapsed = time.time() - self._start_time
        components = []
        for index, name in enumerate(_DEMO_COMPONENTS):
            # 第 5 个组件（WebSocket 桥）每 40 秒模拟一次离线抖动
            flaky = (index == 4) and (int(elapsed / 20) % 2 == 1)
            components.append({"name": name, "running": not flaky})

        udp_ports = [
            {"port": 5005, "desc": "仲裁器", "listening": True},
            {"port": 5006, "desc": "sit.py", "listening": True},
        ]
        video_streams = [
            {"port": 8071, "desc": "右眼", "online": True},
            {"port": 8072, "desc": "左眼", "online": True},
            {"port": 8073, "desc": "深度图", "online": True},
            {"port": 8093, "desc": "YOLO检测", "online": True},
            {"port": 8094, "desc": "手势识别", "online": True},
        ]
        return {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "board_ip": self.board_host,
            "components": components,
            "udp_ports": udp_ports,
            "video_streams": video_streams,
        }

    # ------------------------------------------------------------------
    # 运动控制（演示模式下仅记录，返回成功）
    # ------------------------------------------------------------------
    def send_action(self, action: str) -> dict:
        return {"ok": True, "message": f"已发送: {action} (演示)"}

    def send_move(self, forward: float, turn: float, source: str = "remote") -> dict:
        return {"ok": True,
                "message": f"follow_control fwd={forward:.2f} turn={turn:.2f} (演示)"}

    # ------------------------------------------------------------------
    # 避障监测：状态机循环演示
    # ------------------------------------------------------------------
    def get_avoid_status(self) -> dict:
        # 8 秒一个周期: 巡航 → 检测左障 → 右转 → 巡航
        phases = [
            ("IDLE", "clear", 0.0),
            ("IDLE", "left", 0.6),     # 左前方出现障碍
            ("STOP", "left", 0.8),
            ("BACK", "left", 1.0),
            ("TURN_RIGHT", "left", 1.2),  # 向右转躲避左障
            ("IDLE", "clear", 0.1),
        ]
        elapsed = time.time() - self._start_time
        phase_index = int(elapsed / 2.0) % len(phases)
        state, decision, ratio = phases[phase_index]

        t = elapsed
        left = 2.5 - 2.0 * abs(math.sin(t * 0.4))
        center = 2.8 - 2.2 * abs(math.sin(t * 0.3 + 1.0))
        right = 2.6 - 2.0 * abs(math.sin(t * 0.35 + 2.0))

        return {
            "node_online": True,
            "avoid_mode": self._avoid_mode,
            "avoid_state": state,
            "left": round(left, 2),
            "center": round(center, 2),
            "right": round(right, 2),
            "left_ratio": round(ratio, 3),
            "center_ratio": round(max(0.0, ratio - 0.4), 3),
            "right_ratio": round(max(0.0, ratio - 0.5), 3),
            "decision": decision,
            "usb_side": "left" if decision == "left" else "",
        }

    def set_avoid_mode(self, mode: str) -> dict:
        self._avoid_mode = (mode == "on")
        text = "开启自动巡航" if mode == "on" else "关闭(被动监测)"
        return {"ok": True, "message": f"避障模式已切换: {text} (演示)"}

    # ------------------------------------------------------------------
    # 日志模拟
    # ------------------------------------------------------------------
    def get_log(self, log_key: str) -> dict:
        now = time.strftime("%H:%M:%S")
        lines = [
            f"[{now}] [demo] 日志源 {log_key} 运行正常",
            f"[{now}] [demo] 心跳正常 | CPU 43% | 内存 61%",
            f"[{now}] [demo] 最近一次指令处理完成 (耗时 0.0{s}ms)".format(s=random.randint(1, 9)),
        ]
        return {"content": "\n".join(lines)}

    # ------------------------------------------------------------------
    # 系统管理（演示模式返回模拟输出）
    # ------------------------------------------------------------------
    def sys_command(self, command: str) -> dict:
        return {"ok": True, "output": f"(演示) 系统 {command} 命令已执行"}

    def restart_stereo(self) -> dict:
        return {"ok": True, "output": "(演示) 双目深度链路重启中，约需 1 分钟"}

    def restart_robot(self) -> dict:
        return {"ok": True, "output": "(演示) 运动中枢重启完成"}

    # ------------------------------------------------------------------
    # 对话模拟
    # ------------------------------------------------------------------
    def chat(self, text: str, speak: bool = False) -> dict:
        """模拟大模型回复：视觉问句返回场景描述，其余返回动作序列"""
        self._chat_history.append(text)

        # 视觉问句检测（与板端 vision_assistant 触发词逻辑一致）
        vision_keywords = ("看到", "看什么", "看见", "前面有", "摄像头")
        if any(kw in text for kw in vision_keywords):
            return {
                "ok": True,
                "vision": True,
                "actions": [],
                "reply": "我看到正前方有一张木桌，桌上放着一个透明水瓶和一台笔记本电脑，"
                         "大约距离 1.2 米。(演示模式回复)",
            }

        # 动作指令：根据关键词生成动作序列
        actions = []
        if "坐下" in text:
            actions.append({"action": "sit", "duration": 2})
        if "站" in text or "起来" in text:
            actions.append({"action": "stand", "duration": 1.5})
        if "前进" in text:
            actions.append({"action": "forward", "duration": 2})
        if "后退" in text:
            actions.append({"action": "backward", "duration": 1})
        if "左转" in text:
            actions.append({"action": "turn_left", "duration": 1})
        if "右转" in text:
            actions.append({"action": "turn_right", "duration": 1})
        if "走" in text and not actions:
            actions.append({"action": "walk", "duration": 3})

        if actions:
            reply = f"好的，我马上执行：{' → '.join(a['action'] for a in actions)}。(演示模式回复)"
        else:
            reply = (f"我收到你的消息了：「{text}」。你可以让我坐下、站立、前进、"
                     f"后退、左转或右转，也可以问我看到了什么。(演示模式回复)")
        return {"ok": True, "vision": False, "actions": actions, "reply": reply}


# ----------------------------------------------------------------------
# 视频画面合成（演示模式的各路视频帧）
# ----------------------------------------------------------------------
class DemoFrameFactory:
    """用 QPainter 实时合成演示视频帧

    各路画面特征:
      - 左/右眼: 相同场景存在视差（水平偏移），模拟双目成像
      - 深度图:   以距离伪彩（近红远蓝）呈现场景深度
      - YOLO:    场景图 + 检测框与类别标签
      - 手势:    场景图 + 手部关键点与骨架连线
    """

    WIDTH = 480
    HEIGHT = 270

    def __init__(self):
        self._t0 = time.time()
        # 模拟场景中的"移动障碍物"位置（水平往返运动）
        self._objects = [
            {"x": 0.30, "y": 0.55, "w": 0.18, "h": 0.30, "label": "person", "speed": 0.10},
            {"x": 0.65, "y": 0.62, "w": 0.12, "h": 0.20, "label": "bottle", "speed": -0.07},
            {"x": 0.82, "y": 0.45, "w": 0.10, "h": 0.28, "label": "chair", "speed": 0.05},
        ]

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------
    def make_frame(self, stream_index: int) -> QImage:
        """生成指定路的演示帧: 0右眼 1左眼 2深度 3YOLO 4手势"""
        if stream_index == 0:
            return self._make_eye_frame(shift=-14)
        if stream_index == 1:
            return self._make_eye_frame(shift=14)
        if stream_index == 2:
            return self._make_depth_frame()
        if stream_index == 3:
            return self._make_yolo_frame()
        return self._make_gesture_frame()

    # ------------------------------------------------------------------
    # 场景物体运动计算
    # ------------------------------------------------------------------
    def _object_rects(self) -> list:
        """计算当前时刻各模拟物体的位置（0~1 归一化坐标）"""
        elapsed = time.time() - self._t0
        rects = []
        for obj in self._objects:
            x = obj["x"] + obj["speed"] * math.sin(elapsed * 0.6)
            x = min(0.9, max(0.02, x))
            rects.append({
                "x": x, "y": obj["y"], "w": obj["w"], "h": obj["h"],
                "label": obj["label"],
            })
        return rects

    # ------------------------------------------------------------------
    # 左右眼画面
    # ------------------------------------------------------------------
    def _make_eye_frame(self, shift: int) -> QImage:
        """合成相机原始画面：地面渐变 + 视差偏移的障碍物 + 通道噪点"""
        image = QImage(self.WIDTH, self.HEIGHT, QImage.Format_RGB32)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)

        # 背景渐变（上=远景墙，下=地面）
        gradient = QLinearGradient(0, 0, 0, self.HEIGHT)
        gradient.setColorAt(0.0, QColor(38, 42, 58))
        gradient.setColorAt(0.55, QColor(70, 74, 88))
        gradient.setColorAt(0.56, QColor(96, 92, 84))
        gradient.setColorAt(1.0, QColor(60, 58, 52))
        painter.fillRect(image.rect(), QBrush(gradient))

        # 障碍物（带双目视差水平偏移）
        for obj in self._object_rects():
            x = (obj["x"] + shift / self.WIDTH) * self.WIDTH
            rect = QRectF(int(x), obj["y"] * self.HEIGHT,
                          obj["w"] * self.WIDTH, obj["h"] * self.HEIGHT)
            painter.fillRect(rect, QColor(150, 120, 90))
            painter.setPen(QPen(QColor(90, 70, 50), 2))
            painter.drawRect(rect)

        painter.setPen(QPen(QColor(0, 0, 0, 40)))
        for _ in range(300):  # 传感器噪点
            nx = random.randint(0, self.WIDTH - 1)
            ny = random.randint(0, self.HEIGHT - 1)
            painter.drawPoint(nx, ny)

        # 画面标注
        label = "RIGHT CAM" if shift < 0 else "LEFT CAM"
        painter.setPen(QPen(QColor(120, 255, 160), 2))
        painter.drawText(12, 22, f"{label}  {time.strftime('%H:%M:%S')}")
        painter.end()
        return image

    # ------------------------------------------------------------------
    # 深度伪彩画面
    # ------------------------------------------------------------------
    def _make_depth_frame(self) -> QImage:
        """合成深度伪彩画面：距离越近颜色越暖（近红远蓝）"""
        image = QImage(self.WIDTH, self.HEIGHT, QImage.Format_RGB32)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)

        # 深度背景：垂直方向由近(下暖)到远(上冷)
        gradient = QLinearGradient(0, self.HEIGHT, 0, 0)
        gradient.setColorAt(0.0, QColor(210, 60, 40))
        gradient.setColorAt(0.4, QColor(220, 170, 40))
        gradient.setColorAt(0.75, QColor(40, 160, 220))
        gradient.setColorAt(1.0, QColor(30, 40, 120))
        painter.fillRect(image.rect(), QBrush(gradient))

        # 障碍物按距离映射颜色（模拟近处检测）
        for obj in self._object_rects():
            distance = 1.0 + obj["y"]  # y 越大越近
            if distance < 1.4:
                color = QColor(255, 80, 40)
            elif distance < 1.7:
                color = QColor(250, 160, 30)
            else:
                color = QColor(90, 190, 230)
            rect = QRectF(obj["x"] * self.WIDTH, obj["y"] * self.HEIGHT,
                          obj["w"] * self.WIDTH, obj["h"] * self.HEIGHT)
            painter.fillRect(rect, color)
            painter.setPen(QPen(QColor(255, 255, 255, 200), 1))
            painter.drawRect(rect)

        # 三分区参考线（左/中/右判定区）
        painter.setPen(QPen(QColor(255, 255, 255, 120), 1, Qt.DashLine))
        painter.drawLine(int(self.WIDTH / 3), 0, int(self.WIDTH / 3), self.HEIGHT)
        painter.drawLine(int(self.WIDTH * 2 / 3), 0, int(self.WIDTH * 2 / 3), self.HEIGHT)

        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawText(12, 22, f"DEPTH  {time.strftime('%H:%M:%S')}")
        painter.end()
        return image

    # ------------------------------------------------------------------
    # YOLO 检测画面
    # ------------------------------------------------------------------
    def _make_yolo_frame(self) -> QImage:
        """合成 YOLO 目标检测画面：场景 + 置信度检测框"""
        base = self._make_eye_frame(shift=0)
        painter = QPainter(base)
        painter.setRenderHint(QPainter.Antialiasing)

        colors = [QColor(0, 220, 120), QColor(255, 180, 0), QColor(80, 160, 255)]
        for i, obj in enumerate(self._object_rects()):
            rect = QRectF(obj["x"] * self.WIDTH, obj["y"] * self.HEIGHT,
                          obj["w"] * self.WIDTH, obj["h"] * self.HEIGHT)
            painter.setPen(QPen(colors[i % len(colors)], 2))
            painter.drawRect(rect)
            conf = 0.75 + 0.2 * abs(math.sin(time.time() + i))
            text = f"{obj['label']} {conf:.2f}"
            painter.fillRect(rect.left(), rect.top() - 16, 8 * len(text) + 10, 15, colors[i % len(colors)])
            painter.setPen(QPen(QColor(0, 0, 0)))
            painter.drawText(int(rect.left()) + 4, int(rect.top()) - 4, text)

        painter.setPen(QPen(QColor(0, 220, 120), 2))
        painter.drawText(12, 22, f"YOLOv5  {time.strftime('%H:%M:%S')}")
        painter.end()
        return base

    # ------------------------------------------------------------------
    # 手势识别画面
    # ------------------------------------------------------------------
    def _make_gesture_frame(self) -> QImage:
        """合成手势识别画面：场景 + 21 点手部关键点骨架"""
        base = self._make_eye_frame(shift=0)
        painter = QPainter(base)
        painter.setRenderHint(QPainter.Antialiasing)

        elapsed = time.time() - self._t0
        # 手掌中心随时间轻微摆动
        cx = self.WIDTH * 0.5 + 18 * math.sin(elapsed * 0.8)
        cy = self.HEIGHT * 0.55 + 8 * math.cos(elapsed * 1.1)
        scale = 30.0

        # MediaPipe 21 关键点连接关系（简化骨架）
        connections = [
            (0, 1), (1, 2), (2, 3), (3, 4),          # 拇指
            (0, 5), (5, 6), (6, 7), (7, 8),          # 食指
            (5, 9), (9, 10), (10, 11), (11, 12),     # 中指
            (9, 13), (13, 14), (14, 15), (15, 16),   # 无名指
            (13, 17), (17, 18), (18, 19), (19, 20),  # 小指
            (0, 17),                                  # 掌根
        ]

        # 生成 21 个关键点坐标（张开手掌的姿态）
        points = []
        finger_offsets = [
            (-0.35, -0.15), (-0.15, -0.55), (0.02, -0.62), (0.10, -0.55),
            (-0.08, -0.15), (0.02, -0.68), (0.10, -0.78), (0.17, -0.68),
            (0.12, -0.15), (0.20, -0.70), (0.27, -0.80), (0.33, -0.70),
            (0.30, -0.15), (0.36, -0.62), (0.42, -0.70), (0.47, -0.62),
            (0.47, -0.15), (0.52, -0.45), (0.55, -0.52), (0.56, -0.45),
            (0.56, -0.15),
        ]
        for fx, fy in finger_offsets:
            jitter_x = 1.5 * math.sin(elapsed * 2.0 + len(points))
            jitter_y = 1.5 * math.cos(elapsed * 1.7 + len(points))
            points.append(QPointF(cx + fx * scale + jitter_x, cy + fy * scale + jitter_y))

        # 绘制骨架
        painter.setPen(QPen(QColor(0, 240, 255), 2))
        for a, b in connections:
            painter.drawLine(points[a], points[b])
        # 绘制关键点
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.setBrush(QBrush(QColor(255, 60, 90)))
        for pt in points:
            painter.drawEllipse(pt, 3.0, 3.0)

        # 手势判定结果（周期切换）
        gestures = ["PALM 张开手掌", "FIST 握拳", "VICTORY 胜利", "THUMB_UP 点赞"]
        gesture = gestures[int(elapsed / 3) % len(gestures)]
        painter.setPen(QPen(QColor(0, 255, 157), 2))
        painter.drawText(12, 22, f"Gesture: {gesture}")
        painter.drawText(12, self.HEIGHT - 12, f"conf 0.9{int(elapsed) % 9}  {time.strftime('%H:%M:%S')}")
        painter.end()
        return base


def parse_status(data: dict) -> SystemStatus:
    """将 /api/status 原始 JSON 解析为 SystemStatus 数据模型"""
    status = SystemStatus(
        timestamp=data.get("timestamp", "--"),
        board_ip=data.get("board_ip", "--"),
    )
    for item in data.get("components", []):
        status.components.append(ComponentStatus(
            name=item.get("name", "?"), running=bool(item.get("running"))))
    for item in data.get("udp_ports", []):
        status.udp_ports.append(UdpPortStatus(
            port=int(item.get("port", 0)),
            desc=item.get("desc", ""),
            listening=bool(item.get("listening"))))
    for item in data.get("video_streams", []):
        status.video_streams.append(VideoStreamStatus(
            port=int(item.get("port", 0)),
            desc=item.get("desc", ""),
            online=bool(item.get("online"))))
    return status


def parse_avoid(data: dict) -> AvoidStatus:
    """将 /api/avoid_mode 原始 JSON 解析为 AvoidStatus 数据模型"""
    def _num(value):
        return float(value) if isinstance(value, (int, float)) else None

    return AvoidStatus(
        node_online=bool(data.get("node_online")),
        avoid_mode=bool(data.get("avoid_mode")),
        avoid_state=str(data.get("avoid_state") or ""),
        left=_num(data.get("left")),
        center=_num(data.get("center")),
        right=_num(data.get("right")),
        left_ratio=_num(data.get("left_ratio")),
        center_ratio=_num(data.get("center_ratio")),
        right_ratio=_num(data.get("right_ratio")),
        decision=str(data.get("decision") or ""),
        usb_side=str(data.get("usb_side") or ""),
    )
