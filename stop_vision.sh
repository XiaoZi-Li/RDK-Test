#!/bin/bash
# stop_vision.sh - 只停止 GS130W 双目视觉进程
#
# 用法:
#   ./stop_vision.sh           停止视觉进程
#   ./stop_vision.sh status    停止前先看状态
#
# 注意: 本脚本只停视觉, 不影响 ROS2 决策/LLM/运动控制
#       如需停完整系统, 用 start_robot.sh stop
# ============================================================================

set -u

# ============ 路径配置 ============
PROJECT_ROOT="/app/gs130w_stereo"
PORT_RIGHT=8071
PORT_LEFT=8072
PORT_DEPTH=8073
PORT_HTTP=8090

LOG_DIR="/tmp/gs130w_vision"
PID_FILE="$LOG_DIR/pids"

# ============ 停止 ============
stop_all() {
    echo "[STOP] 停止 GS130W 双目视觉进程..."

    # 1. 按 PID 文件 kill (最精确, 不误杀)
    if [ -f "$PID_FILE" ]; then
        echo "[STOP] 按 PID 文件清理..."
        while read -r pid; do
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                echo "  kill PID=$pid"
                kill "$pid" 2>/dev/null
            fi
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    fi

    # 2. 兜底: 按进程名精确匹配 (只用视觉特有的名字, 不碰通用名)
    echo "[STOP] 兜底清理残留..."

    # mjpeg_bridge (按端口精确匹配, 避免误杀其他 mjpeg_bridge)
    pkill -f "mjpeg_bridge.py.*--port $PORT_LEFT" 2>/dev/null
    pkill -f "mjpeg_bridge.py.*--port $PORT_RIGHT" 2>/dev/null
    pkill -f "mjpeg_bridge.py.*--port $PORT_DEPTH" 2>/dev/null

    # camera_info_publisher (gs130w_stereo 项目的)
    pkill -f 'camera_info_publisher.py' 2>/dev/null

    # stereonet (视觉深度估计)
    pkill -f 'stereonet_model.launch.py' 2>/dev/null
    pkill -f 'hobot_stereonet' 2>/dev/null

    # stereonet_visual codec (hobot_codec 专门给深度图编码的)
    # 注意: 不用 pkill -f 'hobot_codec' (会误杀 full_system_cloud 的 codec)
    # 只杀订阅 stereonet_visual 的那个 codec
    pkill -f 'hobot_codec.*stereonet_visual' 2>/dev/null

    # mipi_cam 双目 (按官方 launch 名精确匹配)
    pkill -f 'mipi_cam_dual_channel_websocket.launch.py' 2>/dev/null
    pkill -f 'mipi_cam_dual_channel.launch.py' 2>/dev/null

    # HTTP server (view.html)
    pkill -f "http.server $PORT_HTTP" 2>/dev/null

    sleep 2

    # 3. 清共享内存 (只在视觉已停时清)
    if ! pgrep -f 'mipi_cam_dual_channel' > /dev/null 2>&1; then
        echo "[STOP] 清理共享内存..."
        rm -f /dev/shm/fastrtps_* 2>/dev/null
    fi

    # 4. 确认结果
    echo ""
    echo "============================================================"
    echo "[STOP] 停止结果确认"
    echo "------------------------------------------------------------"
    REMAIN=0

    if pgrep -f 'mipi_cam_dual_channel' > /dev/null 2>&1; then
        echo "⚠️  mipi_cam 双目  仍在运行"
        REMAIN=1
    else
        echo "✅ mipi_cam 双目  已停止"
    fi

    if pgrep -f 'stereonet' > /dev/null 2>&1; then
        echo "⚠️  stereonet      仍在运行"
        REMAIN=1
    else
        echo "✅ stereonet      已停止"
    fi

    for port in $PORT_LEFT $PORT_RIGHT $PORT_DEPTH $PORT_HTTP; do
        if ss -tlnp 2>/dev/null | grep -q ":$port"; then
            echo "⚠️  端口 $port    仍被占用"
            REMAIN=1
        else
            echo "✅ 端口 $port    已释放"
        fi
    done

    if [ "$REMAIN" -eq 0 ]; then
        echo "------------------------------------------------------------"
        echo "[STOP] 全部视觉进程已停止"
    else
        echo "------------------------------------------------------------"
        echo "[STOP] 部分进程未停干净, 可再运行一次本脚本"
        echo "       或手动检查: ps aux | grep -E 'mipi_cam|stereonet|mjpeg'"
    fi
    echo "============================================================"
}

# ============ 状态 ============
status_all() {
    echo "============================================================"
    echo "[STATUS] 双目视觉状态  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"

    if pgrep -f 'mipi_cam_dual_channel' > /dev/null 2>&1; then
        echo "✅ mipi_cam 双目         运行中"
    else
        echo "❌ mipi_cam 双目         未运行"
    fi

    if pgrep -f 'camera_info_publisher' > /dev/null 2>&1; then
        echo "✅ camera_info_publisher 运行中"
    else
        echo "❌ camera_info_publisher 未运行"
    fi

    if pgrep -f 'stereonet' > /dev/null 2>&1; then
        echo "✅ stereonet 深度        运行中"
    else
        echo "❌ stereonet 深度        未运行"
    fi

    echo "------------------------------------------------------------"
    for port in $PORT_LEFT $PORT_RIGHT $PORT_DEPTH $PORT_HTTP; do
        if ss -tlnp 2>/dev/null | grep -q ":$port"; then
            echo "✅ 端口 $port  监听中"
        else
            echo "❌ 端口 $port  未监听"
        fi
    done
    echo "============================================================"
}

# ============ 主入口 ============
case "${1:-}" in
    ""|stop)
        stop_all
        ;;
    status)
        status_all
        ;;
    *)
        echo "用法: $0 [stop|status]"
        echo ""
        echo "  stop    停止双目视觉 (默认)"
        echo "  status  查看状态 (不停)"
        exit 1
        ;;
esac
