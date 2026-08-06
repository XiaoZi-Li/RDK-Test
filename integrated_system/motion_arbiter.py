#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""motion_arbiter.py - 运动控制仲裁器

把多个来源的运动请求按优先级仲裁后发给 sit.py。

优先级（数字越小越高）:
  0 - 避障 (stereo_avoid): follow_control 连续控制 / 离散动作
  1 - 语音 (voice): 离散动作
  2 - 手势 (gesture): 离散动作
  9 - 未知来源

运行:
  # 默认: 监听 5005, 转发给 sit.py 5006
  python3 motion_arbiter.py

  # 自定义端口
  python3 motion_arbiter.py --listen-port 5005 --sit-port 5006
"""
import argparse
import json
import os
import socket
import sys
import threading
import time
from typing import Any, Dict, Optional, Tuple

# ============ 配置 ============
DEFAULT_LISTEN_PORT = int(os.environ.get("ARBITER_LISTEN_PORT", "5005"))
DEFAULT_SIT_PORT = int(os.environ.get("ARBITER_SIT_PORT", "5006"))
DEFAULT_SIT_IP = os.environ.get("ARBITER_SIT_IP", "127.0.0.1")

# 各通道活跃超时 (秒)
CHANNEL_TIMEOUT = {
    0: 0.30,   # 避障: 10Hz, 0.3s 足够覆盖 3 帧
    1: 2.50,   # 语音: 触发式, 保持到说完/动作完成
    2: 0.50,   # 手势: 持续检测, 消失即停
    9: 0.50,   # 未知来源
}

# source 字符串 → 优先级
SOURCE_PRIORITY = {
    "stereo_avoid": 0,
    "avoid": 0,
    "voice": 1,
    "gesture": 2,
}


def is_stop_like(cmd: Any) -> bool:
    """判断指令是否等效于停止。"""
    if cmd is None:
        return True
    if isinstance(cmd, str):
        return cmd.strip().lower() in ("stop", "")
    if isinstance(cmd, dict):
        # follow_control 全零视为停止
        if cmd.get("mode") == "follow_control":
            fwd = float(cmd.get("forward", 0.0))
            trn = float(cmd.get("turn", 0.0))
            return abs(fwd) < 1e-6 and abs(trn) < 1e-6
        action = cmd.get("action", "")
        if isinstance(action, str):
            return action.strip().lower() == "stop"
    return False


def cmd_to_payload(cmd: Any) -> bytes:
    """把内部保存的指令转成 UDP bytes。"""
    if isinstance(cmd, bytes):
        return cmd
    if isinstance(cmd, str):
        return cmd.encode("utf-8")
    if isinstance(cmd, dict):
        return json.dumps(cmd, ensure_ascii=False).encode("utf-8")
    return str(cmd).encode("utf-8")


class MotionArbiter:
    def __init__(self, listen_ip: str, listen_port: int,
                 sit_ip: str, sit_port: int):
        self.listen_ip = listen_ip
        self.listen_port = listen_port
        self.sit_ip = sit_ip
        self.sit_port = sit_port

        self.sock_in = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_in.bind((listen_ip, listen_port))
        self.sock_in.settimeout(0.05)

        self.sock_out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.lock = threading.Lock()
        # channels[priority] = {"last_time": float, "last_cmd": any, "active": bool}
        self.channels: Dict[int, Dict[str, Any]] = {
            p: {"last_time": 0.0, "last_cmd": None, "active": False}
            for p in CHANNEL_TIMEOUT
        }

        self.last_sent_raw: Optional[bytes] = None
        self.last_sent_desc = "stop"
        self.running = True

    def parse_packet(self, data: bytes) -> Tuple[int, Any, bytes]:
        """解析 UDP 包, 返回 (priority, cmd_object, raw_bytes)。"""
        raw = data.decode("utf-8", errors="ignore").strip()
        priority = 9
        cmd_obj: Any = raw

        # 尝试 JSON
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                src = payload.get("source", "")
                priority = SOURCE_PRIORITY.get(src, 9)
                cmd_obj = payload
        except Exception:
            # 纯字符串动作, 无法识别来源, 最低优先级
            priority = 9
            cmd_obj = raw

        return priority, cmd_obj, data

    def decide(self, now: float) -> Tuple[Optional[Any], int]:
        """返回 (要发送的指令, 优先级), 没有则返回 (None, -1)。"""
        with self.lock:
            for p in sorted(self.channels.keys()):
                ch = self.channels[p]
                if not ch["active"]:
                    continue
                age = now - ch["last_time"]
                if age > CHANNEL_TIMEOUT[p]:
                    ch["active"] = False
                    continue
                return ch["last_cmd"], p
        return None, -1

    def send(self, cmd: Any, priority: int):
        """发送指令到 sit.py, 只在变化时发送。"""
        payload = cmd_to_payload(cmd)
        desc = self._cmd_desc(cmd)

        # 去重: 如果是完全相同的原始包且不是停止, 跳过 (停止可以重复发作为心跳)
        if payload == self.last_sent_raw and not is_stop_like(cmd):
            return

        try:
            self.sock_out.sendto(payload, (self.sit_ip, self.sit_port))
            self.last_sent_raw = payload
            self.last_sent_desc = desc
            src_name = {0: "避障", 1: "语音", 2: "手势", 9: "未知"}.get(priority, "?")
            print(f"[arbiter] {src_name}(P{priority}) → {desc}")
        except Exception as e:
            print(f"[arbiter] 发送失败: {e}")

    @staticmethod
    def _cmd_desc(cmd: Any) -> str:
        if isinstance(cmd, dict):
            if cmd.get("mode") == "follow_control":
                return f"follow f={cmd.get('forward', 0):.2f} t={cmd.get('turn', 0):.2f}"
            return cmd.get("action", str(cmd))
        return str(cmd)

    def receiver_loop(self):
        """接收线程: 解析包并更新通道状态。"""
        while self.running:
            try:
                data, addr = self.sock_in.recvfrom(2048)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[arbiter] recv error: {e}")
                continue

            now = time.time()
            priority, cmd_obj, raw = self.parse_packet(data)

            with self.lock:
                self.channels[priority]["last_time"] = now
                self.channels[priority]["last_cmd"] = cmd_obj
                self.channels[priority]["active"] = True

    def arbiter_loop(self):
        """后台仲裁线程: 定期检查超时并发送合适指令。"""
        while self.running:
            now = time.time()
            cmd, p = self.decide(now)
            if cmd is not None:
                self.send(cmd, p)
            else:
                # 没有任何通道活跃, 发送 stop (仅发送一次)
                if self.last_sent_desc != "stop":
                    self.send({"action": "stop", "source": "arbiter"}, 9)
            time.sleep(0.05)  # 20Hz

    def run(self):
        print("=" * 60)
        print(" 运动控制仲裁器启动")
        print(f" 监听: {self.listen_ip}:{self.listen_port}")
        print(f" 转发: {self.sit_ip}:{self.sit_port}")
        print(" 优先级: 避障(0) > 语音(1) > 手势(2) > 未知(9)")
        print("=" * 60)
        print("按 Ctrl+C 退出\n")

        rx_thread = threading.Thread(target=self.receiver_loop, daemon=True)
        rx_thread.start()

        arb_thread = threading.Thread(target=self.arbiter_loop, daemon=True)
        arb_thread.start()

        try:
            while self.running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n[arbiter] 退出中...")
        finally:
            self.running = False
            # 退出前停车
            try:
                self.sock_out.sendto(
                    b'{"action":"stop","source":"arbiter"}',
                    (self.sit_ip, self.sit_port)
                )
            except Exception:
                pass
            self.sock_in.close()
            self.sock_out.close()


def main():
    parser = argparse.ArgumentParser(description="运动控制仲裁器")
    parser.add_argument("--listen-ip", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=DEFAULT_LISTEN_PORT)
    parser.add_argument("--sit-ip", default=DEFAULT_SIT_IP)
    parser.add_argument("--sit-port", type=int, default=DEFAULT_SIT_PORT)
    args = parser.parse_args()

    arbiter = MotionArbiter(args.listen_ip, args.listen_port,
                            args.sit_ip, args.sit_port)
    arbiter.run()


if __name__ == "__main__":
    main()
