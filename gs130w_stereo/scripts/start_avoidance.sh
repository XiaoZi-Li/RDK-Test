#!/bin/bash
# 双目深度避障 v2 - 独立启动脚本 (不修改 start_v2.sh / start_robot.sh)
#
# 功能: 订阅 stereonet 深度数据 + IMU, 分析前方障碍物, 通过 UDP 向 sit.py 发送避障指令
# v2 改进: follow_control 流畅模式 + IMU航向修正 + 深度图180°翻转修复
#
# 前置 (必须先启动):
#   1. /app/gs130w_stereo/scripts/start_v2.sh start   (视觉 + stereonet 深度)
#   2. /app/start_robot.sh start                        (sit.py + IMU, UDP:5005)
#
# 用法:
#   ./start_avoidance.sh start    启动避障
#   ./start_avoidance.sh stop     停止避障 (机器人可能仍在运动, 需手动停车)
#   ./start_avoidance.sh restart  重启
#   ./start_avoidance.sh status   查看状态 + 前置检查
#   ./start_avoidance.sh logs     实时查看日志
#
# 注意: 避障节点会持续发送运动指令, 不要与 LLM 决策系统同时运行!
#       如需切回 LLM 控制, 先 ./start_avoidance.sh stop
set -u

PROJECT_ROOT="/app/gs130w_stereo"
TROS_SETUP="/opt/tros/humble/setup.bash"
NODE_SCRIPT="$PROJECT_ROOT/scripts/stereo_avoidance_node.py"
STATUS_SCRIPT="$PROJECT_ROOT/scripts/status_bridge.py"
LOG_DIR="/tmp/gs130w_v2"
PID_FILE="$LOG_DIR/avoidance.pid"
STATUS_PID_FILE="$LOG_DIR/status_bridge.pid"
STATUS_PORT=8074

# ============ 环境检查 ============
check_env() {
    [ -f "$TROS_SETUP" ] || { echo "[ERR] TROS 缺失: $TROS_SETUP"; exit 1; }
    [ -f "$NODE_SCRIPT" ] || { echo "[ERR] 避障节点缺失: $NODE_SCRIPT"; exit 1; }
    [ -f "$STATUS_SCRIPT" ] || { echo "[ERR] 状态桥接器缺失: $STATUS_SCRIPT"; exit 1; }
}

# 检查前置服务
# $1: motion_enabled (true/false), false 时 sit.py 未启动也允许运行
check_prereqs() {
    local motion_enabled="${1:-true}"
    local ok=0

    # 1. sit.py (UDP 5005)
    if ss -ulnp 2>/dev/null | grep -q ":5005"; then
        echo "  [OK]   sit.py (UDP 5005) 监听中"
    else
        if [ "$motion_enabled" = "false" ]; then
            echo "  [WARN] sit.py (UDP 5005) 未监听 (调试模式, 不发送运动指令, 跳过)"
        else
            echo "  [FAIL] sit.py (UDP 5005) 未监听"
            echo "         先启动: /app/start_robot.sh start"
            ok=1
        fi
    fi

    # 2. stereonet 深度节点
    set +u
    source "$TROS_SETUP" 2>/dev/null
    set -u
    if ros2 topic list 2>/dev/null | grep -q "stereonet"; then
        echo "  [OK]   stereonet 深度节点运行中"
        for t in /StereoNetNode/stereonet_disp /StereoNetNode/stereonet_visual; do
            if ros2 topic list 2>/dev/null | grep -q "^${t}$"; then
                echo "         -> $t"
            fi
        done
    else
        echo "  [FAIL] stereonet 深度节点未运行"
        echo "         先启动: /app/gs130w_stereo/scripts/start_v2.sh start"
        ok=1
    fi

    # 3. IMU (航向修正用, 没有也能跑但无修正)
    if ros2 topic list 2>/dev/null | grep -q "^/ros_robot_controller/imu_raw$"; then
        echo "  [OK]   IMU (/ros_robot_controller/imu_raw) 运行中"
    else
        echo "  [WARN] IMU topic 不存在 (航向修正将不生效)"
        echo "         确保 start_robot.sh 已启动 (含 imu_node_ros2)"
    fi

    return $ok
}

# ============ 启动 ============
start_node() {
    check_env
    mkdir -p "$LOG_DIR"

    # 检查是否已在运行
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "[WARN] 避障节点已在运行 (PID=$(cat "$PID_FILE"))"
        echo "       先停止: $0 stop"
        exit 1
    fi

    # 判断是否为纯视觉调试模式
    local motion_enabled="true"
    for arg in "$@"; do
        case "$arg" in
            *enable_motion*false*) motion_enabled="false" ;;
        esac
    done

    echo "[START] 前置检查..."
    if ! check_prereqs "$motion_enabled"; then
        echo "[ERR] 前置服务不满足, 无法启动避障"
        exit 1
    fi

    echo ""
    echo "[START] 启动双目深度避障节点..."
    set +u
    source "$TROS_SETUP"
    set -u

    python3 "$NODE_SCRIPT" "$@" > "$LOG_DIR/avoidance.log" 2>&1 &
    PID=$!
    echo "$PID" > "$PID_FILE"

    echo "[START] 启动状态桥接器 :$STATUS_PORT ..."
    python3 "$STATUS_SCRIPT" --port $STATUS_PORT \
        > "$LOG_DIR/status_bridge.log" 2>&1 &
    STATUS_PID=$!
    echo "$STATUS_PID" > "$STATUS_PID_FILE"

    # 等待启动
    sleep 2
    if kill -0 "$PID" 2>/dev/null; then
        BOARD_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
        [ -z "$BOARD_IP" ] && BOARD_IP="<板端IP>"
        echo ""
        echo "================================================"
        echo " 双目深度避障 v2 已启动"
        echo "================================================"
        echo " PID:     $PID"
        echo " 日志:    $LOG_DIR/avoidance.log"
        echo " 状态:    $0 status"
        echo " 停止:    $0 stop"
        echo "------------------------------------------------"
        echo " 模式: follow_control (流畅连续控制)"
        echo " IMU航向修正: 已启用 (解决前进左倾)"
        echo " 深度图180°翻转: 已修复"
        echo "------------------------------------------------"
        echo " 浏览器监控: http://$BOARD_IP:8090/view_status.html"
        echo " 状态接口:   http://$BOARD_IP:$STATUS_PORT/status"
        echo "------------------------------------------------"
        echo " 监控 topic: /stereo_avoidance/status"
        echo "   ros2 topic echo /stereo_avoidance/status"
        echo "------------------------------------------------"
        echo " 调参 (运行时):"
        echo " 关闭IMU修正:  -p use_imu_correction:=false"
        echo "   调修正增益:   -p yaw_gain:=0.8"
        echo "   调触发距离:   -p danger_disp:=35 -p clear_disp:=18"
        echo "   切离散模式:   -p use_follow_control:=false"
        echo "   纯视觉调试:   -p enable_motion:=false  (不输出UDP运动指令)"
        echo "================================================"
    else
        echo "[ERR] 启动失败, 看日志:"
        tail -30 "$LOG_DIR/avoidance.log"
        rm -f "$PID_FILE"
        # 顺手清理已启动的状态桥接器
        if [ -f "$STATUS_PID_FILE" ]; then
            kill "$(cat "$STATUS_PID_FILE")" 2>/dev/null
            rm -f "$STATUS_PID_FILE"
        fi
        pkill -f 'status_bridge.py' 2>/dev/null
        exit 1
    fi
}

# ============ 停止 ============
stop_node() {
    echo "[STOP] 停止避障节点..."
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        # 优雅退出 (触发 destroy_node 发送 stop)
        kill "$PID" 2>/dev/null
        sleep 1
        # 兜底强杀
        kill -9 "$PID" 2>/dev/null
        rm -f "$PID_FILE"
    fi
    pkill -f 'stereo_avoidance_node.py' 2>/dev/null

    echo "[STOP] 停止状态桥接器..."
    if [ -f "$STATUS_PID_FILE" ]; then
        STATUS_PID=$(cat "$STATUS_PID_FILE")
        kill "$STATUS_PID" 2>/dev/null
        sleep 1
        kill -9 "$STATUS_PID" 2>/dev/null
        rm -f "$STATUS_PID_FILE"
    fi
    pkill -f 'status_bridge.py' 2>/dev/null
    # 兜底清端口
    fuser -k ${STATUS_PORT}/tcp 2>/dev/null || true

    echo "[STOP] 避障节点已停止"
    echo "[WARN] 机器人可能仍在运动, 请手动发 stop 指令停车:"
    echo "       echo '{\"action\":\"stop\"}' | nc -u -w1 127.0.0.1 5005"
}

# ============ 状态 ============
status_node() {
    echo "============================================================"
    echo "[STATUS] 双目深度避障  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"

    # 避障节点
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "✅ 避障节点            运行中  PID=$(cat "$PID_FILE")"
    else
        echo "❌ 避障节点            未运行"
    fi

    # 状态桥接器
    if [ -f "$STATUS_PID_FILE" ] && kill -0 "$(cat "$STATUS_PID_FILE")" 2>/dev/null; then
        echo "✅ 状态桥接器          运行中  PID=$(cat "$STATUS_PID_FILE") 端口:$STATUS_PORT"
    else
        echo "❌ 状态桥接器          未运行"
    fi

    echo "------------------------------------------------------------"
    echo "前置检查:"
    check_prereqs || true

    echo "------------------------------------------------------------"
    echo "实时状态 (如节点在运行):"
    set +u
    source "$TROS_SETUP" 2>/dev/null
    set -u
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        timeout 2 ros2 topic echo /stereo_avoidance/status --once 2>/dev/null | head -5 || echo "  (等待数据...)"
    fi

    if [ -f "$STATUS_PID_FILE" ] && kill -0 "$(cat "$STATUS_PID_FILE")" 2>/dev/null; then
        echo "HTTP 状态接口:"
        curl -s -m 2 "http://localhost:$STATUS_PORT/status" 2>/dev/null | head -c 200 || echo "  (接口无响应)"
        echo ""
    fi
    echo "============================================================"
}

# ============ 日志 ============
show_logs() {
    local f="$LOG_DIR/avoidance.log"
    if [ ! -f "$f" ]; then
        echo "[ERR] 日志不存在: $f"
        echo "      可能还没启动过, 先: $0 start"
        return
    fi
    echo "=== tail -f $f === (Ctrl+C 退出)"
    tail -f "$f"
}

# ============ 主入口 ============
case "${1:-}" in
    start)   shift; start_node "$@" ;;
    stop)    stop_node ;;
    restart) shift; stop_node; sleep 1; start_node "$@" ;;
    status)  status_node ;;
    logs)    show_logs ;;
    *)
        echo "用法: $0 {start|stop|restart|status|logs} [ros-args...]"
        echo ""
        echo "  start    启动避障 (前置: start_v2.sh + start_robot.sh)"
        echo "  stop     停止避障"
        echo "  restart  重启"
        echo "  status   查看状态 + 前置检查"
        echo "  logs     实时查看日志"
        echo ""
        echo " 传参示例:"
        echo "    $0 start --ros-args -p enable_motion:=false"
        echo "    $0 start --ros-args -p danger_disp:=35 -p clear_disp:=18"
        exit 1
        ;;
esac
