#!/bin/bash
# run_offline_depth.sh - 离线深度分析一键运行 (拍摄标定闭环的验证环节)
#
# 拉起 stereonet + camera_info (不开相机), 把 stereo_capture 拍的 raw 图对
# 逐组喂给 BPU 推理, 输出三区域近度并与 labels.csv 标定对比。
# 与在线避障完全同一套算法和阈值, 验证结果可直接指导 danger_disp 调参。
#
# 用法:
#   ./run_offline_depth.sh            # 分析 /app/stereo_captures
#   ./run_offline_depth.sh -d /path   # 指定目录
set -u

# 清理 Trae 沙箱注入的旧 libstdc++ (否则 libdnn 加载失败)
if echo "${LD_LIBRARY_PATH:-}" | grep -q "trae-cn-server"; then
    export LD_LIBRARY_PATH=$(echo "$LD_LIBRARY_PATH" | tr ':' '\n' | grep -v "trae-cn-server" | tr '\n' ':' | sed 's/:$//')
fi

_ros_log_base="${ROS_LOG_DIR:-${ROS_HOME:-$HOME/.ros}/log}"
if ! (mkdir -p "$_ros_log_base" 2>/dev/null && touch "$_ros_log_base/.wtest" 2>/dev/null); then
    export ROS_LOG_DIR="/tmp/ros_log"
    mkdir -p "$ROS_LOG_DIR" 2>/dev/null
else
    rm -f "$_ros_log_base/.wtest" 2>/dev/null
fi
unset _ros_log_base

PROJECT_ROOT="/app/gs130w_stereo"
TROS_SETUP="/opt/tros/humble/setup.bash"
STEREONET_MODEL="/opt/tros/humble/share/hobot_stereonet/config/DStereoV2.0.bin"
LOG_DIR="/tmp/offline_depth"
CAP_DIR="/app/stereo_captures"

while [ $# -gt 0 ]; do
    case "$1" in
        -d|--dir) CAP_DIR="$2"; shift 2 ;;
        *) shift ;;
    esac
done

[ -f "$TROS_SETUP" ] || { echo "[ERR] TROS 缺失"; exit 1; }
[ -f "$STEREONET_MODEL" ] || { echo "[ERR] stereonet 模型缺失: $STEREONET_MODEL"; exit 1; }
[ -d "$CAP_DIR" ] || { echo "[ERR] 拍摄目录不存在: $CAP_DIR"; exit 1; }

mkdir -p "$LOG_DIR"

# 确保没有占用相机/话题的残留进程
pkill -f 'stereonet_model_node' 2>/dev/null
pkill -f 'camera_info_publisher.py' 2>/dev/null
pkill -f 'mipi_cam' 2>/dev/null
pkill -f 'stereo_avoidance_node.py' 2>/dev/null
sleep 1

set +u
# shellcheck disable=SC1090
source "$TROS_SETUP"
set -u

cleanup() {
    pkill -f 'stereonet_model_node' 2>/dev/null
    pkill -f 'camera_info_publisher.py' 2>/dev/null
}
trap cleanup EXIT

echo "[START] camera_info_publisher ..."
python3 -u "$PROJECT_ROOT/launch/camera_info_publisher.py" \
    > "$LOG_DIR/camera_info.log" 2>&1 &
sleep 1

echo "[START] stereonet_model_node (BPU 推理) ..."
ros2 run hobot_stereonet stereonet_model_node --ros-args \
    -p stereonet_model_file_path:="$STEREONET_MODEL" \
    -p stereo_image_topic:=/image_combine_raw \
    -p publish_visual_enabled:=false \
    -p publish_pcd_enabled:=false \
    -p publish_rectify_bgr:=false \
    -p render_perf:=false \
    -p log_level:=warn \
    -p save_result_flag:=false \
    > "$LOG_DIR/stereonet.log" 2>&1 &

echo "[WAIT] 等 stereonet 初始化 (模型加载+DDS发现, 固定 10s)..."
sleep 10
if ! pgrep -f 'stereonet_model_node' > /dev/null; then
    echo "[ERR] stereonet 进程已退出, 看 $LOG_DIR/stereonet.log"
    exit 1
fi

echo "[RUN] 开始离线分析 ..."
python3 -u "$PROJECT_ROOT/scripts/offline_depth_analyze.py" --dir "$CAP_DIR"
RC=$?

echo "[DONE] 退出码 $RC, 日志在 $LOG_DIR/"
exit $RC
