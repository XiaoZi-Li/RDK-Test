#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双目深度避障节点 v2 (Stereo Depth Obstacle Avoidance Node v2)

v2 改进 (相比 v1):
  1. 深度图 180° 旋转修复 (mipi_rotation:=90 导致左右颠倒)
  2. 默认使用 follow_control 模式 (解决离散指令走走停停卡顿)
  3. IMU 角速度积分航向修正 (解决前进左倾)
  4. 阈值调整 (触发距离缩小 ~15%)
  5. 转向锁定 (避免障碍物边界左右抖动)

========== 数据源 ==========
  深度 (自动检测, 优先级):
    1. /StereoNetNode/stereonet_disp   视差图 (高值=近)
    2. /StereoNetNode/stereonet_visual bgr8 颜色映射 (红=近)
  IMU:
    /ros_robot_controller/imu_raw  (angular_velocity.z 积分得航向)

========== 运动指令 (UDP -> 127.0.0.1:5005 -> sit.py) ==========
  follow_control 模式 (默认, 流畅): {"mode":"follow_control","forward":0.4,"turn":0.1}
  离散模式 (use_follow_control:=false): forward/turn_left/turn_right/backward/stop

========== 启动顺序 ==========
  1. /app/gs130w_stereo/scripts/start_v2.sh start   (视觉 + stereonet)
  2. /app/start_robot.sh start                        (sit.py + IMU)
  3. /app/gs130w_stereo/scripts/start_avoidance.sh start
"""
import json
import socket
import sys
import time
import threading
import math
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import Image, Imu
from std_msgs.msg import String

# ============ 深度数据源 ============
TOPIC_DISP = '/StereoNetNode/stereonet_disp'
TOPIC_VISUAL = '/StereoNetNode/stereonet_visual'
TOPIC_IMU = '/ros_robot_controller/imu_raw'

# ============ 避障参数 (v2 调优) ============
DECISION_HZ = 10.0         # 决策频率提高到 10Hz (follow_control 需要高频更新)
DANGER_DISP = 45.0         # 视差 > 此值 → 障碍太近
CLEAR_DISP = 25.0          # 视差 < 此值 → 路径畅通
STALE_SEC = 2.0            # 深度数据超时
TURN_LOCK_SEC = 0.4        # 转向锁定时长 (避免边界抖动)

# ============ 速度参数 (follow_control 模式) ============
FWD_NORMAL = 0.45          # 正常前进速度 (映射到 vx = 0.45 * WALK_X = 4.5)
FWD_SLOW = 0.25            # 接近障碍减速
FWD_BACKWARD = -0.3        # 后退速度
TURN_SPEED = 0.5           # 转向速度

# ============ IMU 航向修正参数 ============
IMU_INTEGRATE_MAX_DT = 0.5    # IMU 积分最大 dt (超过则跳过, 避免大跳变)
IMU_STALE_SEC = 1.0           # IMU 数据超时
YAW_GAIN = 0.6                # 航向修正比例增益
MAX_YAW_CORRECTION = 0.25     # 最大航向修正 turn 值

# visual 颜色 → 视差量级缩放
VISUAL_SCALE = 30.0


class StereoAvoidanceNode(Node):
    """双目深度避障节点 v2"""

    def __init__(self):
        super().__init__('stereo_avoidance')

        # ==================== 参数 ====================
        self.declare_parameter('udp_ip', '127.0.0.1')
        self.declare_parameter('udp_port', 5005)
        self.declare_parameter('decision_hz', DECISION_HZ)
        self.declare_parameter('danger_disp', DANGER_DISP)
        self.declare_parameter('clear_disp', CLEAR_DISP)
        self.declare_parameter('use_follow_control', True)
        self.declare_parameter('use_imu_correction', True)
        self.declare_parameter('yaw_gain', YAW_GAIN)
        self.declare_parameter('max_yaw_correction', MAX_YAW_CORRECTION)
        self.declare_parameter('turn_lock_sec', TURN_LOCK_SEC)
        self.declare_parameter('enable_motion', True)

        self.udp_ip = str(self.get_parameter('udp_ip').value)
        self.udp_port = int(self.get_parameter('udp_port').value)
        self.danger_disp = float(self.get_parameter('danger_disp').value)
        self.clear_disp = float(self.get_parameter('clear_disp').value)
        self.use_follow_control = bool(self.get_parameter('use_follow_control').value)
        self.use_imu_correction = bool(self.get_parameter('use_imu_correction').value)
        self.yaw_gain = float(self.get_parameter('yaw_gain').value)
        self.max_yaw_correction = float(self.get_parameter('max_yaw_correction').value)
        self.turn_lock_sec = float(self.get_parameter('turn_lock_sec').value)
        self.enable_motion = bool(self.get_parameter('enable_motion').value)
        hz = float(self.get_parameter('decision_hz').value)

        # ==================== UDP ====================
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # ==================== 深度数据缓存 ====================
        self.depth_lock = threading.Lock()
        self.depth_data = None
        self.depth_source = None
        self.depth_stamp = 0.0
        self.disp_active = False

        # ==================== IMU 航向 (角速度积分) ====================
        self.imu_lock = threading.Lock()
        self.integrated_yaw = 0.0       # 积分得到的相对 yaw (rad)
        self.imu_last_time = 0.0
        self.imu_stamp = 0.0
        self.target_yaw = None          # 前进目标航向 (None=未设定)

        # ==================== 转向锁定 ====================
        self.turn_lock_dir = 0          # 0=无, 1=左转, -1=右转
        self.turn_lock_until = 0.0

        # ==================== 避障状态机 ====================
        # IDLE: 无障碍, 不发任何指令 (让仲裁器降级到语音/手势)
        # STOP: 检测到障碍, 停车
        # BACK: 后退
        # TURN: 转向空旷侧
        # ADVANCE: 前进绕开
        # RETURN: 回正方向
        self.avoid_state = 'IDLE'
        self.avoid_state_start = 0.0
        self.avoid_turn_dir = 0         # 1=左, -1=右 (RETURN 时反向)
        self.last_obstacle_alert = 0.0  # 语音告警节流

        # ==================== 指令去重 ====================
        self.last_cmd = None
        self.last_cmd_time = 0.0

        # ==================== 日志节流 ====================
        self._last_log = 0.0

        # ==================== 订阅 ====================
        sensor_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=2,
        )
        self.create_subscription(Image, TOPIC_DISP, self.disp_cb, sensor_qos)
        self.create_subscription(Image, TOPIC_VISUAL, self.visual_cb, sensor_qos)
        self.create_subscription(Imu, TOPIC_IMU, self.imu_cb, 10)

        # ==================== 状态发布 ====================
        self.status_pub = self.create_publisher(String, '/stereo_avoidance/status', 10)

        # ==================== 决策定时器 ====================
        self.timer = self.create_timer(1.0 / hz, self.decision_loop)

        # 启动时先停车
        self._send_cmd('stop')

        self.get_logger().info(
            f'避障节点 v2 启动 | udp={self.udp_ip}:{self.udp_port} hz={hz} '
            f'danger={self.danger_disp} clear={self.clear_disp} '
            f'follow_control={self.use_follow_control} '
            f'imu_correction={self.use_imu_correction} '
            f'motion_enabled={self.enable_motion}'
        )
        motion_hint = '【调试模式: 运动输出已禁用】' if not self.enable_motion else ''
        if motion_hint:
            self.get_logger().warn(motion_hint)
        self.get_logger().info(f'订阅: {TOPIC_DISP} + {TOPIC_VISUAL} + {TOPIC_IMU}')
        self.get_logger().info('等待深度数据...')

    # ================================================================
    #  深度回调
    # ================================================================

    def disp_cb(self, msg: Image):
        """视差图回调: 高值=近"""
        try:
            arr = self._image_to_array(msg)
            if arr is None:
                return
            if arr.ndim == 3:
                arr = arr[:, :, 0]
            with self.depth_lock:
                self.depth_data = arr.astype(np.float32)
                self.depth_source = 'disp'
                self.disp_active = True
                self.depth_stamp = time.time()
        except Exception as e:
            self.get_logger().warn(f'disp_cb: {e}')

    def visual_cb(self, msg: Image):
        """颜色映射深度图回调: 红=近 蓝=远 (有视差时跳过)"""
        if self.disp_active:
            return
        try:
            arr = self._image_to_array(msg)
            if arr is None:
                return
            h, w = arr.shape[:2]
            if h > w * 1.2:
                arr = arr[h // 2:, :, :]
            if arr.ndim == 3 and arr.shape[2] == 3:
                b_ch = arr[:, :, 0].astype(np.float32)
                r_ch = arr[:, :, 2].astype(np.float32)
                prox = (r_ch - b_ch + 255.0) / 510.0 * VISUAL_SCALE
            else:
                prox = (255.0 - arr.astype(np.float32)) / 255.0 * VISUAL_SCALE
            with self.depth_lock:
                self.depth_data = prox
                self.depth_source = 'visual'
                self.depth_stamp = time.time()
        except Exception as e:
            self.get_logger().warn(f'visual_cb: {e}')

    @staticmethod
    def _image_to_array(msg: Image):
        enc = msg.encoding.lower()
        h, w = msg.height, msg.width
        if enc in ('bgr8', 'rgb8'):
            arr = np.frombuffer(msg.data, dtype=np.uint8).reshape((h, w, 3)).copy()
            return arr[:, :, ::-1] if enc == 'rgb8' else arr
        if enc in ('mono8', '8uc1'):
            return np.frombuffer(msg.data, dtype=np.uint8).reshape((h, w)).copy()
        if enc in ('mono16', '16uc1'):
            return np.frombuffer(msg.data, dtype=np.uint16).reshape((h, w)).copy()
        if enc in ('32fc1',):
            return np.frombuffer(msg.data, dtype=np.float32).reshape((h, w)).copy()
        return None

    # ================================================================
    #  IMU 回调 (角速度积分得航向)
    # ================================================================

    def imu_cb(self, msg: Imu):
        """
        IMU 节点没有可靠四元数, 用 angular_velocity.z 积分得相对 yaw.
        gz 正值 = 左转 (逆时针), 负值 = 右转 (顺时针).
        """
        now = time.time()
        gz = float(msg.angular_velocity.z)

        with self.imu_lock:
            if self.imu_last_time > 0:
                dt = now - self.imu_last_time
                if 0 < dt < IMU_INTEGRATE_MAX_DT:
                    self.integrated_yaw += gz * dt
            self.imu_last_time = now
            self.imu_stamp = now

    # ================================================================
    #  深度分析
    # ================================================================

    def analyze_depth(self):
        """
        分析深度图, 返回 (left, center, right) proximity (高值=近).
        修复: 深度图 180° 翻转 (mipi_rotation 导致左右颠倒).
        """
        with self.depth_lock:
            if self.depth_data is None:
                return None
            depth = self.depth_data.copy()
            source = self.depth_source
            stamp = self.depth_stamp

        if time.time() - stamp > STALE_SEC:
            return None

        h, w = depth.shape[:2]
        if h < 4 or w < 4:
            return None

        # 修复 180° 翻转: 上下 + 左右翻转
        # mipi_cam mipi_rotation:=90 导致 stereonet 输出的深度图旋转了 180°
        # 翻转后图像左侧对应机器人右侧, 图像右侧对应机器人左侧
        depth = depth[::-1, ::-1]

        # 中间垂直带: 40%~80% (避开天花板和地面噪声)
        y0, y1 = int(h * 0.4), int(h * 0.8)
        band = depth[y0:y1, :]

        bh, bw = band.shape[:2]
        x_l = int(bw * 0.35)
        x_r = int(bw * 0.65)

        # 按机器人视角取区域 (图像左右与机器人左右相反)
        left_p = float(np.percentile(band[:, x_r:], 90))    # 图像右侧 = 机器人左侧
        center_p = float(np.percentile(band[:, x_l:x_r], 90))
        right_p = float(np.percentile(band[:, :x_l], 90))   # 图像左侧 = 机器人右侧

        return left_p, center_p, right_p, source

    # ================================================================
    #  IMU 航向修正
    # ================================================================

    def _ensure_target_yaw(self):
        """进入前进状态时, 记录当前航向作为目标"""
        if self.target_yaw is None:
            with self.imu_lock:
                self.target_yaw = self.integrated_yaw

    def _reset_target_yaw(self):
        """转向/后退时重置目标航向"""
        self.target_yaw = None

    def _get_yaw_correction(self):
        """
        计算航向修正 turn 值.
        机器人左偏 (integrated_yaw > target_yaw) → 右转修正 (turn < 0)
        返回 [-max_yaw_correction, max_yaw_correction]
        """
        if not self.use_imu_correction:
            return 0.0
        if time.time() - self.imu_stamp > IMU_STALE_SEC:
            return 0.0  # IMU 数据过期
        if self.target_yaw is None:
            return 0.0

        with self.imu_lock:
            yaw_error = self.integrated_yaw - self.target_yaw

        # 比例控制: 正误差(左偏) → 负 turn(右转修正)
        correction = -self.yaw_gain * yaw_error
        # 限幅
        correction = max(-self.max_yaw_correction,
                         min(self.max_yaw_correction, correction))
        return correction

    # ================================================================
    #  指令发送
    # ================================================================

    def _send_cmd(self, action):
        """发送离散运动指令 (enable_motion=False 时只记录不发送)"""
        if action == self.last_cmd:
            return
        if not self.enable_motion:
            self.get_logger().debug(f'[MOTION DISABLED] would send: {action}')
            self.last_cmd = action
            self.last_cmd_time = time.time()
            return
        payload = json.dumps({"action": action, "source": "stereo_avoid"})
        try:
            self.sock.sendto(payload.encode('utf-8'), (self.udp_ip, self.udp_port))
        except Exception as e:
            self.get_logger().warn(f'UDP send failed: {e}')
            return
        self.last_cmd = action
        self.last_cmd_time = time.time()

    def _send_follow(self, forward, turn):
        """
        发送 follow_control 连续控制指令.
        sit.py 不对此去重, 每帧都更新目标速度, 速度平滑过渡.
        """
        if not self.enable_motion:
            self.get_logger().debug(f'[MOTION DISABLED] would send follow: {forward}, {turn}')
            self.last_cmd = f"follow:{forward:.2f},{turn:.2f}"
            self.last_cmd_time = time.time()
            return
        payload = json.dumps({
            "mode": "follow_control",
            "forward": round(float(forward), 3),
            "turn": round(float(turn), 3),
            "source": "stereo_avoid"
        })
        try:
            self.sock.sendto(payload.encode('utf-8'), (self.udp_ip, self.udp_port))
        except Exception:
            return
        self.last_cmd = f"follow:{forward:.2f},{turn:.2f}"
        self.last_cmd_time = time.time()

    # ================================================================
    #  决策主循环 — 状态机避障
    # ================================================================

    def decision_loop(self):
        result = self.analyze_depth()
        now = time.time()

        if result is None:
            # 无深度数据 → 如果不在避障序列中, 不发任何指令
            if self.avoid_state != 'IDLE':
                # 正在避障中但丢失深度 → 停车, 回 IDLE
                self._send_cmd('stop')
                self._set_state('IDLE')
            self._reset_target_yaw()
            self.turn_lock_dir = 0
            return

        left_p, center_p, right_p, source = result

        # 节流日志
        if now - self._last_log > 1.0:
            self.get_logger().info(
                f'[{source}] L={left_p:.1f} C={center_p:.1f} R={right_p:.1f} '
                f'| state={self.avoid_state} '
                f'| cmd={self.last_cmd}'
            )
            self._last_log = now

        # 发布状态 JSON
        status = json.dumps({
            "source": source,
            "left": round(left_p, 1),
            "center": round(center_p, 1),
            "right": round(right_p, 1),
            "danger": round(self.danger_disp, 1),
            "clear": round(self.clear_disp, 1),
            "enable_motion": self.enable_motion,
            "avoid_state": self.avoid_state,
            "turn_lock": self.turn_lock_dir,
            "last_cmd": self.last_cmd
        })
        smsg = String()
        smsg.data = status
        self.status_pub.publish(smsg)

        # 状态机决策
        self._decide_state_machine(left_p, center_p, right_p, now)

    def _set_state(self, state):
        """切换避障状态"""
        if self.avoid_state != state:
            self.get_logger().info(f'[AVOID] {self.avoid_state} → {state}')
        self.avoid_state = state
        self.avoid_state_start = time.time()

    def _decide_state_machine(self, left_p, center_p, right_p, now):
        """状态机避障策略

        IDLE: 无障碍时不发指令, 让仲裁器降级到语音/手势
              检测到障碍 → STOP
        STOP: 停车 0.5s → BACK
        BACK: 后退 1.5s → TURN (判断哪边空旷)
        TURN: 转向 0.8s → ADVANCE
        ADVANCE: 前进 1.5s → RETURN
        RETURN: 反向回转 0.8s → IDLE
        """
        danger = self.danger_disp
        elapsed = now - self.avoid_state_start

        # ---------- IDLE: 监测障碍 ----------
        if self.avoid_state == 'IDLE':
            if center_p > danger or left_p > danger or right_p > danger:
                # 检测到障碍!
                self._send_cmd('stop')
                self._set_state('STOP')
                # 语音告警 (节流 5s 一次)
                if now - self.last_obstacle_alert > 5.0:
                    self.last_obstacle_alert = now
                    self.get_logger().warn('前方有障碍! 启动避障')
            # 无障碍 → 不发任何指令, 仲裁器自动降级到语音/手势
            return

        # ---------- STOP: 停车 0.5s ----------
        if self.avoid_state == 'STOP':
            self._send_cmd('stop')
            if elapsed > 0.5:
                self._set_state('BACK')
            return

        # ---------- BACK: 后退 1.5s ----------
        if self.avoid_state == 'BACK':
            self._send_cmd('backward')
            if elapsed > 1.5:
                # 判断哪边更空旷
                if left_p < right_p - 2.0:
                    self.avoid_turn_dir = 1   # 左转
                elif right_p < left_p - 2.0:
                    self.avoid_turn_dir = -1  # 右转
                else:
                    # 两边差不多, 默认左转
                    self.avoid_turn_dir = 1
                self._set_state('TURN')
            return

        # ---------- TURN: 转向空旷侧 0.8s ----------
        if self.avoid_state == 'TURN':
            if self.avoid_turn_dir > 0:
                self._send_cmd('turn_left')
            else:
                self._send_cmd('turn_right')
            if elapsed > 0.8:
                self._send_cmd('stop')
                self._set_state('ADVANCE')
            return

        # ---------- ADVANCE: 前进绕开 1.5s ----------
        if self.avoid_state == 'ADVANCE':
            # 如果前方仍然有障碍, 重新进入 STOP
            if center_p > danger:
                self._send_cmd('stop')
                self._set_state('STOP')
                return
            self._send_cmd('forward')
            if elapsed > 1.5:
                self._send_cmd('stop')
                self._set_state('RETURN')
            return

        # ---------- RETURN: 回正方向 0.8s ----------
        if self.avoid_state == 'RETURN':
            if self.avoid_turn_dir > 0:
                self._send_cmd('turn_right')
            else:
                self._send_cmd('turn_left')
            if elapsed > 0.8:
                self._send_cmd('stop')
                self._set_state('IDLE')
            return

    # ================================================================
    #  退出清理
    # ================================================================

    def destroy_node(self):
        try:
            self._send_cmd('stop')
            time.sleep(0.1)
        except Exception:
            pass
        self.get_logger().info('避障节点关闭, 已发送停车指令')
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = StereoAvoidanceNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main(sys.argv)
