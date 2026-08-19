# -*- coding: utf-8 -*-
"""config.py - 连接配置管理模块

负责管理上位机与机器狗板端系统之间的连接参数，
包括板端 IP、API 端口、各路视频流端口以及状态轮询间隔等。
配置以 JSON 文件形式保存在用户主目录下，启动时自动加载。
"""

import json
import os

# 配置文件保存路径（用户主目录）
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".puppy_console.json")


class ConsoleConfig:
    """上位机连接配置类

    属性说明：
        board_host       板端 IP 地址（板端 dashboard.py HTTP 服务所在主机）
        api_port         板端 HTTP API 端口（dashboard.py 监听端口）
        video_streams    视频流列表，每项为 (端口, 名称, 子路径)
        poll_interval    状态轮询间隔（秒）
        heartbeat_ms     运动控制长按心跳间隔（毫秒）
        move_rate_hz     连续遥控模式指令发送频率（Hz）
        request_timeout  HTTP 请求超时（秒）
        demo_mode        是否启用演示模式（不连接真实板端）
    """

    def __init__(self):
        # ---- 连接参数（默认值与板端 integrated_system 一致）----
        self.board_host = "192.168.1.10"
        self.api_port = 8081

        # ---- 视频流端口定义 ----
        # (端口, 显示名称, 流子路径)
        # 8071 右眼 / 8072 左眼 / 8073 深度图 / 8093 YOLO / 8094 手势
        self.video_streams = [
            (8071, "右眼原始画面", ""),
            (8072, "左眼原始画面", ""),
            (8073, "深度伪彩图", ""),
            (8093, "YOLO 检测", "/stream"),
            (8094, "手势识别", "/stream"),
        ]

        # ---- 行为参数 ----
        self.poll_interval = 3.0       # 状态轮询间隔（秒）
        self.heartbeat_ms = 200        # 长按运动心跳间隔（毫秒）
        self.move_rate_hz = 8          # 连续遥控指令频率（Hz）
        self.request_timeout = 4.0     # HTTP 超时（秒）
        self.log_lines = 80            # 日志拉取行数

        # ---- 运行模式 ----
        self.demo_mode = False         # True 时使用内置模拟数据源

    # ------------------------------------------------------------------
    # 属性计算
    # ------------------------------------------------------------------
    @property
    def base_url(self) -> str:
        """板端 HTTP API 基地址，例如 http://192.168.1.10:8081"""
        return f"http://{self.board_host}:{self.api_port}"

    # ------------------------------------------------------------------
    # 序列化 / 反序列化
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """将配置导出为字典（用于 JSON 持久化）"""
        return {
            "board_host": self.board_host,
            "api_port": self.api_port,
            "video_streams": [list(item) for item in self.video_streams],
            "poll_interval": self.poll_interval,
            "heartbeat_ms": self.heartbeat_ms,
            "move_rate_hz": self.move_rate_hz,
            "request_timeout": self.request_timeout,
            "log_lines": self.log_lines,
            "demo_mode": self.demo_mode,
        }

    def from_dict(self, data: dict):
        """从字典恢复配置（对缺失字段保持默认值，对非法值直接忽略）"""
        if not isinstance(data, dict):
            return
        if isinstance(data.get("board_host"), str) and data["board_host"]:
            self.board_host = data["board_host"].strip()
        if isinstance(data.get("api_port"), int) and 1 <= data["api_port"] <= 65535:
            self.api_port = data["api_port"]
        streams = data.get("video_streams")
        if isinstance(streams, list) and streams:
            parsed = []
            for item in streams:
                if (isinstance(item, (list, tuple)) and len(item) == 3
                        and isinstance(item[0], int)):
                    parsed.append((int(item[0]), str(item[1]), str(item[2])))
            if parsed:
                self.video_streams = parsed
        if isinstance(data.get("poll_interval"), (int, float)) and data["poll_interval"] >= 0.5:
            self.poll_interval = float(data["poll_interval"])
        if isinstance(data.get("heartbeat_ms"), int) and 50 <= data["heartbeat_ms"] <= 2000:
            self.heartbeat_ms = int(data["heartbeat_ms"])
        if isinstance(data.get("move_rate_hz"), (int, float)) and 1 <= data["move_rate_hz"] <= 30:
            self.move_rate_hz = float(data["move_rate_hz"])
        if isinstance(data.get("request_timeout"), (int, float)) and 1 <= data["request_timeout"] <= 30:
            self.request_timeout = float(data["request_timeout"])
        if isinstance(data.get("log_lines"), int) and 10 <= data["log_lines"] <= 1000:
            self.log_lines = int(data["log_lines"])
        if isinstance(data.get("demo_mode"), bool):
            self.demo_mode = data["demo_mode"]

    # ------------------------------------------------------------------
    # 文件读写
    # ------------------------------------------------------------------
    def load(self):
        """从磁盘加载配置文件；文件不存在或损坏时静默使用默认值"""
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                self.from_dict(json.load(f))
        except (OSError, ValueError):
            # 配置文件不存在或 JSON 格式错误时使用默认配置
            pass

    def save(self):
        """将当前配置写入磁盘；失败时不抛出异常（配置属非关键数据）"""
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # 调试输出
    # ------------------------------------------------------------------
    def summary(self) -> str:
        """返回人类可读的配置摘要（用于日志）"""
        mode = "演示模式" if self.demo_mode else "在线模式"
        return (f"[{mode}] 板端 {self.board_host}:{self.api_port} | "
                f"轮询 {self.poll_interval}s | 心跳 {self.heartbeat_ms}ms | "
                f"遥控 {self.move_rate_hz}Hz")
