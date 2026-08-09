#!/bin/bash
# start_robot_minimal.sh - 集成模式下的精简机器人启动
#
# 与 start_robot.sh 的区别:
#   - 只启动运动中枢 (sit.py) + IMU + WebSocket桥 + ROS/UDP桥
#   - 不启动 full_system_cloud 里的 decision_node / usb_asr / intent_router /
#     gesture_adapter / LLM / TTS, 避免与 standalone 语音/手势冲突
#   - sit.py 默认绑到 5006, 由 motion_arbiter 在 5005 做仲裁后转发
#
# 用法:
#   ./start_robot_minimal.sh start
#   ./start_robot_minimal.sh stop
#   ./start_robot_minimal.sh status
# ============================================================================

set -u

TROS_SETUP="/opt/tros/humble/setup.bash"
WS_ROOT="/app/puppy_ws"
WS_SETUP="$WS_ROOT/install/setup.bash"
SIT_DIR="/app/pydev_demo/puppypi_control"
SIT_PY="$SIT_DIR/sit.py"
SIT_PYTHON="/root/anaconda3/envs/puppy/bin/python"

LOG_DIR="/tmp/integrated_system"
mkdir -p "$LOG_DIR"
PID_FILE="$LOG_DIR/robot_minimal.pids"

# 清理 LD_LIBRARY_PATH 中 Trae 沙箱注入的路径
# (trae-cn-server 的 libstdc++.so.6 版本太旧, 会导致 rclpy 加载失败)
if echo "$LD_LIBRARY_PATH" | grep -q "trae-cn-server"; then
    export LD_LIBRARY_PATH=$(echo "$LD_LIBRARY_PATH" | tr ':' '\n' | grep -v "trae-cn-server" | tr '\n' ':' | sed 's/:$//')
fi

# 集成模式: sit.py 绑 5006, 仲裁器在 5005
export SIT_UDP_PORT="${SIT_UDP_PORT:-5006}"

# 后台启动函数: 用 nohup 让进程脱离终端, 避免被父 shell 退出杀掉
# 同时清理 LD_LIBRARY_PATH 中的 trae-cn-server 路径, 防止 libstdc++ 版本冲突
launch_bg() {
    local logfile=$1
    shift
    local clean_llp
    clean_llp=$(echo "$LD_LIBRARY_PATH" | tr ':' '\n' | grep -v "trae-cn-server" | tr '\n' ':' | sed 's/:$//')
    LD_LIBRARY_PATH="$clean_llp" nohup "$@" > "$logfile" 2>&1 &
    echo $!
}

source_tros() {
    set +u
    # shellcheck disable=SC1090
    source "$TROS_SETUP"
    set -u
}

source_ws() {
    set +u
    # shellcheck disable=SC1090
    source "$WS_SETUP"
    set -u
}

check_env() {
    [ -f "$TROS_SETUP" ] || { echo "[ERROR] TROS 未安装: $TROS_SETUP"; exit 1; }
    [ -f "$SIT_PY" ] || { echo "[ERROR] sit.py 不存在: $SIT_PY"; exit 1; }
    [ -f "$WS_SETUP" ] || { echo "[ERROR] workspace 未编译: $WS_SETUP"; exit 1; }
    [ -x "$SIT_PYTHON" ] || { echo "[ERROR] puppy env 不存在: $SIT_PYTHON"; exit 1; }
}

start_all() {
    check_env
    echo "[START] 清理旧进程..."
    stop_all 2>/dev/null
    sleep 1
    : > "$PID_FILE"

    # ---------- 1. sit.py (运动中枢) ----------
    echo "[START] 1/4 启动运动中枢 sit.py (UDP:$SIT_UDP_PORT)..."
    cd "$SIT_DIR"
    SIT_PID=$(launch_bg "$LOG_DIR/sit.log" "$SIT_PYTHON" "$SIT_PY")
    echo "sit:$SIT_PID" >> "$PID_FILE"
    cd - > /dev/null

    # 等 sit.py 监听端口
    for i in $(seq 1 20); do
        if ss -ulnp 2>/dev/null | grep -q ":$SIT_UDP_PORT"; then
            echo "[START] sit.py 就绪 (PID=$SIT_PID)"
            break
        fi
        if ! kill -0 "$SIT_PID" 2>/dev/null; then
            echo "[ERROR] sit.py 启动失败, 看 $LOG_DIR/sit.log"
            tail -20 "$LOG_DIR/sit.log"
            exit 1
        fi
        sleep 0.5
    done

    # ---------- 2. ROS2 环境 ----------
    source_tros
    source_ws

    # ---------- 3. IMU ----------
    echo "[START] 2/4 启动 IMU 节点..."
    IMU_PID=$(launch_bg "$LOG_DIR/imu.log" ros2 run puppy_brain imu_node_ros2 \
        --ros-args -p topic_name:=/ros_robot_controller/imu_raw -p publish_hz:=50.0)
    echo "imu:$IMU_PID" >> "$PID_FILE"
    sleep 1

    # ---------- 4. WebSocket 桥 (供上位机) ----------
    echo "[START] 3/4 启动 WebSocket 桥 (9090)..."
    WS_PID=$(launch_bg "$LOG_DIR/ws.log" ros2 run puppy_brain ws_bridge_node \
        --ros-args --log-level info)
    echo "ws:$WS_PID" >> "$PID_FILE"
    sleep 1

    # ---------- 5. ROS/UDP 桥 (ROS topic → 仲裁器 5005) ----------
    echo "[START] 4/4 启动 ROS/UDP 桥 (→ 127.0.0.1:5005)..."
    ROSUDP_PID=$(launch_bg "$LOG_DIR/ros_udp.log" ros2 run puppy_brain ros_udp_bridge \
        --ros-args \
        -p udp_ip:=127.0.0.1 -p udp_port:=5005 \
        -p imu_udp_ip:=127.0.0.1 -p imu_udp_port:=5006)
    echo "ros_udp:$ROSUDP_PID" >> "$PID_FILE"
    sleep 1

    echo ""
    echo "============================================================"
    echo " 精简机器人系统已启动 (集成模式)"
    echo "------------------------------------------------------------"
    echo "  sit.py          PID=$SIT_PID  端口=$SIT_UDP_PORT"
    echo "  IMU             /ros_robot_controller/imu_raw"
    echo "  WebSocket       9090"
    echo "  ROS/UDP桥       127.0.0.1:5005 → 仲裁器"
    echo "------------------------------------------------------------"
    echo "  查看状态: $0 status"
    echo "  停止全部: $0 stop"
    echo "============================================================"
}

stop_all() {
    echo "[STOP] 停止精简机器人系统..."

    # 按 PID 文件优雅 kill
    if [ -f "$PID_FILE" ]; then
        while read -r line; do
            name="${line%%:*}"
            pid="${line##*:}"
            [ -n "$pid" ] && kill "$pid" 2>/dev/null
        done < "$PID_FILE"
        sleep 2
        while read -r line; do
            pid="${line##*:}"
            kill -9 "$pid" 2>/dev/null
        done < "$PID_FILE"
        : > "$PID_FILE"
    fi

    # 兜底清理
    pkill -f 'anaconda3/envs/puppy/bin/python.*sit.py' 2>/dev/null
    pkill -f '/app/pydev_demo/puppypi_control/sit.py' 2>/dev/null
    pkill -f 'imu_node_ros2' 2>/dev/null
    pkill -f 'ws_bridge_node' 2>/dev/null
    pkill -f 'ros_udp_bridge' 2>/dev/null

    echo "[STOP] 完成"
}

status_all() {
    echo "============================================================"
    echo "[STATUS] 精简机器人系统  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"

    SIT_PID=$(pgrep -f '/app/pydev_demo/puppypi_control/sit.py' | head -1)
    if [ -n "$SIT_PID" ]; then
        echo "✅ 运动中枢 (sit.py)    运行中  PID=$SIT_PID"
    else
        echo "❌ 运动中枢 (sit.py)    未运行"
    fi

    if pgrep -f 'imu_node_ros2' > /dev/null 2>&1; then
        echo "✅ IMU 节点             运行中"
    else
        echo "❌ IMU 节点             未运行"
    fi

    if pgrep -f 'ws_bridge_node' > /dev/null 2>&1; then
        echo "✅ WebSocket (9090)     运行中"
    else
        echo "❌ WebSocket (9090)     未运行"
    fi

    if pgrep -f 'ros_udp_bridge' > /dev/null 2>&1; then
        echo "✅ ROS/UDP 桥           运行中"
    else
        echo "❌ ROS/UDP 桥           未运行"
    fi

    SIT_PORT="${SIT_UDP_PORT:-5006}"
    if ss -ulnp 2>/dev/null | grep -q ":$SIT_PORT"; then
        echo "✅ UDP $SIT_PORT (sit.py) 监听中"
    else
        echo "❌ UDP $SIT_PORT (sit.py) 未监听"
    fi

    echo "============================================================"
}

case "${1:-}" in
    start)
        start_all
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        sleep 2
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
