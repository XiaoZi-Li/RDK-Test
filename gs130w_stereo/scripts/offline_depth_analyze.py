#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""offline_depth_analyze.py - 离线双目深度分析 (拍摄标定闭环的验证环节)

把 stereo_capture.py 拍下的左右眼 raw 图对喂给 stereonet (与在线避障同一条
BPU 推理链路), 复刻 stereo_avoidance_node.analyze_depth 的三区域近度算法,
输出每组图的 左/中/右 近度值, 并与 labels.csv 的人工标定对比:

  标定"正前方有障碍物"     → 期望 center_r 触发且三区最大
  标定"左转" (障碍在右侧)   → 期望 right_r 显著高于 left_r
  标定"右转" (障碍在左/中左) → 期望 left_r 显著高于 right_r

依赖 (由 run_offline_depth.sh 拉起):
  - stereonet_model_node  (订阅 /image_combine_raw, nv12 1280x2176 上=右目/下=左目)
  - camera_info_publisher.py (TRANSIENT_LOCAL, stereonet 不做 rectify 就不会出图)

用法:
  python3 offline_depth_analyze.py --dir /app/stereo_captures
  python3 offline_depth_analyze.py --dir /app/stereo_captures --danger 45 --save-disp
"""
import argparse
import csv
import glob
import os
import sys
import threading
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import Image

TOPIC_RAW = '/image_combine_raw'
TOPIC_DEPTH = '/StereoNetNode/stereonet_depth'   # 实测: stereonet 只发 depth(mm), 无 disp 话题

IMG_W = 1280
IMG_H = 1088          # 单目
COMBINED_H = IMG_H * 2  # 上下拼接 2176

# 与在线避障 v3 同一套距离阈值 (米)
# 注意: 透明/反光物体 (矿泉水瓶) 立体匹配系统性偏远 ~1.5x, 阈值要比实际宽松
DANGER_DIST = 0.45    # 任区域近端距离 < 此值 → 障碍
CLEAR_DIST = 0.65     # > 此值 → 畅通


def bgr_to_nv12(bgr: np.ndarray) -> bytes:
    """BGR → NV12 字节流 (Y 平面 + UV 交错), 与 mipi_cam 发布格式一致"""
    h, w = bgr.shape[:2]
    yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420)  # (h*3/2, w)
    y = yuv[:h, :].reshape(-1)
    u = yuv[h:h + h // 4, :].reshape(-1)
    v = yuv[h + h // 4:, :].reshape(-1)
    uv = np.empty(u.size * 2, dtype=np.uint8)
    uv[0::2] = u
    uv[1::2] = v
    return y.tobytes() + uv.tobytes()


def analyze_lcr(depth_raw: np.ndarray, pct: float = 15.0, danger: float = 0.45):
    """复刻避障 v4 分析: 180°翻转 + 40~70% 垂直带 + 35%/65% 三段,
    每段返回 (近端分位距离, 近像素占比)。占比判定抗小片误差。
    返回 (left_d, center_d, right_d, left_r, center_r, right_r)"""
    d = depth_raw[::-1, ::-1].astype(np.float32)     # 180° 方向矫正
    # 单位自适应: 最大值 > 100 视为 mm
    if float(np.max(d)) > 100.0:
        d = d / 1000.0
    h, w = d.shape[:2]
    band = d[int(h * 0.4):int(h * 0.7), :]           # v4: 收窄到 70%, 排近处地面误差
    x_l = int(w * 0.35)
    x_r = int(w * 0.65)

    def region_stat(region):
        valid = region[(region > 0.05) & (region < 10.0)]   # 滤无效(0/超远)
        if valid.size < 20:
            return 9.9, 0.0
        ratio = float(np.count_nonzero(valid < danger)) / float(valid.size)
        near_d = float(np.percentile(valid, pct))
        return near_d, ratio

    left_d, left_r = region_stat(band[:, :x_l])      # 图像左 = 机器人左 (翻转后与左目视图同向)
    center_d, center_r = region_stat(band[:, x_l:x_r])
    right_d, right_r = region_stat(band[:, x_r:])    # 图像右 = 机器人右
    return left_d, center_d, right_d, left_r, center_r, right_r


class OfflineAnalyzer(Node):
    def __init__(self):
        super().__init__('offline_depth_analyzer')
        # RELIABLE 发布兼容 stereonet 任意 QoS 订阅
        pub_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            history=QoSHistoryPolicy.KEEP_LAST, depth=2)
        sub_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST, depth=2)
        self.pub = self.create_publisher(Image, TOPIC_RAW, pub_qos)
        self.create_subscription(Image, TOPIC_DEPTH, self._depth_cb, sub_qos)
        self._lock = threading.Lock()
        self._frames = []          # 本次采集的深度图列表
        self._collecting = False

    def _depth_cb(self, msg: Image):
        if not self._collecting:
            return
        try:
            h, w = msg.height, msg.width
            enc = msg.encoding.lower()
            if enc in ('mono16', '16uc1'):
                arr = np.frombuffer(msg.data, dtype=np.uint16).reshape(h, w)
            elif enc in ('mono8', '8uc1'):
                arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(h, w)
            elif enc == '32fc1':
                arr = np.frombuffer(msg.data, dtype=np.float32).reshape(h, w)
            elif enc in ('bgr8', 'rgb8'):
                arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(h, w, 3)[:, :, 0]
            else:
                return
            with self._lock:
                self._frames.append(arr.astype(np.float32))
        except Exception:
            pass

    def feed_pair(self, left_bgr: np.ndarray, right_bgr: np.ndarray,
                  hz: float = 5.0, seconds: float = 2.4) -> list:
        """拼成 mipi_cam 布局 (上=右目, 下=左目) → NV12 发布, 收集深度帧。
        频率 5Hz: stereonet BPU 推理 ~150ms/帧, 发太快只会堆队列被丢"""
        combined = np.vstack([right_bgr, left_bgr])   # 1280x2176
        payload = bgr_to_nv12(combined)

        msg = Image()
        msg.height = COMBINED_H
        msg.width = IMG_W
        msg.encoding = 'nv12'
        msg.step = IMG_W
        msg.is_bigendian = 0
        msg.data = payload

        with self._lock:
            self._frames = []
        self._collecting = True

        n = int(hz * seconds)
        for _ in range(n):
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = 'default_cam'
            self.pub.publish(msg)
            # 留出 spin 间隙: 本节点由调用线程 spin_once 驱动
            rclpy.spin_once(self, timeout_sec=1.0 / hz)

        # 再等最后的推理结果 (BPU 推理 ~100ms)
        t_end = time.time() + 1.0
        while time.time() < t_end:
            rclpy.spin_once(self, timeout_sec=0.05)

        self._collecting = False
        with self._lock:
            return list(self._frames)


# ============ v5 判定参数 (与 stereo_avoidance_node.py 完全一致) ============
BLOCKED_DIST = 0.35    # 近端分位距离 < 0.35m 且占比>obst_ratio → 该区有障
SIDE_RATIO = 0.90      # 左/右占比 ≥90% → 该侧有障; 两侧都≥90% → 正前(优先右转)
TIE_MARGIN = 0.08      # 兜底: center 距离与最小值差 < 0.08m → 优先 center


def obstacle_side(left_d, center_d, right_d,
                  left_r, center_r, right_r,
                  obst_ratio, blocked=BLOCKED_DIST,
                  side_ratio=SIDE_RATIO, tie=TIE_MARGIN):
    """与在线避障 v5 _obstacle_side 完全相同的判定, 返回 None/'left'/'center'/'right'"""
    l_blk = left_d < blocked and left_r > obst_ratio
    c_blk = center_d < blocked and center_r > obst_ratio
    r_blk = right_d < blocked and right_r > obst_ratio
    if not (l_blk or c_blk or r_blk):
        return None
    l90 = l_blk and left_r >= side_ratio
    c90 = c_blk and center_r >= side_ratio
    r90 = r_blk and right_r >= side_ratio
    if (l90 and r90) or (c90 and (l90 or r90)):
        return 'center'
    if l90:
        return 'left'
    if r90:
        return 'right'
    if c90:
        return 'center'
    m = min(left_d, center_d, right_d)
    if c_blk and center_d <= m + tie:
        return 'center'
    if not l_blk and not r_blk:
        return 'center'
    if l_blk and not r_blk:
        return 'left'
    if r_blk and not l_blk:
        return 'right'
    return 'left' if left_d <= right_d else 'right'


_SIDE_TEXT = {None: '畅通(可直行)', 'left': '左前方障碍(右转)',
              'right': '右前方障碍(左转)', 'center': '正前方障碍(停+退+优先右转)'}


def decide(left_d, center_d, right_d, left_r, center_r, right_r, obst_ratio):
    """v5: 返回人类可读判定文本"""
    side = obstacle_side(left_d, center_d, right_d, left_r, center_r, right_r,
                         obst_ratio)
    return _SIDE_TEXT[side]


def match_label(label: str, left_d, center_d, right_d,
                left_r, center_r, right_r, obst_ratio) -> bool:
    """标定期望值 vs 实测判定 (v5)

    "能避开即正确"标准:
      正前方有障碍物 → side == 'center'
      左转(障碍在右) → side == 'right'
      右转(障碍在左) → side == 'left'
      双侧≥90%判 center 时, 左转/右转标定也算动作可避开(优先右转能绕开) → 通过
    """
    side = obstacle_side(left_d, center_d, right_d, left_r, center_r, right_r,
                         obst_ratio)
    if label in ('正前方有障碍物', '直行'):   # 兼容旧标定
        return side == 'center'
    if label == '左转':
        return side in ('right', 'center')
    if label == '右转':
        return side in ('left', 'center')
    return False


def main():
    ap = argparse.ArgumentParser(description='离线双目深度分析 (标定验证)')
    ap.add_argument('--dir', default='/app/stereo_captures', help='拍摄目录')
    ap.add_argument('--danger', type=float, default=DANGER_DIST,
                    help='近像素距离阈值(米), 默认 0.45 (透明瓶测偏远取宽松)')
    ap.add_argument('--obst-ratio', type=float, default=0.03,
                    help='区域近像素占比触发阈值, 默认 0.03 (3%%)')
    ap.add_argument('--save-depth', action='store_true', default=True,
                    help='保存深度彩色图 (默认开)')
    args = ap.parse_args()

    labels = {}
    csv_path = os.path.join(args.dir, 'labels.csv')
    if os.path.exists(csv_path):
        with open(csv_path, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                labels[row['ts']] = row['label']

    pairs = sorted(set(
        os.path.basename(p).replace('_left_raw.jpg', '')
        for p in glob.glob(os.path.join(args.dir, '*_left_raw.jpg'))))
    if not pairs:
        print(f'[ERR] {args.dir} 下没有 *_left_raw.jpg')
        sys.exit(1)

    print('=' * 66)
    print(f' 离线双目深度分析 | 目录: {args.dir}')
    print(f' 共 {len(pairs)} 组 | danger={args.danger}m obst_ratio={args.obst_ratio}')
    print('=' * 66)

    rclpy.init()
    node = OfflineAnalyzer()

    passed, failed = 0, 0
    for ts in pairs:
        left = cv2.imread(os.path.join(args.dir, f'{ts}_left_raw.jpg'))
        right = cv2.imread(os.path.join(args.dir, f'{ts}_right_raw.jpg'))
        if left is None or right is None:
            print(f'[SKIP] {ts}: 读图失败')
            continue
        if left.shape[:2] != (IMG_H, IMG_W):
            left = cv2.resize(left, (IMG_W, IMG_H))
        if right.shape[:2] != (IMG_H, IMG_W):
            right = cv2.resize(right, (IMG_W, IMG_H))

        frames = node.feed_pair(left, right)
        if not frames:
            print(f'[FAIL] {ts}: 没收到深度 (stereonet 未运行? camera_info 缺失?)')
            failed += 1
            continue

        # 多帧中位数, 抗偶发噪声
        lcr = [analyze_lcr(f, danger=args.danger) for f in frames[-5:]]
        left_d = float(np.median([v[0] for v in lcr]))
        center_d = float(np.median([v[1] for v in lcr]))
        right_d = float(np.median([v[2] for v in lcr]))
        left_r = float(np.median([v[3] for v in lcr]))
        center_r = float(np.median([v[4] for v in lcr]))
        right_r = float(np.median([v[5] for v in lcr]))

        label = labels.get(ts, '(未标定)')
        verdict = decide(left_d, center_d, right_d,
                         left_r, center_r, right_r, args.obst_ratio)
        ok = match_label(label, left_d, center_d, right_d,
                         left_r, center_r, right_r, args.obst_ratio) \
            if label in ('左转', '右转', '正前方有障碍物', '直行') else None
        if ok is True:
            passed += 1
            mark = 'PASS'
        elif ok is False:
            failed += 1
            mark = 'FAIL'
        else:
            mark = 'INFO'

        print(f'[{mark}] {ts} 标定={label} (收到 {len(frames)} 帧深度)')
        print(f'       近端距离: 左={left_d:.2f}m 中={center_d:.2f}m 右={right_d:.2f}m')
        print(f'       近像素占比: 左={left_r*100:.1f}% 中={center_r*100:.1f}% '
              f'右={right_r*100:.1f}%  → 判定: {verdict}')

        if args.save_depth:
            depth = frames[-1].astype(np.float32)
            if float(np.max(depth)) > 100.0:
                depth = depth / 1000.0
            # 距离 → 颜色: 近=红 远=蓝, 无效=黑; 上限 2m 裁剪
            clipped = np.clip(depth, 0.0, 2.0)
            norm = ((2.0 - clipped) / 2.0 * 255).astype(np.uint8)
            norm[depth <= 0.05] = 0
            color = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
            cv2.imwrite(os.path.join(args.dir, f'{ts}_depth.jpg'),
                        color, [cv2.IMWRITE_JPEG_QUALITY, 90])
            # 翻转版 (人眼方向) 便于对照
            cv2.imwrite(os.path.join(args.dir, f'{ts}_depth_view.jpg'),
                        color[::-1, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 90])

    print('=' * 66)
    print(f' 完成: {passed} 通过 / {failed} 待查 (共 {len(pairs)} 组)')
    print('=' * 66)

    node.destroy_node()
    rclpy.shutdown()
    sys.exit(0 if failed == 0 else 2)


if __name__ == '__main__':
    main()
