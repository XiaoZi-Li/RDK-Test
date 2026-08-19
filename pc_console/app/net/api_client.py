# -*- coding: utf-8 -*-
"""api_client.py - 板端 HTTP API 客户端

封装与板端 dashboard.py（HTTP 服务）之间的全部 REST 交互：
  - 状态查询:  GET  /api/status
  - 离散动作:  POST /api/action/{action}
  - 连续遥控:  POST /api/move
  - 避障查询:  GET  /api/avoid_mode
  - 避障切换:  POST /api/avoid_mode
  - 日志拉取:  GET  /api/log/{key}
  - 系统管理:  POST /api/sys/start|stop|restart
  - 单独重启:  POST /api/restart/stereo|robot
  - 对话控制:  POST /api/chat

全部方法使用 Python 标准库 urllib 实现，无第三方依赖；
方法内部不做线程同步，调用方负责在工作线程中调用。
"""

import json
import urllib.request
import urllib.error


class ApiError(Exception):
    """API 交互异常（网络错误 / 非 200 响应 / 响应体解析失败）"""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class ApiClient:
    """板端 HTTP API 客户端

    用法:
        client = ApiClient("http://192.168.1.10:8081", timeout=4.0)
        ok, status = client.get_status()
    """

    def __init__(self, base_url: str, timeout: float = 4.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # 底层请求
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, body: dict = None) -> dict:
        """发送 HTTP 请求并解析 JSON 响应

        :param method: HTTP 方法 "GET" / "POST"
        :param path:   接口路径，如 "/api/status"
        :param body:   POST 请求体（自动序列化为 JSON）
        :return:       解析后的响应字典
        :raises ApiError: 网络失败 / HTTP 错误 / 响应非 JSON
        """
        url = self.base_url + path
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise ApiError(f"HTTP {e.code} {e.reason}", e.code) from e
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            raise ApiError(f"连接板端失败: {reason}") from e
        except (OSError, ValueError) as e:
            raise ApiError(f"请求异常: {e}") from e

        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8", errors="ignore"))
        except ValueError as e:
            raise ApiError("响应不是合法 JSON") from e

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def get_status(self) -> dict:
        """获取板端整体状态快照（组件 / UDP 端口 / 视频流 / IP）"""
        return self._request("GET", "/api/status")

    # ------------------------------------------------------------------
    # 运动控制
    # ------------------------------------------------------------------
    def send_action(self, action: str) -> dict:
        """发送离散动作指令（由板端转发至运动仲裁器 UDP 5005）

        :param action: forward/backward/turn_left/turn_right/sit/stand/stop/walk
        """
        return self._request("POST", f"/api/action/{action}")

    def send_move(self, forward: float, turn: float, source: str = "remote") -> dict:
        """发送连续遥控指令（follow_control 模式，需 5~10Hz 持续发送）

        :param forward: 前进速度 [-1, 1]，正=前进 负=后退
        :param turn:    转向速度 [-1, 1]，正=左转 负=右转
        """
        forward = max(-1.0, min(1.0, float(forward)))
        turn = max(-1.0, min(1.0, float(turn)))
        return self._request("POST", "/api/move", {
            "forward": forward,
            "turn": turn,
            "source": source,
        })

    # ------------------------------------------------------------------
    # 避障监测
    # ------------------------------------------------------------------
    def get_avoid_status(self) -> dict:
        """查询避障子系统实时状态（阶段 / 占比 / 决策 / USB 检测）"""
        return self._request("GET", "/api/avoid_mode")

    def set_avoid_mode(self, mode: str) -> dict:
        """切换避障模式

        :param mode: "on"=开启自动巡航(控车) "off"=关闭(纯监测不控车)
        """
        if mode not in ("on", "off"):
            raise ValueError("mode 必须是 on/off")
        return self._request("POST", "/api/avoid_mode", {"mode": mode})

    # ------------------------------------------------------------------
    # 日志查看
    # ------------------------------------------------------------------
    def get_log(self, log_key: str) -> dict:
        """拉取指定日志源的末尾内容

        :param log_key: arbiter/sit/start_v2/start_avoidance/
                        robot_minimal/gesture_control/voice_assistant
        """
        return self._request("GET", f"/api/log/{log_key}")

    # ------------------------------------------------------------------
    # 系统管理
    # ------------------------------------------------------------------
    def sys_command(self, command: str) -> dict:
        """系统级命令：启动/停止/重启全部板端组件

        :param command: start/stop/restart
        """
        if command not in ("start", "stop", "restart"):
            raise ValueError("command 必须是 start/stop/restart")
        return self._request("POST", f"/api/sys/{command}")

    def restart_stereo(self) -> dict:
        """单独重启双目深度链路（深度图出不来时使用）"""
        return self._request("POST", "/api/restart/stereo")

    def restart_robot(self) -> dict:
        """单独重启运动中枢（sit.py）"""
        return self._request("POST", "/api/restart/robot")

    # ------------------------------------------------------------------
    # 大模型对话控制
    # ------------------------------------------------------------------
    def chat(self, text: str, speak: bool = False) -> dict:
        """发送自然语言指令给板端大模型对话服务

        :param text:  用户输入文本
        :param speak: True 时板端喇叭同步播报回答
        :return:      {'ok':bool, 'reply':str, 'actions':list, 'vision':bool}
        """
        return self._request("POST", "/api/chat", {"text": text, "speak": speak})
