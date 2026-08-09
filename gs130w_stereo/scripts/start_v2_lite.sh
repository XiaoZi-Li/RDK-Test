#!/bin/bash
# GS130W 轻量版一键启动 (独立脚本, 与完整版 start_v2.sh 无关)
#
# 只跑避障必需链路: mipi_cam(双目) + stereonet(深度) + camera_info
# 不起: codec / websocket / AI 叠加 / mjpeg_bridge / http server (省 CPU/带宽)
#
# 用法：
#   ./start_v2_lite.sh start    启动轻量版
#   ./start_v2_lite.sh stop     停止
#   ./start_v2_lite.sh restart  重启
#   ./start_v2_lite.sh status   查看状态
#   ./start_v2_lite.sh logs     查看日志
set -u

# 清理 LD_LIBRARY_PATH 中 Trae 沙箱注入的路径
# (trae-cn-server 的 libstdc++.so.6 版本太旧, 会导致 mipi_cam/libdnn 崩溃: 总线错误)
if echo "${LD_LIBRARY_PATH:-}" | grep -q "trae-cn-server"; then
    export LD_LIBRARY_PATH=$(echo "$LD_LIBRARY_PATH" | tr ':' '\n' | grep -v "trae-cn-server" | tr '\n' ':' | sed 's/:$//')
fi

# ROS 日志目录: 沙箱/受限环境下 /root/.ros 可能实际不可写(-w 测试不准),
# 会导致 ros2 launch 和 rclpy.init() 全部 Permission denied.
# 用 touch 实测, 不可写则回落到 /tmp/ros_log
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
GDC_BIN="/root/multimedia_samples/vp_sensors/gdc_bin/sc132gs_1088X1280_gdc.bin"
CALIB_YAML="/opt/tros/humble/lib/mipi_cam/config/SC132gs_dual_calibration.yaml"

LOG_DIR="/tmp/gs130w_lite"
PID_FILE="$LOG_DIR/pids"

check_env() {
    [ -f "$TROS_SETUP" ] || { echo "[ERR] TROS 缺失: $TROS_SETUP"; exit 1; }
    [ -f "$GDC_BIN" ] || { echo "[ERR] GDC bin 缺失: $GDC_BIN"; exit 1; }
    [ -f "$CALIB_YAML" ] || { echo "[ERR] 标定 yaml 缺失: $CALIB_YAML"; exit 1; }
    [ -f "$PROJECT_ROOT/launch/gs130w_lite.launch.py" ] || { echo "[ERR] lite launch 缺失"; exit 1; }
    [ -f "$PROJECT_ROOT/launch/camera_info_publisher.py" ] || { echo "[ERR] camera_info_publisher.py 缺失"; exit 1; }
}

# 彻底清理: 轻量版自身 + 完整版双目链路 (切换版本时避免硬件占用冲突)
stop_all() {
    echo "[STOP] 清理 gs130w lite / v2 进程..."
    # 先按 PID 文件 kill
    if [ -f "$PID_FILE" ]; then
        while read -r pid; do
            [ -n "$pid" ] && kill "$pid" 2>/dev/null
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    fi
    # 轻量版自身
    pkill -f 'gs130w_lite.launch.py' 2>/dev/null
    # 完整版链路 (切换版本时清理)
    pkill -f 'gs130w_ai_overlay_v2.launch.py' 2>/dev/null
    pkill -f 'gs130w_dualcam' 2>/dev/null
    pkill -f 'mjpeg_bridge.py' 2>/dev/null
    pkill -f 'hobot_codec' 2>/dev/null
    pkill -f 'websocket' 2>/dev/null
    pkill -f 'mono2d_body_detection' 2>/dev/null
    pkill -f 'face_landmarks_detection' 2>/dev/null
    pkill -f 'hand_lmk_detection' 2>/dev/null
    pkill -f 'hand_gesture_detection' 2>/dev/null
    # 公共链路
    pkill -f 'camera_info_publisher.py' 2>/dev/null
    pkill -f 'stereonet_model_node' 2>/dev/null
    pkill -f 'mipi_cam' 2>/dev/null
    sleep 1
    # 强杀完整版端口占用 (8071/8072/8073/8090)
    fuser -k 8071/tcp 8072/tcp 8073/tcp 8090/tcp 2>/dev/null
    sleep 1
    # 清共享内存
    # 注意: 不要删 sem.fastrtps_* 信号量文件! ros2 daemon 等长驻进程持有其映射,
    #       删除后新建段状态不一致, 会导致 DDS 发现/订阅异常 (stereonet 收不到 camera_info)
    rm -f /dev/shm/fastrtps_* 2>/dev/null
    echo "[STOP] 完成"
}

# 等待 topic 出现（轮询，比 sleep 可靠）
wait_topic_ready() {
    local topic="$1"
    local max_wait="${2:-30}"
    local waited=0
    while [ $waited -lt $max_wait ]; do
        if ros2 topic list 2>/dev/null | grep -q "^${topic}$"; then
            return 0
        fi
        sleep 1
        waited=$((waited+1))
    done
    echo "[WARN] 等待 $topic 超时（${max_wait}s）"
    return 1
}

start() {
    check_env
    mkdir -p "$LOG_DIR"
    : > "$PID_FILE"

    # 先清残留 (含完整版链路)
    stop_all 2>/dev/null
    sleep 1

    set +u
    # shellcheck disable=SC1090
    source "$TROS_SETUP"
    set -u

    echo "[START] 1/2 mipi_cam + stereonet (gs130w_lite.launch) ..."
    ros2 launch "$PROJECT_ROOT/launch/gs130w_lite.launch.py" \
        > "$LOG_DIR/stereo_lite.log" 2>&1 &
    echo $! >> "$PID_FILE"

    # 等 /image_combine_raw 出现 (lite 无 codec, 没有 jpeg topic)
    echo "[START] 等待 mipi_cam 出图..."
    if wait_topic_ready "/image_combine_raw" 30; then
        echo "[START] mipi_cam 出图 OK"
    else
        echo "[WARN] mipi_cam 可能没出图, 继续 (看 $LOG_DIR/stereo_lite.log)"
    fi
    sleep 2

    echo "[START] 2/2 camera_info_publisher ..."
    python3 "$PROJECT_ROOT/launch/camera_info_publisher.py" \
        > "$LOG_DIR/camera_info.log" 2>&1 &
    echo $! >> "$PID_FILE"

    sleep 2

    echo ""
    echo "================================================"
    echo " GS130W 轻量版启动完成 (无视频流)"
    echo "================================================"
    echo " 已裁剪: codec / websocket / AI叠加 / MJPEG桥"
    echo " 保留:   mipi_cam 双目 + stereonet (避障数据源)"
    echo " 日志:   $LOG_DIR/stereo_lite.log"
    echo "================================================"
}

status_all() {
    echo "[STATUS] gs130w lite 进程状态:"
    if [ ! -f "$PID_FILE" ]; then
        echo "  未启动（PID 文件不存在：$PID_FILE）"
        return
    fi
    local names=(stereo_lite camera_info)
    local i=0 pid name
    while read -r pid; do
        name="${names[$i]:-unknown}"
        if kill -0 "$pid" 2>/dev/null; then
            echo "  [OK]   $name  pid=$pid"
        else
            echo "  [DEAD] $name  pid=$pid"
        fi
        i=$((i+1))
    done < "$PID_FILE"
}

case "${1:-}" in
    start)   start ;;
    stop)    stop_all ;;
    restart) stop_all; sleep 1; start ;;
    status)  status_all ;;
    logs)    tail -n 50 "$LOG_DIR/stereo_lite.log" ;;
    *)       echo "用法: $0 {start|stop|restart|status|logs}"; exit 1 ;;
esac
