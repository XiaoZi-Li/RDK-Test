#!/bin/bash
# start_all.sh - 双目/避障/手势/语音/YOLO 一键集成启动
#
# 运动控制优先级: 避障 > 语音 > 手势
#
# 用法:
#   ./start_all.sh start    # 一键启动全部功能
#   ./start_all.sh stop     # 停止全部
#   ./start_all.sh status   # 查看各组件状态
#   ./start_all.sh restart  # 重启
# ============================================================================

set -u

INTEGRATED_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="/tmp/integrated_system"
PID_FILE="$LOG_DIR/integrated.pids"

# 集成模式端口配置
export SIT_UDP_PORT="${SIT_UDP_PORT:-5006}"
export ARBITER_LISTEN_PORT="${ARBITER_LISTEN_PORT:-5005}"
export ARBITER_SIT_PORT="${ARBITER_SIT_PORT:-5006}"
export ARBITER_SIT_IP="${ARBITER_SIT_IP:-127.0.0.1}"

mkdir -p "$LOG_DIR"

# ---------- 工具函数 ----------
wait_for_udp() {
    local port=$1
    local name=$2
    local max_wait=${3:-20}
    echo "[WAIT] 等待 $name 在 UDP $port 就绪..."
    for i in $(seq 1 "$max_wait"); do
        if ss -ulnp 2>/dev/null | grep -q ":$port "; then
            echo "[WAIT] $name 已就绪"
            return 0
        fi
        sleep 0.5
    done
    echo "[WARN] $name 在 UDP $port 未就绪, 继续启动后续组件"
    return 1
}

wait_for_ros_topic() {
    local topic=$1
    local name=$2
    local max_wait=${3:-30}
    echo "[WAIT] 等待 ROS topic $topic ($name)..."
    for i in $(seq 1 "$max_wait"); do
        if ros2 topic list 2>/dev/null | grep -q "$topic"; then
            echo "[WAIT] $name topic 已就绪"
            return 0
        fi
        sleep 1
    done
    echo "[WARN] $name topic $topic 未就绪, 继续启动后续组件"
    return 1
}

record_pid() {
    local name=$1
    local pid=$2
    echo "$name:$pid" >> "$PID_FILE"
}

# ---------- start ----------
start_all() {
    echo "============================================================"
    echo " 一键集成启动  $(date '+%Y-%m-%d %H:%M:%S')"
    echo " 运动控制优先级: 避障 > 语音 > 手势"
    echo " 仲裁器: $ARBITER_SIT_IP:$ARBITER_LISTEN_PORT → sit.py:$ARBITER_SIT_PORT"
    echo "============================================================"

    # 先清理
    echo "[INIT] 清理已有进程..."
    stop_all >/dev/null 2>&1 || true
    sleep 2
    : > "$PID_FILE"

    # ---------- 1. 运动仲裁器 ----------
    echo "[START] 1/7 启动运动仲裁器 (UDP:$ARBITER_LISTEN_PORT → $ARBITER_SIT_PORT)..."
    python3 "$INTEGRATED_DIR/motion_arbiter.py" \
        --listen-port "$ARBITER_LISTEN_PORT" \
        --sit-port "$ARBITER_SIT_PORT" \
        --sit-ip "$ARBITER_SIT_IP" \
        > "$LOG_DIR/arbiter.log" 2>&1 &
    record_pid "arbiter" $!
    wait_for_udp "$ARBITER_LISTEN_PORT" "运动仲裁器"
    sleep 1

    # ---------- 2. 双目深度 + AI ----------
    echo "[START] 2/7 启动双目深度与 AI 节点..."
    /app/gs130w_stereo/scripts/start_v2.sh start > "$LOG_DIR/start_v2.log" 2>&1
    # start_v2.sh 会以后台方式启动子进程, 脚本本身很快返回
    sleep 5

    # ---------- 3. 精简机器人 (sit.py:5006 + IMU + WS桥 + ROS/UDP桥) ----------
    echo "[START] 3/7 启动精简机器人系统..."
    "$INTEGRATED_DIR/start_robot_minimal.sh" start > "$LOG_DIR/robot_minimal.log" 2>&1
    # start_robot_minimal.sh 也会后台启动子进程
    wait_for_udp "$SIT_UDP_PORT" "运动中枢 sit.py"
    sleep 2

    # ---------- 4. 避障 ----------
    echo "[START] 4/7 启动双目避障..."
    /app/gs130w_stereo/scripts/start_avoidance.sh start > "$LOG_DIR/start_avoidance.log" 2>&1
    sleep 3

    # ---------- 5. YOLO 显示 ----------
    echo "[START] 5/7 启动 YOLO 显示 (http://<ip>:8093)..."
    cd /app/standalone
    python3 yolo_display.py > "$LOG_DIR/yolo_display.log" 2>&1 &
    record_pid "yolo" $!
    cd - > /dev/null
    sleep 2

    # ---------- 6. 手势控制 ----------
    echo "[START] 6/7 启动手势控制 (USB 摄像头)..."
    cd /app/standalone
    python3 gesture_control.py > "$LOG_DIR/gesture_control.log" 2>&1 &
    record_pid "gesture" $!
    cd - > /dev/null
    sleep 2

    # ---------- 7. 语音控制 ----------
    echo "[START] 7/7 启动语音控制..."
    python3 /app/puppy_ws/tools/voice_control_standalone.py \
        --mic plughw:1,0 \
        --speaker plughw:0,0 \
        --gain 10 \
        --aggressiveness 2 \
        --silence 1.0 \
        > "$LOG_DIR/voice_control.log" 2>&1 &
    record_pid "voice" $!

    echo ""
    echo "============================================================"
    echo " 全部组件已启动完成"
    echo "------------------------------------------------------------"
    echo "  仲裁器日志      $LOG_DIR/arbiter.log"
    echo "  双目/AI 日志    $LOG_DIR/start_v2.log"
    echo "  机器人日志      $LOG_DIR/robot_minimal.log"
    echo "  避障日志        $LOG_DIR/start_avoidance.log"
    echo "  YOLO日志        $LOG_DIR/yolo_display.log"
    echo "  手势日志        $LOG_DIR/gesture_control.log"
    echo "  语音日志        $LOG_DIR/voice_control.log"
    echo "------------------------------------------------------------"
    echo "  查看状态: $0 status"
    echo "  停止全部: $0 stop"
    echo "============================================================"
}

# ---------- stop ----------
stop_all() {
    echo "============================================================"
    echo "[STOP] 停止一键集成系统  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"

    # 1. 停止独立进程
    echo "[STOP] 1/4 停止语音/手势/YOLO/仲裁器..."
    pkill -f 'voice_control_standalone.py' 2>/dev/null || true
    pkill -f 'gesture_control.py' 2>/dev/null || true
    pkill -f 'yolo_display.py' 2>/dev/null || true
    pkill -f 'motion_arbiter.py' 2>/dev/null || true

    # 2. 停止避障
    echo "[STOP] 2/4 停止避障..."
    /app/gs130w_stereo/scripts/start_avoidance.sh stop 2>/dev/null || true

    # 3. 停止精简机器人
    echo "[STOP] 3/4 停止精简机器人系统..."
    "$INTEGRATED_DIR/start_robot_minimal.sh" stop 2>/dev/null || true

    # 4. 停止双目/AI
    echo "[STOP] 4/4 停止双目深度与 AI..."
    /app/gs130w_stereo/scripts/start_v2.sh stop 2>/dev/null || true

    # 清理 PID 文件
    [ -f "$PID_FILE" ] && : > "$PID_FILE"

    echo "[STOP] 完成"
}

# ---------- status ----------
status_all() {
    echo "============================================================"
    echo "[STATUS] 一键集成系统  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"

    check_proc() {
        local name=$1
        local pattern=$2
        if pgrep -f "$pattern" > /dev/null 2>&1; then
            echo "✅ $name"
        else
            echo "❌ $name"
        fi
    }

    check_proc "运动仲裁器" "motion_arbiter.py"
    check_proc "双目深度+AI (v2)" "start_v2.sh"
    check_proc "运动中枢 sit.py" "/app/pydev_demo/puppypi_control/sit.py"
    check_proc "IMU 节点" "imu_node_ros2"
    check_proc "WebSocket 桥" "ws_bridge_node"
    check_proc "ROS/UDP 桥" "ros_udp_bridge"
    check_proc "双目避障" "stereo_avoidance_node.py"
    check_proc "YOLO 显示" "yolo_display.py"
    check_proc "手势控制" "gesture_control.py"
    check_proc "语音控制" "voice_control_standalone.py"

    if ss -ulnp 2>/dev/null | grep -q ":$ARBITER_LISTEN_PORT "; then
        echo "✅ UDP $ARBITER_LISTEN_PORT (仲裁器)"
    else
        echo "❌ UDP $ARBITER_LISTEN_PORT (仲裁器)"
    fi

    if ss -ulnp 2>/dev/null | grep -q ":$SIT_UDP_PORT "; then
        echo "✅ UDP $SIT_UDP_PORT (sit.py)"
    else
        echo "❌ UDP $SIT_UDP_PORT (sit.py)"
    fi

    echo "============================================================"
}

# ---------- main ----------
case "${1:-}" in
    start)
        start_all
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        sleep 3
        start_all
        ;;
    status)
        status_all
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
