# -*- coding: utf-8 -*-
"""models.py - 状态数据模型定义

定义上位机与板端系统之间交互的数据结构，
包括组件运行状态、UDP 端口状态、视频流状态、
避障监测状态与对话消息等。所有模型均为纯数据类，
不依赖 Qt，可在任意线程中构造与传递。
"""

import time
from dataclasses import dataclass, field


# ----------------------------------------------------------------------
# 组件状态模型
# ----------------------------------------------------------------------
@dataclass
class ComponentStatus:
    """板端单个组件（进程）的运行状态"""
    name: str          # 组件显示名称，如"运动仲裁器"
    running: bool      # 是否在运行


@dataclass
class UdpPortStatus:
    """板端单个 UDP 端口的监听状态"""
    port: int          # 端口号
    desc: str          # 用途描述，如"仲裁器"
    listening: bool    # 是否处于监听状态


@dataclass
class VideoStreamStatus:
    """单路视频流的在线状态"""
    port: int          # 视频服务端口
    desc: str          # 显示名称，如"深度图"
    online: bool       # TCP 端口是否可达


@dataclass
class SystemStatus:
    """板端整体状态快照（对应 GET /api/status）"""
    timestamp: str = "--"                       # 板端时间戳
    board_ip: str = "--"                        # 板端 IP
    components: list = field(default_factory=list)   # ComponentStatus 列表
    udp_ports: list = field(default_factory=list)    # UdpPortStatus 列表
    video_streams: list = field(default_factory=list)  # VideoStreamStatus 列表

    def online_component_count(self) -> int:
        """统计处于运行状态的组件数量"""
        return sum(1 for c in self.components if c.running)

    def total_component_count(self) -> int:
        """组件总数"""
        return len(self.components)

    def all_video_offline(self) -> bool:
        """判断是否所有视频流均离线"""
        return all(not v.online for v in self.video_streams)


# ----------------------------------------------------------------------
# 避障监测模型
# ----------------------------------------------------------------------
@dataclass
class AvoidStatus:
    """双目避障子系统的实时状态（对应 GET /api/avoid_mode）"""
    node_online: bool = False    # 避障节点进程是否在线
    avoid_mode: bool = False     # True=自动巡航(控车) False=纯监测(不控车)
    avoid_state: str = ""        # 状态机阶段: IDLE/STOP/BACK/TURN_LEFT/TURN_RIGHT
    left: float = None           # 左区最近距离（米），无数据时为 None
    center: float = None         # 中区最近距离（米）
    right: float = None          # 右区最近距离（米）
    left_ratio: float = None     # 左区近像素占比（0~1）
    center_ratio: float = None   # 中区近像素占比
    right_ratio: float = None    # 右区近像素占比
    decision: str = ""           # 方位判定结果: clear/left/center/right/sensor_error
    usb_side: str = ""           # USB 语义检测到的障碍方位: left/center/right

    # 避障状态机的中文展示名
    STATE_NAMES = {
        "IDLE": "巡航/监测",
        "STOP": "停车",
        "BACK": "后退",
        "TURN_LEFT": "左转躲右障",
        "TURN_RIGHT": "右转躲左障",
    }

    # 方位判定的中文展示名
    DECISION_NAMES = {
        "left": "左前方障碍",
        "center": "正前方障碍",
        "right": "右前方障碍",
        "sensor_error": "深度数据异常",
    }

    def state_text(self) -> str:
        """状态机阶段的中文描述"""
        return self.STATE_NAMES.get(self.avoid_state, self.avoid_state or "-")

    def decision_text(self) -> str:
        """方位判定结果的中文描述；无障碍时返回空串"""
        if not self.decision or self.decision == "clear":
            return ""
        return self.DECISION_NAMES.get(self.decision, self.decision)

    def ratio_text(self) -> str:
        """近像素占比的可读文本，如 '左12.3% 中4.5% 右2.1%'"""
        parts = []
        for label, value in (("左", self.left_ratio),
                             ("中", self.center_ratio),
                             ("右", self.right_ratio)):
            if isinstance(value, (int, float)):
                parts.append(f"{label}{value * 100:.1f}%")
        return " ".join(parts)

    def distance_text(self) -> str:
        """三区最近距离的可读文本，如 '左0.8m 中1.2m 右2.5m'"""
        parts = []
        for label, value in (("左", self.left),
                             ("中", self.center),
                             ("右", self.right)):
            if isinstance(value, (int, float)):
                parts.append(f"{label}{value:.2f}m")
        return " ".join(parts)

    def usb_text(self) -> str:
        """USB 语义检测结果的中文描述"""
        if not self.usb_side:
            return ""
        names = {"left": "左侧有物", "right": "右侧有物", "center": "正前有物"}
        return "USB:" + names.get(self.usb_side, self.usb_side)


# ----------------------------------------------------------------------
# 对话消息模型
# ----------------------------------------------------------------------
@dataclass
class ChatMessage:
    """一条对话消息"""
    role: str                       # "user" / "assistant" / "error"
    text: str                       # 消息正文
    actions: list = field(default_factory=list)  # 动作序列 [{'action':..,'duration':..}]
    vision: bool = False            # 是否来自视觉问答（📷 标记）
    timestamp: str = ""             # 本地时间戳

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%H:%M:%S")

    def actions_text(self) -> str:
        """动作序列的可读文本，如 '坐下 2s → 站立 1.5s'"""
        parts = []
        for act in self.actions:
            if not isinstance(act, dict):
                continue
            name = str(act.get("action", ""))
            duration = act.get("duration")
            if isinstance(duration, (int, float)):
                parts.append(f"{name} {duration}s")
            else:
                parts.append(name)
        return " → ".join(parts)


# ----------------------------------------------------------------------
# 离散动作定义
# ----------------------------------------------------------------------
# 运动控制页支持的离散动作（与板端 /api/action/{action} 一致）
DISCRETE_ACTIONS = [
    ("forward", "前进", True),      # 第三列: 是否支持长按持续
    ("backward", "后退", True),
    ("turn_left", "左转", True),
    ("turn_right", "右转", True),
    ("walk", "行走", True),
    ("sit", "坐下", False),
    ("stand", "站立", False),
    ("stop", "停止", False),
]

# 日志源定义: (key, 显示名称)，对应板端 GET /api/log/{key}
LOG_SOURCES = [
    ("arbiter", "运动仲裁器"),
    ("sit", "运动中枢"),
    ("start_v2", "双目深度"),
    ("start_avoidance", "避障"),
    ("robot_minimal", "机器人"),
    ("gesture_control", "手势"),
    ("voice_assistant", "语音助手"),
]
