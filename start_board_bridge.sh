#!/bin/bash
# ============================================================
# 上位机桥接服务一键启动脚本 (板端 RDK X5)
# 用法:
#   ./start_board_bridge.sh build    # 首次: 安装依赖 + 编译
#   ./start_board_bridge.sh start    # 启动 ws_bridge_node
#   ./start_board_bridge.sh stop     # 停止
#   ./start_board_bridge.sh restart  # 重启
#   ./start_board_bridge.sh status   # 查看状态
#   ./start_board_bridge.sh logs     # 查看日志
#   ./start_board_bridge.sh mjpeg    # 可选: 启动 F37 单目 MJPEG 桥(:8074)
# ============================================================
set -u

TROS_SETUP="/opt/tros/humble/setup.bash"
WS_DIR="/app/puppy_ws"
PKG="puppy_brain"
NODE="ws_bridge_node"
LOG_DIR="/tmp/host_bridge"
LOG_FILE="$LOG_DIR/bridge.log"
PID_FILE="$LOG_DIR/bridge.pid"

# 可选: F37 单目摄像头 MJPEG 桥(用于上位机主视频 AI 叠加)
MJPEG_BRIDGE_SCRIPT="/app/gs130w_stereo/scripts/mjpeg_bridge.py"
MJPEG_F37_PORT=8074
MJPEG_F37_TOPIC="/image"
MJPEG_F37_PID="$LOG_DIR/mjpeg_f37.pid"
MJPEG_F37_LOG="$LOG_DIR/mjpeg_f37.log"

mkdir -p "$LOG_DIR"

# ============ source TROS 的安全封装（TROS setup.bash 用了未定义变量，set -u 会炸） ============
source_tros(){
    set +u
    source "$TROS_SETUP"
    set -u
}

# ============ build ============
do_build(){
    echo "[BUILD] 安装 websockets 依赖..."
    pip3 install websockets 2>&1 | tail -3

    echo "[BUILD] source TROS..."
    source_tros

    echo "[BUILD] colcon build puppy_brain..."
    cd "$WS_DIR"
    colcon build --packages-select $PKG --symlink-install 2>&1 | tail -10

    if [ -f "$WS_DIR/install/setup.bash" ]; then
        echo "[BUILD] OK, 已生成 install/setup.bash"
    else
        echo "[BUILD] FAIL, 检查编译日志"
        exit 1
    fi
}

# ============ start ============
do_start(){
    if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        echo "[START] $NODE 已在运行 (PID=$(cat $PID_FILE))"
        exit 0
    fi

    [ -f "$TROS_SETUP" ] || { echo "[ERR] TROS 缺失: $TROS_SETUP"; exit 1; }

    echo "[START] source TROS + workspace..."
    source_tros
    set +u
    source "$WS_DIR/install/setup.bash" 2>/dev/null || {
        echo "[ERR] workspace 未编译, 先执行: $0 build"
        exit 1
    }
    set -u

    echo "[START] 启动 $NODE (日志: $LOG_FILE)..."
    nohup ros2 run $PKG $NODE > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 2

    if kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        echo "[START] OK, PID=$(cat $PID_FILE), WS 端口 9090"
        echo "[START] 上位机访问: 在 PC 浏览器打开 index.html, 板端IP 填本机 IP"
        ip addr show | grep -oP 'inet \K192\.\d+\.\d+\.\d+' | head -3
        echo "[START] 提示: 如需主视频 AI 叠加, 执行: $0 mjpeg  (启动 F37 MJPEG 桥 :8074)"
    else
        echo "[START] FAIL, 日志:"
        tail -20 "$LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
}

# ============ mjpeg: 可选启动 F37 单目 MJPEG 桥 ============
do_mjpeg(){
    if [ -f "$MJPEG_F37_PID" ] && kill -0 "$(cat $MJPEG_F37_PID)" 2>/dev/null; then
        echo "[MJPEG] F37 MJPEG 桥已在运行 (PID=$(cat $MJPEG_F37_PID))"
        exit 0
    fi
    [ -f "$MJPEG_BRIDGE_SCRIPT" ] || { echo "[ERR] mjpeg_bridge.py 不存在: $MJPEG_BRIDGE_SCRIPT"; exit 1; }
    [ -f "$TROS_SETUP" ] || { echo "[ERR] TROS 缺失"; exit 1; }
    source_tros
    echo "[MJPEG] 启动 F37 MJPEG 桥 port=$MJPEG_F37_PORT topic=$MJPEG_F37_TOPIC"
    nohup python3 "$MJPEG_BRIDGE_SCRIPT" --port "$MJPEG_F37_PORT" --topic "$MJPEG_F37_TOPIC" > "$MJPEG_F37_LOG" 2>&1 &
    echo $! > "$MJPEG_F37_PID"
    sleep 2
    if kill -0 "$(cat $MJPEG_F37_PID)" 2>/dev/null; then
        echo "[MJPEG] OK, PID=$(cat $MJPEG_F37_PID), 访问 http://<板端IP>:$MJPEG_F37_PORT"
    else
        echo "[MJPEG] FAIL, 日志:"
        tail -20 "$MJPEG_F37_LOG"
        rm -f "$MJPEG_F37_PID"
        exit 1
    fi
}

# ============ stop ============
do_stop(){
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        echo "[STOP] kill bridge PID=$PID"
        kill "$PID" 2>/dev/null
        sleep 1
        kill -9 "$PID" 2>/dev/null
        rm -f "$PID_FILE"
    fi
    if [ -f "$MJPEG_F37_PID" ]; then
        PID=$(cat "$MJPEG_F37_PID")
        echo "[STOP] kill mjpeg_f37 PID=$PID"
        kill "$PID" 2>/dev/null
        sleep 1
        kill -9 "$PID" 2>/dev/null
        rm -f "$MJPEG_F37_PID"
    fi
    # 兜底
    pkill -f "ros2 run $PKG $NODE" 2>/dev/null
    pkill -f "$NODE" 2>/dev/null
    pkill -f "mjpeg_bridge.py.*$MJPEG_F37_TOPIC" 2>/dev/null
    echo "[STOP] done"
}

# ============ status ============
do_status(){
    if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        PID=$(cat "$PID_FILE")
        echo "[STATUS] $NODE 运行中, PID=$PID"
        echo "[STATUS] 端口监听:"
        ss -tlnp 2>/dev/null | grep 9090 || netstat -tlnp 2>/dev/null | grep 9090
        echo "[STATUS] 最近日志:"
        tail -5 "$LOG_FILE" 2>/dev/null
    else
        echo "[STATUS] $NODE 未运行"
    fi
    if [ -f "$MJPEG_F37_PID" ] && kill -0 "$(cat $MJPEG_F37_PID)" 2>/dev/null; then
        echo "[STATUS] F37 MJPEG 桥运行中, PID=$(cat $MJPEG_F37_PID), 端口 $MJPEG_F37_PORT"
    else
        echo "[STATUS] F37 MJPEG 桥未运行"
    fi
}

# ============ logs ============
do_logs(){
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo "[LOGS] 无日志文件 $LOG_FILE"
    fi
}

# ============ main ============
case "${1:-}" in
    build)   do_build ;;
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; sleep 1; do_start ;;
    status)  do_status ;;
    logs)    do_logs ;;
    mjpeg)   do_mjpeg ;;
    *)       echo "用法: $0 {build|start|stop|restart|status|logs|mjpeg}"; exit 1 ;;
esac
