#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双目深度避障节点 v4 (Stereo Depth Obstacle Avoidance Node v4)

v4 重构 (2026-08-11, 基于用户现场摆瓶调试反馈):
  1. 【方向性躲避】左边障碍 → 右转; 右边障碍 → 左转; 正前障碍 →
     停车+播报 → 后退 → 向空旷侧转。转向持续到障碍侧清空(非固定时序),
     超时 4s 兜底回巡航。
  2. 【占比判定】v3 用 15% 分位距离, 右侧地面/桌面小片误差(几个像素)就把
     right 判定值抬到跟瓶子侧差不多 → 左右误判。v4 改为"近像素占比":
     区域 dist<danger 的像素占比 > 3% 才算障碍, <1.5% 算清空(滞回防抖),
     小片误差直接被占比淹没。
  3. 【垂直带收窄】40%~80% → 40%~70%: 排除近处地面(显示方向底部)误差区,
     保留人手持瓶子所在的中部高度。
  4. 【被动纯监测】开关 off 时绝不发任何运动指令, 只发布状态 JSON
     (界面看判定结果); on→off 切换瞬间若节点自己正在驱动运动则补发 stop。
  5. 【巡航】on 时 IDLE 持续 forward, 障碍触发状态机, 清空自动回 IDLE 续走。

========== 状态机 ==========
  IDLE:       巡航模式持续前进; 障碍 → TURN_RIGHT/TURN_LEFT/STOP
  TURN_RIGHT: 躲左障, 右转直到左+中清空 → IDLE; 超时→IDLE; 障碍换边→IDLE
  TURN_LEFT:  躲右障, 镜像
  STOP:       正前障碍停车 stop_sec (已播报) → BACK
  BACK:       后退 back_sec → 向空旷侧 TURN

========== 数据源 ==========
  深度 (优先级自动选择):
    1. /StereoNetNode/stereonet_depth   深度图 mono16/32FC1 (mm, 小值=近)
    2. /StereoNetNode/stereonet_visual  bgr8 颜色映射 (红=近, fallback)

========== 运动指令 (UDP -> 仲裁器 5005 -> sit.py 5006) ==========
  离散指令: forward/backward/turn_left/turn_right/stop, source=stereo_avoid
  避障优先级最高 (P0), 发指令时压制语音/手势/遥控

启动:
  /app/gs130w_stereo/scripts/start_avoidance.sh start
调参:
  --ros-args -p danger_dist:=0.5 -p obst_ratio:=0.05
  --ros-args -p enable_motion:=false   # 纯视觉调试 (不发运动指令)
"""
import json
import socket
import sys
import time
import threading
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import String

# ============ 深度数据源 ============
TOPIC_DEPTH = '/StereoNetNode/stereonet_depth'
TOPIC_VISUAL = '/StereoNetNode/stereonet_visual'

# ============ 默认参数 (v4: 距离米 + 占比判定) ============
DECISION_HZ = 10.0
DANGER_DIST = 0.45       # 像素距离 < 此值 → 近像素 (透明瓶测偏远, 取宽松)
NEAR_PCT = 15.0          # 近端分位 (仅状态显示/空旷侧比较用)
OBST_RATIO = 0.03        # 区域近像素占比 > 3% → 该区域有障碍
CLEAR_RATIO = 0.015      # 占比 < 1.5% → 清空 (滞回防抖)
BAND_TOP = 0.40          # 垂直带上界 (避开远处/天空)
BAND_BOT = 0.70          # 垂直带下界 (避开近处地面误差区)
STALE_SEC = 2.0          # 深度数据超时

# ============ 动作时序 (秒) ============
STOP_SEC = 0.4           # 正前障碍停车确认
BACK_SEC = 2.0           # 正前障碍后退时长
TURN_TIMEOUT = 4.0       # 转向兜底超时 (防死循环)

# ============ visual fallback 阈值 (近度 0~30, 大=近) ============
VIS_DANGER = 18.0
VISUAL_SCALE = 30.0

# ============ v5 方位判定参数 (2026-08-11 六组标定数据拟合) ============
# 有障碍 = 近端距离 < BLOCKED_DIST 且 近像素占比 > OBST_RATIO (双条件)
#   —— 抗"障碍移开后近像素滞留": 滞留是高占比+远距离, 距离条件直接滤掉
BLOCKED_DIST = 0.35      # 近端分位距离 < 0.35m → 该区域有障碍
SIDE_RATIO = 0.90        # 用户现场规则: 左/右占比 ≥90% → 该侧有障
TIE_MARGIN = 0.08        # 兜底判定: center 距离与最小值差 < 0.08m → 优先算 center
                         # (center 近像素系统性偏低 — 正前水瓶双目匹配弱, 用距离补偿)

# ============ 心跳: arbiter P0 通道 0.3s 超时, 0.2s 重发保持活跃 ============
CMD_HEARTBEAT_SEC = 0.2

# ============ 方位播报文本 ============
SPEAK_TEXT = {
    'left':   '左前方有障碍物，向右避让',
    'center': '正前方有障碍物，后退绕行',
    'right':  '右前方有障碍物，向左避让',
}


class StereoAvoidanceNode(Node):
    """双目深度避障节点 v4"""

    def __init__(self):
        super().__init__('stereo_avoidance')

        # ==================== 参数 ====================
        self.declare_parameter('udp_ip', '127.0.0.1')
        self.declare_parameter('udp_port', 5005)
        self.declare_parameter('decision_hz', DECISION_HZ)
        self.declare_parameter('danger_dist', DANGER_DIST)
        self.declare_parameter('near_pct', NEAR_PCT)
        self.declare_parameter('obst_ratio', OBST_RATIO)
        self.declare_parameter('clear_ratio', CLEAR_RATIO)
        self.declare_parameter('band_top', BAND_TOP)
        self.declare_parameter('band_bot', BAND_BOT)
        self.declare_parameter('stop_sec', STOP_SEC)
        self.declare_parameter('back_sec', BACK_SEC)
        self.declare_parameter('turn_timeout', TURN_TIMEOUT)
        self.declare_parameter('enable_motion', True)
        self.declare_parameter('speak_udp_ip', '127.0.0.1')
        self.declare_parameter('speak_udp_port', 5007)
        self.declare_parameter('control_udp_port', 5008)
        self.declare_parameter('usb_fusion_port', 5009)   # USB 语义检测 UDP (0=禁用)
        self.declare_parameter('usb_fusion', True)
        # v5 方位判定参数
        self.declare_parameter('blocked_dist', BLOCKED_DIST)
        self.declare_parameter('side_ratio', SIDE_RATIO)
        self.declare_parameter('tie_margin', TIE_MARGIN)

        self.udp_ip = str(self.get_parameter('udp_ip').value)
        self.udp_port = int(self.get_parameter('udp_port').value)
        self.danger_dist = float(self.get_parameter('danger_dist').value)
        self.near_pct = float(self.get_parameter('near_pct').value)
        self.obst_ratio = float(self.get_parameter('obst_ratio').value)
        self.clear_ratio = float(self.get_parameter('clear_ratio').value)
        self.band_top = float(self.get_parameter('band_top').value)
        self.band_bot = float(self.get_parameter('band_bot').value)
        self.stop_sec = float(self.get_parameter('stop_sec').value)
        self.back_sec = float(self.get_parameter('back_sec').value)
        self.turn_timeout = float(self.get_parameter('turn_timeout').value)
        self.enable_motion = bool(self.get_parameter('enable_motion').value)
        self.speak_addr = (str(self.get_parameter('speak_udp_ip').value),
                           int(self.get_parameter('speak_udp_port').value))
        self.control_port = int(self.get_parameter('control_udp_port').value)
        self.blocked_dist = float(self.get_parameter('blocked_dist').value)
        self.side_ratio = float(self.get_parameter('side_ratio').value)
        self.tie_margin = float(self.get_parameter('tie_margin').value)
        hz = float(self.get_parameter('decision_hz').value)

        # ==================== USB 语义检测融合 ====================
        self.usb_fusion = bool(self.get_parameter('usb_fusion').value)
        self.usb_port = int(self.get_parameter('usb_fusion_port').value)
        self._usb_lock = threading.Lock()
        self._usb_result = None      # {'side':..., 'area':..., 'ts':...}
        if self.usb_fusion and self.usb_port > 0:
            threading.Thread(target=self._usb_query_loop, daemon=True).start()
            self.get_logger().info(f'USB 语义融合: 查询 127.0.0.1:{self.usb_port} @3Hz')

        # ==================== UDP ====================
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # ==================== 深度数据缓存 ====================
        self.depth_lock = threading.Lock()
        self.depth_data = None       # 距离图 (米) 或 visual 近度图 (0~30)
        self.depth_source = None     # 'depth' / 'visual'
        self.depth_stamp = 0.0
        self.depth_active = False    # 主源是否来过数据 (来过后禁用 fallback)

        # ==================== 避障模式开关 ====================
        self.avoid_mode = False      # False=被动监测, True=自动巡航
        self._ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._ctrl_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._ctrl_sock.bind(('127.0.0.1', self.control_port))
            self._ctrl_sock.settimeout(0.5)
            threading.Thread(target=self._control_loop, daemon=True).start()
        except Exception as e:
            self.get_logger().warn(f'控制端口 {self.control_port} 绑定失败: {e}')

        # ==================== 避障状态机 v4 ====================
        # IDLE:       无障碍 (巡航模式持续前进 / 被动模式静默只发状态)
        # TURN_RIGHT: 躲左障, 右转直到清空
        # TURN_LEFT:  躲右障, 左转直到清空
        # STOP:       正前障碍停车 (已播报)
        # BACK:       后退 → 向空旷侧 TURN
        self.avoid_state = 'IDLE'
        self.avoid_state_start = 0.0
        self.last_obstacle_alert = 0.0   # 播报节流
        self.last_sensor_alert = 0.0     # 深度异常播报节流
        self.detour_count = 0            # 正前障碍连续绕行次数 (防后退死循环)
        self.motion_driving = False      # 本节点是否正在驱动运动 (off 切换时决定是否补 stop)

        # ==================== 指令心跳 ====================
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
        self.create_subscription(Image, TOPIC_DEPTH, self.depth_cb, sensor_qos)
        self.create_subscription(Image, TOPIC_VISUAL, self.visual_cb, sensor_qos)

        # ==================== 状态发布 ====================
        self.status_pub = self.create_publisher(String, '/stereo_avoidance/status', 10)

        # ==================== 决策定时器 ====================
        self.timer = self.create_timer(1.0 / hz, self.decision_loop)

        # v4: 启动即被动监测, 不发任何运动指令 (等避障模式开启)

        self.get_logger().info(
            f'避障节点 v4 启动 | udp={self.udp_ip}:{self.udp_port} hz={hz} '
            f'danger={self.danger_dist}m obst_ratio={self.obst_ratio} '
            f'clear_ratio={self.clear_ratio} band={self.band_top}~{self.band_bot} '
            f'时序: 停{self.stop_sec}s 退{self.back_sec}s 转直到清空(超时{self.turn_timeout}s) '
            f'| 播报→{self.speak_addr[0]}:{self.speak_addr[1]} '
            f'控制口:{self.control_port} motion={self.enable_motion}'
        )
        if not self.enable_motion:
            self.get_logger().warn('【调试模式: 运动输出已禁用】')
        self.get_logger().info(f'订阅: {TOPIC_DEPTH} + {TOPIC_VISUAL}')
        self.get_logger().info('等待深度数据...')

    # ================================================================
    #  深度回调
    # ================================================================

    def depth_cb(self, msg: Image):
        """深度图回调 (mm 或 m, 小值=近) → 统一转成米"""
        try:
            arr = self._image_to_array(msg)
            if arr is None:
                return
            if arr.ndim == 3:
                arr = arr[:, :, 0]
            arr = arr.astype(np.float32)
            # 单位自适应: 最大值 > 100 视为 mm
            if float(np.max(arr)) > 100.0:
                arr = arr / 1000.0
            with self.depth_lock:
                self.depth_data = arr
                self.depth_source = 'depth'
                self.depth_active = True
                self.depth_stamp = time.time()
        except Exception as e:
            self.get_logger().warn(f'depth_cb: {e}')

    def visual_cb(self, msg: Image):
        """颜色映射深度图回调: 红=近 蓝=远 (有主源深度时跳过)"""
        if self.depth_active:
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
    #  深度分析
    # ================================================================

    def analyze(self):
        """
        分析深度图 → dict:
          left_d/center_d/right_d: 三区近端分位距离 (米, 显示+比较用)
          left_r/center_r/right_r: 三区近像素占比 (判定用, 0~1)
          source: 'depth' / 'visual'
        方向: 深度图 180°翻转后与左目视图同向 → 图像左 = 机器人左
        垂直带收窄到 band_top~band_bot (40~70%): 排除近处地面误差区
        """
        with self.depth_lock:
            if self.depth_data is None:
                return None
            data = self.depth_data.copy()
            source = self.depth_source
            stamp = self.depth_stamp

        if time.time() - stamp > STALE_SEC:
            return None

        h, w = data.shape[:2]
        if h < 4 or w < 4:
            return None

        # 180° 翻转: mipi_rotation=90 + 相机物理倒装, stereonet 输出上下左右颠倒
        data = data[::-1, ::-1]

        # 垂直带 (避开远处天空和近处地面误差区)
        band = data[int(h * self.band_top):int(h * self.band_bot), :]
        bw = band.shape[1]
        x_l = int(bw * 0.35)
        x_r = int(bw * 0.65)

        if source == 'depth':
            def region_stat(region):
                valid = region[(region > 0.05) & (region < 10.0)]
                if valid.size < 20:
                    return 9.9, 0.0
                # 近像素占比: 距离 < danger 的像素比例 (抗小片误差)
                ratio = float(np.count_nonzero(valid < self.danger_dist)) / float(valid.size)
                near_d = float(np.percentile(valid, self.near_pct))
                return near_d, ratio
            left_d, left_r = region_stat(band[:, :x_l])      # 图像左 = 机器人左
            center_d, center_r = region_stat(band[:, x_l:x_r])
            right_d, right_r = region_stat(band[:, x_r:])    # 图像右 = 机器人右
            # 全帧饱和守卫: 三区占比都极高且距离全部钉在贴脸级 (<0.10m)
            #   → stereonet 垃圾输出或镜头被完全捂住, 任何避障动作都无意义
            # 注意阈值必须贴脸级: 真实障碍场景 (六组标定) 也会出现三区占比>50%
            #   且 max_d<0.25, 0.25 的阈值会把真障碍误判成垃圾数据
            saturated = (left_r > 0.5 and center_r > 0.5 and right_r > 0.5
                         and max(left_d, center_d, right_d) < 0.10)
        else:
            # visual 近度 (大=近): 近度 > VIS_DANGER 的像素占比
            def region_stat_vis(region):
                if region.size < 20:
                    return 0.0, 0.0
                ratio = float(np.count_nonzero(region > VIS_DANGER)) / float(region.size)
                prox = float(np.percentile(region, 90))
                return prox, ratio
            left_d, left_r = region_stat_vis(band[:, :x_l])
            center_d, center_r = region_stat_vis(band[:, x_l:x_r])
            right_d, right_r = region_stat_vis(band[:, x_r:])
            saturated = False

        return {
            'left_d': left_d, 'center_d': center_d, 'right_d': right_d,
            'left_r': left_r, 'center_r': center_r, 'right_r': right_r,
            'source': source,
            'saturated': saturated,
        }

    # ================================================================
    #  USB 语义检测融合 (UDP 5009 ← usb_obstacle_node.py)
    # ================================================================

    def _usb_query_loop(self):
        """3Hz 轮询 USB 语义检测节点, 缓存最新结果 (离线时结果为 None)"""
        qsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        qsock.settimeout(0.3)
        addr = ('127.0.0.1', self.usb_port)
        while True:
            try:
                qsock.sendto(b'q', addr)
                data, _ = qsock.recvfrom(1024)
                res = json.loads(data.decode('utf-8', errors='ignore'))
                with self._usb_lock:
                    self._usb_result = res if res.get('online') else None
            except socket.timeout:
                with self._usb_lock:
                    self._usb_result = None
            except Exception:
                with self._usb_lock:
                    self._usb_result = None
            time.sleep(0.33)

    def _usb_side(self):
        """USB 语义判定方位 (透明瓶/黑色无纹理等双目盲区兜底)。
        结果超过 1.5s 视为离线 → None"""
        with self._usb_lock:
            res = self._usb_result
        if not res or time.time() - res.get('ts', 0) > 1.5:
            return None
        return res.get('side')

    # ================================================================
    #  避障模式控制 (UDP 5008)
    # ================================================================

    def _control_loop(self):
        """接收 UDP 控制:
          {"avoid_mode":"on"/"off"}   切换自动巡航
          {"danger_dist":0.15, "obst_ratio":0.05, ...}  运行时调参 (免重启)
        """
        while True:
            try:
                data, _ = self._ctrl_sock.recvfrom(1024)
            except socket.timeout:
                if not rclpy.ok():
                    return
                continue
            except Exception:
                return
            try:
                payload = json.loads(data.decode('utf-8', errors='ignore'))
            except Exception:
                continue
            # 运行时调参 (现场摆瓶标定时实时调阈值)
            for key in ('danger_dist', 'obst_ratio', 'clear_ratio',
                        'band_top', 'band_bot', 'stop_sec', 'back_sec',
                        'turn_timeout', 'blocked_dist', 'side_ratio',
                        'tie_margin'):
                if key in payload:
                    try:
                        setattr(self, key, float(payload[key]))
                        self.get_logger().warn(f'[TUNE] {key} = {getattr(self, key)}')
                    except Exception:
                        pass
            mode = str(payload.get('avoid_mode', '')).lower()
            if mode == 'on' and not self.avoid_mode:
                self.avoid_mode = True
                self.get_logger().warn('[AVOID_MODE] 开启: 自动巡航前进')
                self._speak('避障模式已开启')
            elif mode == 'off' and self.avoid_mode:
                self.avoid_mode = False
                self.get_logger().warn('[AVOID_MODE] 关闭: 纯监测 (不控车)')
                # 仅当本节点正在驱动运动时补发 stop (避免狗一直走)
                if self.motion_driving:
                    self._send_cmd('stop')
                self._set_state('IDLE')
                self._speak('避障模式已关闭')

    # ================================================================
    #  语音播报 (UDP → voice_assistant:5007)
    # ================================================================

    def _speak(self, text: str):
        try:
            payload = json.dumps({"speak": text}, ensure_ascii=False)
            self.sock.sendto(payload.encode('utf-8'), self.speak_addr)
        except Exception:
            pass

    # ================================================================
    #  指令发送 (带心跳)
    # ================================================================

    def _send_cmd(self, action):
        """发送离散运动指令。相同指令每 CMD_HEARTBEAT_SEC 重发,
        保持仲裁器 P0 通道活跃 (0.3s 超时), 否则长动作会被截断成 stop"""
        now = time.time()
        if action == self.last_cmd and now - self.last_cmd_time < CMD_HEARTBEAT_SEC:
            return
        if not self.enable_motion:
            self.last_cmd = action
            self.last_cmd_time = now
            return
        payload = json.dumps({"action": action, "source": "stereo_avoid"})
        try:
            self.sock.sendto(payload.encode('utf-8'), (self.udp_ip, self.udp_port))
        except Exception as e:
            self.get_logger().warn(f'UDP send failed: {e}')
            return
        self.last_cmd = action
        self.last_cmd_time = now
        self.motion_driving = (action != 'stop')

    # ================================================================
    #  决策主循环 — 状态机避障
    # ================================================================

    def decision_loop(self):
        result = self.analyze()
        now = time.time()

        if result is None:
            # 无深度数据: 巡航中断 → 停车回 IDLE (仅巡航模式才在控车)
            if self.avoid_state != 'IDLE':
                self._send_cmd('stop')
                self._set_state('IDLE')
            return

        source = result['source']
        saturated = result.get('saturated', False)

        # 节流日志
        if now - self._last_log > 1.0:
            if source == 'depth':
                vals = (f"L={result['left_d']:.2f}m/{result['left_r']*100:.1f}% "
                        f"C={result['center_d']:.2f}m/{result['center_r']*100:.1f}% "
                        f"R={result['right_d']:.2f}m/{result['right_r']*100:.1f}%")
            else:
                vals = (f"L={result['left_d']:.1f}/{result['left_r']*100:.1f}% "
                        f"C={result['center_d']:.1f}/{result['center_r']*100:.1f}% "
                        f"R={result['right_d']:.1f}/{result['right_r']*100:.1f}%(visual)")
            if saturated:
                vals += ' [饱和:数据无效]'
            self.get_logger().info(
                f'[{source}] {vals} | state={self.avoid_state} '
                f'| mode={"auto" if self.avoid_mode else "monitor"} '
                f'| cmd={self.last_cmd}'
            )
            self._last_log = now

        # 发布状态 JSON (被动模式也持续发布, 界面看判定结果)
        status = json.dumps({
            "source": source,
            "left": round(result['left_d'], 2),
            "center": round(result['center_d'], 2),
            "right": round(result['right_d'], 2),
            "left_ratio": round(result['left_r'], 3),
            "center_ratio": round(result['center_r'], 3),
            "right_ratio": round(result['right_r'], 3),
            "unit": "m" if source == "depth" else "prox",
            "danger": round(self.danger_dist, 2) if source == "depth" else VIS_DANGER,
            "obst_ratio": round(self.obst_ratio, 3),
            "decision": ("sensor_error" if saturated
                         else (self._obstacle_side(result) or "clear")),
            "usb_side": self._usb_side() if (self.usb_fusion and self.usb_port > 0) else None,
            "enable_motion": self.enable_motion,
            "avoid_mode": self.avoid_mode,
            "avoid_state": self.avoid_state,
            "last_cmd": self.last_cmd
        })
        smsg = String()
        smsg.data = status
        self.status_pub.publish(smsg)

        # 深度饱和 (stereonet 垃圾输出/镜头被完全遮挡):
        # 任何避障动作都无意义 → 停车待命, 绝不再后退 (修"开启避障就一直后退")
        if saturated:
            if self.motion_driving:
                self._send_cmd('stop')
            if self.avoid_state != 'IDLE':
                self._set_state('IDLE')
            if self.avoid_mode and now - self.last_sensor_alert > 10.0:
                self.last_sensor_alert = now
                self.get_logger().warn('[SENSOR] 深度数据全帧饱和, 判定无效, 停车待命')
                self._speak('深度数据异常，请检查相机')
            return

        # 被动模式: 只发状态, 绝不控车
        if not self.avoid_mode:
            return

        self._decide_state_machine(result, now)

    def _set_state(self, state):
        if self.avoid_state != state:
            self.get_logger().info(f'[AVOID] {self.avoid_state} → {state}')
        self.avoid_state = state
        self.avoid_state_start = time.time()

    def _region_blocked(self, res, side):
        """单区有障判定 (v5 双条件): 近端距离够近 且 近像素占比够高
        抗"障碍移开后近像素滞留": 滞留=高占比+远距离, 距离条件直接滤掉"""
        return (res[side + '_d'] < self.blocked_dist
                and res[side + '_r'] > self.obst_ratio)

    def _obstacle_side(self, res):
        """v5 方位判定: 'left'/'center'/'right'/None (六组标定数据拟合)

        规则 (用户现场标定 2026-08-11):
          1. 三区都不满足双条件 → None (畅通)
          2. 左/右占比 ≥90% (且满足双条件):
             - 仅一侧 → 该侧有障 (向反方向转)
             - 两侧都 ≥90% → 'center' (按正前障碍处理, 优先右转)
          3. 兜底: 近端分位距离最小侧; center 与最小值差 < tie_margin 时
             优先 'center' (center 近像素系统性偏低, 正前水瓶双目匹配弱,
             用距离补偿 — 标定组"正前2" center 仅33.9% 但距离 0.12m 最小)
        """
        l_d, c_d, r_d = res['left_d'], res['center_d'], res['right_d']
        l_r, r_r = res['left_r'], res['right_r']
        l_blk = self._region_blocked(res, 'left')
        c_blk = self._region_blocked(res, 'center')
        r_blk = self._region_blocked(res, 'right')
        if not (l_blk or c_blk or r_blk):
            return None
        # 90% 规则 (center 也≥90% 时说明障碍横跨中间 → 按正前处理)
        l90 = l_blk and l_r >= self.side_ratio
        c90 = c_blk and res['center_r'] >= self.side_ratio
        r90 = r_blk and r_r >= self.side_ratio
        if (l90 and r90) or (c90 and (l90 or r90)):
            return 'center'
        if l90:
            return 'left'
        if r90:
            return 'right'
        if c90:
            return 'center'
        # 兜底: 距离最小侧, 并列含 center → center
        m = min(l_d, c_d, r_d)
        if c_blk and c_d <= m + self.tie_margin:
            return 'center'
        if not l_blk and not r_blk:
            return 'center'      # 只有 center 触发
        if l_blk and not r_blk:
            return 'left'
        if r_blk and not l_blk:
            return 'right'
        return 'left' if l_d <= r_d else 'right'

    def _side_cleared(self, res, watch_sides):
        """转向清空判定 (v5): 关注侧都不满足有障双条件 → 已清空
        (旧版只看占比 <clear_ratio, 移开后滞留高占比会永远不清空 → 死转)"""
        for s in watch_sides:
            if self._region_blocked(res, s):
                return False
        return True

    def _alert_obstacle(self, side, now):
        """播报障碍方位 (5s 节流)"""
        if now - self.last_obstacle_alert > 5.0:
            self.last_obstacle_alert = now
            self.get_logger().warn(f'{SPEAK_TEXT[side]}')
            self._speak(SPEAK_TEXT[side])

    def _decide_state_machine(self, res, now):
        """状态机 v4 (方向性躲避, 转向直到清空)

        IDLE:       持续前进; 左障→TURN_RIGHT, 右障→TURN_LEFT, 正前→STOP
        TURN_RIGHT: 右转躲左障, 左+中清空 → IDLE; 超时/障碍换边 → IDLE
        TURN_LEFT:  左转躲右障, 镜像
        STOP:       停车 stop_sec → BACK
        BACK:       后退 back_sec → 向空旷侧 TURN
        """
        elapsed = now - self.avoid_state_start
        side = self._obstacle_side(res)
        # USB 语义融合: 双目漏检 (透明瓶测偏远/黑色无纹理盲区) 时兜底
        if side is None:
            usb = self._usb_side()
            if usb:
                side = usb
                if now - getattr(self, '_usb_log_ts', 0) > 2.0:
                    self._usb_log_ts = now
                    self.get_logger().warn(f'[USB-FUSION] 双目畅通但 USB 看到 {usb} 障碍')

        # ---------- IDLE: 巡航前进 + 监测障碍 ----------
        if self.avoid_state == 'IDLE':
            if side == 'left':
                self.detour_count = 0
                self._alert_obstacle('left', now)
                self._send_cmd('turn_right')
                self._set_state('TURN_RIGHT')
                return
            if side == 'right':
                self.detour_count = 0
                self._alert_obstacle('right', now)
                self._send_cmd('turn_left')
                self._set_state('TURN_LEFT')
                return
            if side == 'center':
                # 防后退死循环: 连续绕行 2 次仍被挡 → 停车等待, 不再后退
                if self.detour_count >= 2:
                    self._send_cmd('stop')
                    if now - self.last_obstacle_alert > 5.0:
                        self.last_obstacle_alert = now
                        self.get_logger().warn('[AVOID] 多次绕行仍被挡, 停车等待')
                        self._speak('前方无法通行，请移开障碍物')
                    return
                self.detour_count += 1
                self._alert_obstacle('center', now)
                self._send_cmd('stop')
                self._set_state('STOP')
                return
            # 无障碍: 持续巡航, 重置绕行计数
            self.detour_count = 0
            self._send_cmd('forward')
            return

        # ---------- TURN_RIGHT: 右转躲左障 ----------
        if self.avoid_state == 'TURN_RIGHT':
            # 左+中清空 → 回巡航; 障碍换到右侧 → 回 IDLE 重新决策; 超时兜底
            if self._side_cleared(res, ('left', 'center')):
                self.get_logger().info('[AVOID] 左侧已清空, 继续巡航')
                self._set_state('IDLE')
                return
            if side == 'right' or elapsed > self.turn_timeout:
                self._set_state('IDLE')
                return
            self._send_cmd('turn_right')
            return

        # ---------- TURN_LEFT: 左转躲右障 ----------
        if self.avoid_state == 'TURN_LEFT':
            if self._side_cleared(res, ('right', 'center')):
                self.get_logger().info('[AVOID] 右侧已清空, 继续巡航')
                self._set_state('IDLE')
                return
            if side == 'left' or elapsed > self.turn_timeout:
                self._set_state('IDLE')
                return
            self._send_cmd('turn_left')
            return

        # ---------- STOP: 正前障碍停车 ----------
        if self.avoid_state == 'STOP':
            self._send_cmd('stop')
            if elapsed > self.stop_sec:
                self._set_state('BACK')
            return

        # ---------- BACK: 后退 → 转向绕行 (v5: 优先右转) ----------
        if self.avoid_state == 'BACK':
            self._send_cmd('backward')
            if elapsed > self.back_sec:
                # 用户规则: 正前/双侧障碍优先右转;
                # 仅当右侧仍有障且左侧畅通时才左转
                r_blk = self._region_blocked(res, 'right')
                l_blk = self._region_blocked(res, 'left')
                if r_blk and not l_blk:
                    self._send_cmd('turn_left')
                    self._set_state('TURN_LEFT')
                else:
                    self._send_cmd('turn_right')
                    self._set_state('TURN_RIGHT')
            return

    # ================================================================
    #  退出清理
    # ================================================================

    def destroy_node(self):
        try:
            self.avoid_mode = False
            # 仅当本节点正在驱动运动时补发 stop (纯监测退出不打扰遥控)
            if self.motion_driving:
                self._send_cmd('stop')
                time.sleep(0.1)
        except Exception:
            pass
        try:
            self._ctrl_sock.close()
        except Exception:
            pass
        self.get_logger().info('避障节点关闭')
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
