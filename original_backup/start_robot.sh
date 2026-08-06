#!/bin/bash
# start_robot.sh - 机器狗全系统一键启动 (板端)
#
# 用法:
#   ./start_robot.sh start    # 启动全部 (运动中枢 + ROS2 系统 + WS 桥)
#   ./start_robot.sh stop     # 停止全部
#   ./start_robot.sh restart  # 重启
#   ./start_robot.sh status   # 查看状态
#   ./start_robot.sh logs     # 实时查看所有日志
#
# 启动顺序:
#   1. sit.py (运动中枢, UDP:5005) - 必须先起
#   2. ROS2 full_system_cloud.launch.py (双目+AI+LLM+决策+UDP桥)
#   3. ws_bridge_node 已在 launch 里, 不用单独起
#
# 前置:
#   - sit.py 已改过 (支持 forward/backward/follow_control)
#   - full_system_cloud.launch.py 已部署
#   - DEEPSEEK_API_KEY 环境变量已设置 (或在脚本里改)
# ============================================================================

set -u

# ============ 路径配置 (按你板端实际改) ============
TROS_SETUP="/opt/tros/humble/setup.bash"
WS_ROOT="/app/puppy_ws"
WS_SETUP="$WS_ROOT/install/setup.bash"
SIT_DIR="/app/pydev_demo/puppypi_control"
SIT_PY="$SIT_DIR/sit.py"
# HiwonderPuppy.so 是 Python 3.7 编译的, 用 anaconda 的 puppy 环境 (和手柄控制一致)
SIT_PYTHON="/root/anaconda3/envs/puppy/bin/python"
LAUNCH_FILE="$WS_ROOT/src/puppy_brain/launch/full_system_cloud.launch.py"
LAUNCH_MINIMAL="$WS_ROOT/src/puppy_brain/launch/minimal_llm.launch.py"

# ============ 日志目录 ============
LOG_DIR="/tmp/robot_system"
mkdir -p "$LOG_DIR"
PID_FILE="$LOG_DIR/pids.txt"

# ============ source TROS (兼容 set -u) ============
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

# ============ 检查环境 ============
check_env() {
    [ -f "$TROS_SETUP" ] || { echo "[ERROR] TROS 未安装: $TROS_SETUP"; exit 1; }
    [ -f "$SIT_PY" ] || { echo "[ERROR] sit.py 不存在: $SIT_PY"; exit 1; }
    [ -f "$LAUNCH_FILE" ] || { echo "[ERROR] launch 不存在: $LAUNCH_FILE"; exit 1; }
}

# ============ 启动 ============
start_all() {
    check_env
    echo "[START] 清理旧进程..."
    stop_all 2>/dev/null
    sleep 1
    : > "$PID_FILE"

    # ---------- 1. sit.py (运动中枢) ----------
    echo "[START] 1/2 启动运动中枢 sit.py (UDP:5005)..."
    if [ ! -x "$SIT_PYTHON" ]; then
        echo "[ERROR] puppy_env Python 不存在: $SIT_PYTHON"
        echo "        HiwonderPuppy.so 需要 Python 3.7, 必须用 puppy_env"
        exit 1
    fi
    cd "$SIT_DIR"
    "$SIT_PYTHON" "$SIT_PY" > "$LOG_DIR/sit.log" 2>&1 &
    SIT_PID=$!
    echo "sit:$SIT_PID" >> "$PID_FILE"
    cd - > /dev/null

    # 等 sit.py 起来 (看到 "监听端口 5005")
    for i in $(seq 1 10); do
        if grep -q "5005\|启动成功\|监听" "$LOG_DIR/sit.log" 2>/dev/null; then
            echo "[START] sit.py 就绪 (PID=$SIT_PID)"
            break
        fi
        sleep 0.5
    done
    if ! kill -0 "$SIT_PID" 2>/dev/null; then
        echo "[ERROR] sit.py 启动失败, 看 $LOG_DIR/sit.log"
        tail -20 "$LOG_DIR/sit.log"
        exit 1
    fi

    # ---------- 2. ROS2 full_system_cloud (决策 + LLM + 适配, 不含双目/AI) ----------
    echo "[START] 2/2 启动 ROS2 系统 (full_system_cloud.launch.py)..."
    echo "[START] 注: 双目视觉 + AI 推理由 start_v2.sh 单独管理"
    echo "[START]     如需视觉, 先跑: /app/gs130w_stereo/scripts/start_v2.sh start"
    source_tros
    source_ws

    # API key (从环境变量读, 没有就提示)
    if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
        echo "[WARN] DEEPSEEK_API_KEY 未设置, LLM 会用不了"
        echo "       解决: export DEEPSEEK_API_KEY='sk-xxx' 后再运行本脚本"
    fi

    ros2 launch "$LAUNCH_FILE" > "$LOG_DIR/ros2.log" 2>&1 &
    ROS_PID=$!
    echo "ros2:$ROS_PID" >> "$PID_FILE"

    # 等 ros2 起来 (等关键节点出现)
    echo "[START] 等待 ROS2 节点就绪 (最多 30 秒)..."
    for i in $(seq 1 30); do
        if ros2 node list 2>/dev/null | grep -q "ws_bridge_node"; then
            echo "[START] ws_bridge_node 就绪"
            break
        fi
        sleep 1
    done

    # ---------- 完成 ----------
    echo ""
    echo "============================================================"
    echo "[START] 全系统已启动"
    echo "------------------------------------------------------------"
    echo "  运动中枢 (sit.py)   PID=$SIT_PID  日志: $LOG_DIR/sit.log"
    echo "  ROS2 系统           PID=$ROS_PID  日志: $LOG_DIR/ros2.log"
    echo "  WebSocket 端口      9090"
    echo "------------------------------------------------------------"
    echo "  PC 上位机访问:"
    echo "    1. 双击 start_pc.bat"
    echo "    2. 浏览器 http://localhost:8888/"
    echo "    3. 顶部填本机 IP, 点连接"
    echo "------------------------------------------------------------"
    echo "  查看状态:   $0 status"
    echo "  查看日志:   $0 logs"
    echo "  停止全部:   $0 stop"
    echo "============================================================"
    echo ""
    echo "本机 IP:"
    hostname -I 2>/dev/null || ip addr show 2>/dev/null | grep "inet " | grep -v 127.0.0.1
}

# ============ 停止 ============
# 注意: 只清理本脚本启动的进程, 不用 pkill -f mipi_cam 这种粗粒度清理
# (避免误杀 gs130w_stereo 的双目视觉或其他独立服务)
stop_all() {
    echo "[STOP] 停止本脚本启动的进程..."

    # 1. 停 sit.py (按 anaconda puppy 环境路径精确匹配)
    pkill -f 'anaconda3/envs/puppy/bin/python.*sit.py' 2>/dev/null
    # 兜底: 如果有其他 sit.py 在跑, 也清掉 (但不用 -f 'sit.py' 太宽泛)
    pkill -f '/app/pydev_demo/puppypi_control/sit.py' 2>/dev/null

    # 2. 停 ROS2 launch (只停 full_system_cloud 和 minimal_llm, 不影响其他 launch)
    pkill -f 'full_system_cloud.launch.py' 2>/dev/null
    pkill -f 'minimal_llm.launch.py' 2>/dev/null

    # 等 launch 退出 (它会级联停所有子节点: mipi_cam/codec/AI/decision/...)
    sleep 2

    # 3. 兜底: 清理 launch 没退干净的子节点 (只针对 full_system_cloud 的 决策/LLM/适配)
    # 注意: 不清视觉节点 (mipi_cam/codec/stereonet/mjpeg_bridge) 和 AI 推理节点
    #       (mono2d/hand_lmk/hand_gesture), 那些由 start_v2.sh 管
    if ! pgrep -f 'full_system_cloud.launch.py' > /dev/null 2>&1; then
        pkill -f 'puppy_brain.*decision_node' 2>/dev/null
        pkill -f 'puppy_brain.*ros_udp_bridge' 2>/dev/null
        pkill -f 'puppy_brain.*ws_bridge_node' 2>/dev/null
        pkill -f 'puppy_brain.*cloud_llm_node' 2>/dev/null
        pkill -f 'puppy_brain.*chat_llm_bridge' 2>/dev/null
        pkill -f 'puppy_brain.*intent_router' 2>/dev/null
        pkill -f 'puppy_brain.*tts_play' 2>/dev/null
        pkill -f 'puppy_brain.*perception_node' 2>/dev/null
        pkill -f 'puppy_brain.*usb_asr' 2>/dev/null
        pkill -f 'puppy_brain.*gesture_adapter' 2>/dev/null
    fi

    # 4. 清共享内存 (只在视觉也没跑时才清, 避免影响正在跑的视觉服务)
    if ! pgrep -f 'full_system_cloud.launch.py' > /dev/null 2>&1; then
        if ! pgrep -f 'mipi_cam_dual_channel' > /dev/null 2>&1; then
            rm -f /dev/shm/fastrtps_* 2>/dev/null
        else
            echo "[STOP] 视觉仍在运行, 跳过清共享内存 (避免影响视觉)"
        fi
    fi

    : > "$PID_FILE" 2>/dev/null
    echo "[STOP] 完成"
}

# ============ 状态 ============
status_all() {
    echo "============================================================"
    echo "[STATUS] 系统状态  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"

    # sit.py
    SIT_PID=$(pgrep -f 'sit.py' | head -1)
    if [ -n "$SIT_PID" ]; then
        echo "✅ 运动中枢 (sit.py)    运行中  PID=$SIT_PID"
    else
        echo "❌ 运动中枢 (sit.py)    未运行"
    fi

    # ROS2 launch
    ROS_PID=$(pgrep -f 'ros2 launch' | head -1)
    if [ -n "$ROS_PID" ]; then
        echo "✅ ROS2 launch          运行中  PID=$ROS_PID"
    else
        echo "❌ ROS2 launch          未运行"
    fi

    # WS 桥
    if ss -tlnp 2>/dev/null | grep -q ":9090"; then
        echo "✅ WebSocket (9090)     监听中"
    else
        echo "❌ WebSocket (9090)     未监听"
    fi

    # UDP 5005 (sit.py)
    if ss -ulnp 2>/dev/null | grep -q ":5005"; then
        echo "✅ UDP 5005 (运动中枢)  监听中"
    else
        echo "❌ UDP 5005 (运动中枢)  未监听"
    fi

    # 关键节点
    echo "------------------------------------------------------------"
    if [ -n "$ROS_PID" ]; then
        source_tros 2>/dev/null
        source_ws 2>/dev/null
        echo "ROS2 节点:"
        ros2 node list 2>/dev/null | sed 's/^/  /' | head -20
        echo "------------------------------------------------------------"
        echo "关键 topic 频率 (采样 3 秒):"
        for t in /puppy_action /voice/result_json /chat/input_text; do
            HZ=$(timeout 3 ros2 topic hz "$t" 2>/dev/null | grep average | awk '{print $3}')
            if [ -n "$HZ" ]; then
                echo "  $t  ${HZ} Hz"
            else
                echo "  $t  (无数据或无订阅)"
            fi
        done
    fi

    echo "============================================================"
    echo "日志目录: $LOG_DIR/"
    echo "============================================================"
}

# ============ 日志 ============
logs_all() {
    echo "[LOGS] 实时显示所有日志 (Ctrl+C 退出)"
    echo "  sit.py:  $LOG_DIR/sit.log"
    echo "  ros2:    $LOG_DIR/ros2.log"
    echo "------------------------------------------------------------"
    tail -f "$LOG_DIR/sit.log" "$LOG_DIR/ros2.log" 2>/dev/null
}

# ============ 主入口 ============
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
    logs)
        logs_all
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "  start    启动全部 (运动中枢 + ROS2 + WS 桥)"
        echo "  stop     停止全部"
        echo "  restart  重启"
        echo "  status   查看状态 + 节点列表 + topic 频率"
        echo "  logs     实时查看 sit.py 和 ros2 日志"
        echo ""
        echo "前置: export DEEPSEEK_API_KEY='sk-xxx' (LLM 用)"
        exit 1
        ;;
esac
