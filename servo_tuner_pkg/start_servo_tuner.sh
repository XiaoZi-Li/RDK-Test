#!/bin/bash
# =========================================================
# 运动调节上位机 · 独立启动脚本
# =========================================================
# 说明:
#   本脚本在 servo_tuner_pkg 目录下独立启动运动调节所需节点，
#   不修改、不覆盖原 puppy_brain / pydev_demo 中的代码。
#
# 启动的进程:
#   1. sit.py            - 运动中枢(舵机精细控制版)
#   2. ros_udp_bridge.py - ROS /puppy_action -> UDP:5005 桥接
#   3. ws_bridge_node.py - WebSocket(9090) <-> ROS 桥接
#
# 用法:
#   cd servo_tuner_pkg
#   bash start_servo_tuner.sh
# =========================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 若当前 shell 没有 ROS2 环境，则自动 source
if [ -z "${ROS_DISTRO:-}" ]; then
    if [ -f "/opt/tros/humble/setup.bash" ]; then
        # 地平线定制版 ROS2 (TROS)
        source /opt/tros/humble/setup.bash
    elif [ -f "/opt/ros/humble/setup.bash" ]; then
        source /opt/ros/humble/setup.bash
    else
        echo "[错误] 找不到 ROS2 Humble setup.bash，请先 source ROS2 环境。"
        exit 1
    fi
fi

echo "=========================================="
echo "  PuppyPi · 运动调节上位机 (独立运行)"
echo "  工作目录: $SCRIPT_DIR"
echo "=========================================="

# 查找 puppy conda 环境 python（运动中枢的 .so 需要这个环境）
PUPPY_PYTHON="/root/anaconda3/envs/puppy/bin/python"
if [ -x "$PUPPY_PYTHON" ]; then
    SIT_PYTHON="$PUPPY_PYTHON"
    echo "[信息] 使用 puppy conda 环境启动 sit.py: $SIT_PYTHON"
else
    echo "[警告] 找不到 /root/anaconda3/envs/puppy/bin/python，回退到 python3"
    SIT_PYTHON="python3"
fi

# 先停止本脚本之前启动的残留进程
bash "$SCRIPT_DIR/stop_servo_tuner.sh" >/dev/null 2>&1 || true

# 再停止原系统运动中枢和桥接节点，避免 UDP 5005 / TCP 9090 冲突
echo "正在停止原系统运动中枢与桥接节点..."
pkill -f "puppypi_control/sit.py" 2>/dev/null || true
pkill -f "puppy_brain/ws_bridge_node" 2>/dev/null || true
pkill -f "puppy_brain/ros_udp_bridge" 2>/dev/null || true
sleep 1

# 1) 启动运动中枢 sit.py
#    独立版已内置路径适配，可从本目录直接运行并导入原 HiwonderPuppy 等库
echo "[1/3] 启动运动中枢 sit.py ..."
nohup "$SIT_PYTHON" "$SCRIPT_DIR/sit.py" > "$SCRIPT_DIR/log_sit.txt" 2>&1 &
echo $! > "$SCRIPT_DIR/pid_sit.txt"

sleep 2

# 2) 启动 ROS -> UDP 桥接
#    把 /puppy_action 话题上的 servo_control / follow_control / action 指令转发给 sit.py
echo "[2/3] 启动 ros_udp_bridge.py ..."
nohup python3 "$SCRIPT_DIR/ros_udp_bridge.py" > "$SCRIPT_DIR/log_ros_udp.txt" 2>&1 &
echo $! > "$SCRIPT_DIR/pid_ros_udp.txt"

sleep 1

# 3) 启动 WebSocket -> ROS 桥接
#    上位机(PC 浏览器)通过 ws://<板端IP>:9090 连接
echo "[3/3] 启动 ws_bridge_node.py ..."
nohup python3 "$SCRIPT_DIR/ws_bridge_node.py" > "$SCRIPT_DIR/log_ws.txt" 2>&1 &
echo $! > "$SCRIPT_DIR/pid_ws.txt"

sleep 1

echo ""
echo "✅ 全部启动完成。日志文件:"
echo "  sit.py          -> $SCRIPT_DIR/log_sit.txt"
echo "  ros_udp_bridge  -> $SCRIPT_DIR/log_ros_udp.txt"
echo "  ws_bridge_node  -> $SCRIPT_DIR/log_ws.txt"
echo ""
echo "📡 上位机连接:"
echo "  WebSocket  ws://<板端IP>:9090"
echo "  打开本地文件 servo_tuner.html 即可控制"
echo ""
echo "🛑 停止命令: bash $SCRIPT_DIR/stop_servo_tuner.sh"
