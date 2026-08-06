#!/bin/bash
# start_tros_hand_bpu.sh - 启动 TROS BPU 手势链路
# fb 模式: 用 ROS topic /image_combine_raw 拿图（usb_camera_bpu.py 提供）
# 不开 USB cam 节点（避免抢设备）
#
# 启动后:
#   /hobot_mono2d_body_detection
#   /hobot_hand_lmk_detection   (21 关键点)
#   /hobot_hand_gesture_detection (8 类手势)
set -e
LOG=/tmp/rdk_gesture/tros_hand.log
mkdir -p /tmp/rdk_gesture

echo "[1/5] 杀旧的 TROS 手势节点"
pkill -9 -f 'mono2d_body_detection|hand_lmk_detection|hand_gesture_detection' 2>/dev/null || true
sleep 2

echo "[2/5] source TROS"
source /opt/tros/humble/setup.bash
export HOME=/root

echo "[3/5] mono2d_body_detection (BPU)"
setsid ros2 run mono2d_body_detection mono2d_body_detection --ros-args \
    -p model_file_name:=/opt/tros/humble/lib/mono2d_body_detection/config/multitask_body_head_face_hand_kps_960x544.hbm \
    -p model_type:=0 \
    -p is_shared_mem_sub:=0 \
    -p ros_img_topic_name:=/image_combine_raw \
    -p ai_msg_pub_topic_name:=/hobot_mono2d_body_detection \
    -p is_sync_mode:=0 -p image_gap:=1 -p dump_render_img:=0 \
    >> $LOG 2>&1 < /dev/null &
sleep 5

echo "[4/5] hand_lmk_detection (BPU)"
setsid ros2 run hand_lmk_detection hand_lmk_detection --ros-args \
    -p model_file_name:=/opt/tros/humble/lib/hand_lmk_detection/config/handLMKs.hbm \
    -p ai_msg_pub_topic_name:=/hobot_hand_lmk_detection \
    -p ai_msg_sub_topic_name:=/hobot_mono2d_body_detection \
    -p is_shared_mem_sub:=0 \
    -p ros_img_topic_name:=/image_combine_raw \
    >> $LOG 2>&1 < /dev/null &
sleep 3

echo "[5/5] hand_gesture_detection (BPU 1252 FPS)"
setsid ros2 run hand_gesture_detection hand_gesture_detection --ros-args \
    -p model_file_name:=/opt/tros/humble/lib/hand_gesture_detection/config/gestureDet_8x21.hbm \
    -p ai_msg_pub_topic_name:=/hobot_hand_gesture_detection \
    -p ai_msg_sub_topic_name:=/hobot_hand_lmk_detection \
    -p is_dynamic_gesture:=False \
    -p time_interval_sec:=0.25 -p threshold:=0.5 \
    >> $LOG 2>&1 < /dev/null &
sleep 4

echo
echo "==[状态] 进程数 (期望 6+)=="
pgrep -af 'mono2d_body|hand_lmk|hand_gesture' | wc -l

echo "==[状态] /image_combine_raw Publisher count=="
timeout 4 ros2 topic info /image_combine_raw 2>&1 | grep 'Publisher count' || echo "no /image_combine_raw"

echo "==[状态] /hobot_mono2d_body_detection Publisher count=="
timeout 4 ros2 topic info /hobot_mono2d_body_detection 2>&1 | grep 'Publisher count' || echo "no /mono2d"

echo "==[状态] /hobot_hand_gesture_detection Publisher count=="
timeout 4 ros2 topic info /hobot_hand_gesture_detection 2>&1 | grep 'Publisher count' || echo "no /gesture"

echo
echo "日志: $LOG"
