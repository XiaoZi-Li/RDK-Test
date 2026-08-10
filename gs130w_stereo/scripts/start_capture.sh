#!/bin/bash
# start_capture.sh - 双目拍摄标定工具一键启动
#
# 链路: mipi_cam(双目) + hobot_codec(jpeg) + stereo_capture.py(网页:8095)
# 不起 stereonet/避障/websocket/AI — 只拍左右眼图, 存盘后人工标定矫正深度判断
#
# 两种模式 (自动判断):
#   独立模式: /image_combine_jpeg 无发布者 → 清场后自起 mipi_cam + codec
#   附加模式: 完整系统已在运行 (jpeg 话题有发布者) → 只起拍摄节点, 不动现有链路
#
# 用法:
#   ./start_capture.sh start     启动 (网页 http://<板端IP>:8095)
#   ./start_capture.sh stop      停止 (附加模式只停拍摄节点, 不动完整系统)
#   ./start_capture.sh restart   重启
#   ./start_capture.sh status    查看状态
#   ./start_capture.sh logs      看相机日志
set -u

# 清理 LD_LIBRARY_PATH 中 Trae 沙箱注入的路径
# (trae-cn-server 的 libstdc++.so.6 版本太旧, 会导致 mipi_cam/libdnn 崩溃: 总线错误)
if echo "${LD_LIBRARY_PATH:-}" | grep -q "trae-cn-server"; then
    export LD_LIBRARY_PATH=$(echo "$LD_LIBRARY_PATH" | tr ':' '\n' | grep -v "trae-cn-server" | tr '\n' ':' | sed 's/:$//')
fi

# ROS 日志目录: 沙箱/受限环境下 /root/.ros 可能实际不可写, touch 实测后回落 /tmp
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
CAP_PORT="${CAP_PORT:-8095}"
CAP_DIR="${CAP_DIR:-/app/stereo_captures}"

LOG_DIR="/tmp/gs130w_capture"
PID_FILE="$LOG_DIR/pids"

check_env() {
    [ -f "$TROS_SETUP" ] || { echo "[ERR] TROS 缺失: $TROS_SETUP"; exit 1; }
    [ -f "$PROJECT_ROOT/launch/gs130w_capture.launch.py" ] || { echo "[ERR] capture launch 缺失"; exit 1; }
    [ -f "$PROJECT_ROOT/scripts/stereo_capture.py" ] || { echo "[ERR] stereo_capture.py 缺失"; exit 1; }
}

# 只停拍摄节点自身 (附加模式 stop 用, 不动完整系统)
stop_capture_only() {
    echo "[STOP] 停止拍摄节点 (不动双目链路)..."
    pkill -f 'stereo_capture.py' 2>/dev/null
    sleep 1
    fuser -k "$CAP_PORT/tcp" 2>/dev/null
    echo "[STOP] 完成"
}

# 彻底清理: 拍摄工具自身 + 完整/轻量双目链路 (mipi_cam 硬件独占, 必须互斥)
stop_all() {
    echo "[STOP] 清理双目相关进程..."
    if [ -f "$PID_FILE" ]; then
        while read -r pid; do
            [ -n "$pid" ] && kill "$pid" 2>/dev/null
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    fi
    pkill -f 'stereo_capture.py' 2>/dev/null
    pkill -f 'gs130w_capture.launch.py' 2>/dev/null
    pkill -f 'gs130w_lite.launch.py' 2>/dev/null
    pkill -f 'gs130w_ai_overlay_v2.launch.py' 2>/dev/null
    pkill -f 'gs130w_dualcam' 2>/dev/null
    pkill -f 'mjpeg_bridge.py' 2>/dev/null
    pkill -f 'hobot_codec' 2>/dev/null
    pkill -f 'websocket' 2>/dev/null
    pkill -f 'camera_info_publisher.py' 2>/dev/null
    pkill -f 'stereonet_model_node' 2>/dev/null
    pkill -f 'stereo_avoidance_node.py' 2>/dev/null
    pkill -f 'mipi_cam' 2>/dev/null
    sleep 1
    fuser -k 8071/tcp 8072/tcp 8073/tcp 8090/tcp "$CAP_PORT/tcp" 2>/dev/null
    sleep 1
    # 清共享内存 (不删 sem.fastrtps_* 信号量, ros2 daemon 持有映射)
    rm -f /dev/shm/fastrtps_* 2>/dev/null
    echo "[STOP] 完成"
}

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
    mkdir -p "$LOG_DIR" "$CAP_DIR"
    : > "$PID_FILE"

    set +u
    # shellcheck disable=SC1090
    source "$TROS_SETUP"
    set -u

    # ===== 模式判断: 完整系统的双目链路是否已在运行 =====
    if ros2 topic info /image_combine_jpeg 2>/dev/null | grep -qE 'Publisher count: [1-9]'; then
        # ---------- 附加模式: 不动现有链路, 只起拍摄节点 ----------
        echo "[MODE] 检测到 /image_combine_jpeg 已有发布者 → 附加模式 (不动完整系统)"
        echo "attach" > "$LOG_DIR/mode"
        pkill -f 'stereo_capture.py' 2>/dev/null
        fuser -k "$CAP_PORT/tcp" 2>/dev/null
        sleep 1

        echo "[START] stereo_capture.py (网页 :$CAP_PORT, 存图 $CAP_DIR) ..."
        python3 -u "$PROJECT_ROOT/scripts/stereo_capture.py" \
            --port "$CAP_PORT" --dir "$CAP_DIR" \
            > "$LOG_DIR/capture.log" 2>&1 &
        echo $! >> "$PID_FILE"
        sleep 2
    else
        # ---------- 独立模式: 清场后自起 mipi_cam + codec ----------
        echo "[MODE] 双目链路未运行 → 独立模式 (自起 mipi_cam)"
        echo "standalone" > "$LOG_DIR/mode"

        stop_all 2>/dev/null
        sleep 1
        : > "$PID_FILE"

        echo "[START] 1/2 mipi_cam + jpeg codec (gs130w_capture.launch) ..."
        ros2 launch "$PROJECT_ROOT/launch/gs130w_capture.launch.py" \
            > "$LOG_DIR/cam.log" 2>&1 &
        echo $! >> "$PID_FILE"

        echo "[START] 等待双目 jpeg 出图..."
        if wait_topic_ready "/image_combine_jpeg" 30; then
            echo "[START] 双目出图 OK"
        else
            echo "[WARN] 可能没出图, 继续 (看 $LOG_DIR/cam.log)"
        fi
        sleep 2

        echo "[START] 2/2 stereo_capture.py (网页 :$CAP_PORT, 存图 $CAP_DIR) ..."
        python3 -u "$PROJECT_ROOT/scripts/stereo_capture.py" \
            --port "$CAP_PORT" --dir "$CAP_DIR" \
            > "$LOG_DIR/capture.log" 2>&1 &
        echo $! >> "$PID_FILE"
        sleep 2
    fi

    BOARD_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -z "$BOARD_IP" ] && BOARD_IP="<板端IP>"

    echo ""
    echo "================================================"
    echo " 双目拍摄标定工具启动完成 ($(cat "$LOG_DIR/mode"))"
    echo "================================================"
    echo " 网页:     http://$BOARD_IP:$CAP_PORT"
    echo " 存图目录: $CAP_DIR"
    echo " 标定文件: $CAP_DIR/labels.csv"
    echo " 日志:     $LOG_DIR/cam.log / capture.log"
    echo "================================================"
}

status_all() {
    echo "[STATUS] 拍摄标定工具:"
    if [ ! -f "$PID_FILE" ]; then
        echo "  未启动（PID 文件不存在：$PID_FILE）"
        return
    fi
    local names=(cam capture)
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

stop_smart() {
    # 附加模式只停拍摄节点; 独立模式全清
    if [ -f "$LOG_DIR/mode" ] && [ "$(cat "$LOG_DIR/mode")" = "attach" ]; then
        stop_capture_only
        rm -f "$LOG_DIR/mode" "$PID_FILE"
    else
        stop_all
        rm -f "$LOG_DIR/mode"
    fi
}

case "${1:-}" in
    start)   start ;;
    stop)    stop_smart ;;
    restart) stop_smart; sleep 1; start ;;
    status)  status_all ;;
    logs)    tail -n 50 "$LOG_DIR/cam.log" 2>/dev/null; tail -n 20 "$LOG_DIR/capture.log" 2>/dev/null ;;
    *)       echo "用法: $0 {start|stop|restart|status|logs}"; exit 1 ;;
esac
