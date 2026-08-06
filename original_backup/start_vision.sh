#!/bin/bash
# start_vision.sh - 只启动 GS130W 双目视觉 (不起 AI/LLM/决策/运动控制)
#
# 用法:
#   ./start_vision.sh start    启动双目视觉 (mipi_cam + codec + stereonet + 3 mjpeg_bridge)
#   ./start_vision.sh status   查看状态
#   ./start_vision.sh logs     实时查看日志
#
# 注意: 本脚本只启动视觉, 不启动 ROS2 决策/LLM/运动控制
#       如需完整系统, 用 start_robot.sh start
# ============================================================================

set -u

# ============ 路径配置 ============
TROS_SETUP="/opt/tros/humble/setup.bash"
PROJECT_ROOT="/app/gs130w_stereo"
GDC_BIN="/root/multimedia_samples/vp_sensors/gdc_bin/sc132gs_1088X1280_gdc.bin"
CALIB_YAML="/opt/tros/humble/lib/mipi_cam/config/SC132gs_dual_calibration.yaml"
LAUNCH_DUAL="/opt/tros/humble/share/mipi_cam/launch/mipi_cam_dual_channel_websocket.launch.py"
LAUNCH_AI="$PROJECT_ROOT/launch/gs130w_ai_overlay_v2.launch.py"
MJPEG_BRIDGE="$PROJECT_ROOT/scripts/mjpeg_bridge.py"
CAMERA_INFO_PUB="$PROJECT_ROOT/launch/camera_info_publisher.py"
VIEW_HTML="$PROJECT_ROOT/snapshots/view.html"

# mjpeg_bridge 端口
PORT_RIGHT=8071
PORT_LEFT=8072
PORT_DEPTH=8073
PORT_HTTP=8090

LOG_DIR="/tmp/gs130w_vision"
PID_FILE="$LOG_DIR/pids"

# ============ source TROS ============
source_tros() {
    set +u
    # shellcheck disable=SC1090
    source "$TROS_SETUP"
    set -u
}

# ============ 检查环境 ============
check_env() {
    [ -f "$TROS_SETUP" ] || { echo "[ERR] TROS 缺失: $TROS_SETUP"; exit 1; }
    [ -f "$GDC_BIN" ] || { echo "[ERR] GDC bin 缺失: $GDC_BIN"; exit 1; }
    [ -f "$CALIB_YAML" ] || { echo "[ERR] 标定 yaml 缺失: $CALIB_YAML"; exit 1; }
    [ -f "$MJPEG_BRIDGE" ] || { echo "[ERR] mjpeg_bridge.py 缺失: $MJPEG_BRIDGE"; exit 1; }
    [ -f "$CAMERA_INFO_PUB" ] || { echo "[ERR] camera_info_publisher.py 缺失: $CAMERA_INFO_PUB"; exit 1; }
}

# ============ 启动 ============
start_all() {
    check_env
    mkdir -p "$LOG_DIR"
    : > "$PID_FILE"

    source_tros

    echo "[START] 启动 GS130W 双目视觉..."

    # ---------- 1. mipi_cam 双目 ----------
    echo "[START] 1/5 mipi_cam 双目 (官方 launch)..."
    ros2 launch mipi_cam mipi_cam_dual_channel_websocket.launch.py \
        mipi_image_width:=1280 \
        mipi_image_height:=1088 \
        mipi_image_framerate:=10.0 \
        mipi_gdc_bin_file:="$GDC_BIN" \
        mipi_camera_calibration_file_path:="$CALIB_YAML" \
        device_mode:=dual \
        dual_combine:=2 \
        mipi_channel:=2 \
        mipi_channel2:=0 \
        > "$LOG_DIR/mipi_cam.log" 2>&1 &
    echo $! >> "$PID_FILE"

    # 等双目出图
    echo "[START] 等待双目出图 (最多 20 秒)..."
    for i in $(seq 1 20); do
        if ros2 topic list 2>/dev/null | grep -q "/image_combine"; then
            echo "[START] 双目 topic 出现"
            break
        fi
        sleep 1
    done

    # ---------- 2. camera_info_publisher ----------
    echo "[START] 2/5 camera_info_publisher..."
    python3 "$CAMERA_INFO_PUB" > "$LOG_DIR/camera_info.log" 2>&1 &
    echo $! >> "$PID_FILE"

    sleep 1

    # ---------- 3. stereonet ----------
    echo "[START] 3/5 stereonet 深度估计..."
    ros2 launch hobot_stereonet stereonet_model.launch.py \
        stereo_camera_info_topic:=/image_combine_raw \
        stereo_left_camera_info_topic:=/left_camera_info \
        stereo_right_camera_info_topic:=/right_camera_info \
        save_disparity_flag:=False \
        save_depth_flag:=False \
        save_lgn_flag:=False \
        save_cloud_flag:=False \
        save_left_flag:=False \
        save_right_flag:=False \
        save_disparity_norm_flag:=False \
        save_depth_norm_flag:=False \
        > "$LOG_DIR/stereonet.log" 2>&1 &
    echo $! >> "$PID_FILE"

    # ---------- 4. stereonet_visual codec (bgr8 → jpeg) ----------
    echo "[START] 4/5 stereonet_visual codec..."
    ros2 launch hobot_codec hobot_codec.launch.py \
        codec_in_mode:=ros_bgr8 \
        codec_in_topic:=/StereoNetNode/stereonet_visual \
        codec_out_mode:=ros_mjpeg \
        codec_out_topic:=/StereoNetNode/stereonet_visual_jpeg \
        > "$LOG_DIR/stereonet_codec.log" 2>&1 &
    echo $! >> "$PID_FILE"

    sleep 2

    # ---------- 5. 3 路 mjpeg_bridge ----------
    echo "[START] 5a/5 mjpeg_bridge 左眼 :$PORT_LEFT..."
    python3 "$MJPEG_BRIDGE" \
        --port $PORT_LEFT --topic /image_combine_jpeg --region top \
        > "$LOG_DIR/mjpeg_left.log" 2>&1 &
    echo $! >> "$PID_FILE"

    echo "[START] 5b/5 mjpeg_bridge 右眼 :$PORT_RIGHT..."
    python3 "$MJPEG_BRIDGE" \
        --port $PORT_RIGHT --topic /image_combine_jpeg --region bottom \
        > "$LOG_DIR/mjpeg_right.log" 2>&1 &
    echo $! >> "$PID_FILE"

    echo "[START] 5c/5 mjpeg_bridge 深度图 :$PORT_DEPTH..."
    python3 "$MJPEG_BRIDGE" \
        --port $PORT_DEPTH --topic /StereoNetNode/stereonet_visual_jpeg --region full \
        > "$LOG_DIR/mjpeg_depth.log" 2>&1 &
    echo $! >> "$PID_FILE"

    # ---------- HTTP server (托管 view.html) ----------
    if [ -f "$VIEW_HTML" ]; then
        echo "[START] 5d/5 HTTP server :$PORT_HTTP (view.html)..."
        cd "$(dirname "$VIEW_HTML")"
        python3 -m http.server $PORT_HTTP > "$LOG_DIR/http.log" 2>&1 &
        echo $! >> "$PID_FILE"
        cd - > /dev/null
    fi

    # ---------- 完成 ----------
    echo ""
    echo "============================================================"
    echo "[START] 双目视觉系统已启动"
    echo "------------------------------------------------------------"
    echo "  左眼 MJPEG:   http://<板端IP>:$PORT_LEFT"
    echo "  右眼 MJPEG:   http://<板端IP>:$PORT_RIGHT"
    echo "  深度图 MJPEG: http://<板端IP>:$PORT_DEPTH"
    echo "  聚合页:       http://<板端IP>:$PORT_HTTP/view.html"
    echo "------------------------------------------------------------"
    echo "  日志目录: $LOG_DIR/"
    echo "  查看状态: $0 status"
    echo "  查看日志: $0 logs"
    echo "  停止:     stop_vision.sh"
    echo "============================================================"
    echo ""
    echo "本机 IP:"
    hostname -I 2>/dev/null
}

# ============ 状态 ============
status_all() {
    echo "============================================================"
    echo "[STATUS] 双目视觉状态  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"

    source_tros 2>/dev/null

    # mipi_cam
    if pgrep -f 'mipi_cam_dual_channel' > /dev/null 2>&1; then
        echo "✅ mipi_cam 双目         运行中"
    else
        echo "❌ mipi_cam 双目         未运行"
    fi

    # camera_info
    if pgrep -f 'camera_info_publisher' > /dev/null 2>&1; then
        echo "✅ camera_info_publisher 运行中"
    else
        echo "❌ camera_info_publisher 未运行"
    fi

    # stereonet
    if pgrep -f 'stereonet' > /dev/null 2>&1; then
        echo "✅ stereonet 深度        运行中"
    else
        echo "❌ stereonet 深度        未运行"
    fi

    # 端口
    echo "------------------------------------------------------------"
    for port in $PORT_LEFT $PORT_RIGHT $PORT_DEPTH $PORT_HTTP; do
        if ss -tlnp 2>/dev/null | grep -q ":$port"; then
            echo "✅ 端口 $port  监听中"
        else
            echo "❌ 端口 $port  未监听"
        fi
    done

    # topic 频率
    echo "------------------------------------------------------------"
    echo "topic 频率 (采样 3 秒):"
    for t in /image_combine_raw /image_combine_jpeg /StereoNetNode/stereonet_visual_jpeg; do
        HZ=$(timeout 3 ros2 topic hz "$t" 2>/dev/null | grep average | awk '{print $3}')
        if [ -n "$HZ" ]; then
            echo "  $t  ${HZ} Hz"
        else
            echo "  $t  (无数据)"
        fi
    done

    echo "============================================================"
}

# ============ 日志 ============
logs_all() {
    echo "[LOGS] 实时显示视觉日志 (Ctrl+C 退出)"
    echo "  日志目录: $LOG_DIR/"
    echo "------------------------------------------------------------"
    tail -f "$LOG_DIR"/*.log 2>/dev/null
}

# ============ 主入口 ============
case "${1:-}" in
    start)
        start_all
        ;;
    status)
        status_all
        ;;
    logs)
        logs_all
        ;;
    *)
        echo "用法: $0 {start|status|logs}"
        echo ""
        echo "  start   启动双目视觉 (不起 AI/LLM/决策)"
        echo "  status  查看状态 + topic 频率"
        echo "  logs    实时查看日志"
        echo ""
        echo "停止视觉: 请用 stop_vision.sh"
        exit 1
        ;;
esac
