#!/bin/bash
# =========================================================
# 运动调节上位机 · 独立停止脚本
# =========================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "正在停止 servo_tuner_pkg 相关进程..."

# 1) 通过 pid 文件停止本脚本启动的进程
for pid_file in "$SCRIPT_DIR"/pid_*.txt; do
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        name=$(basename "$pid_file" .txt)
        if kill -0 "$pid" 2>/dev/null; then
            echo "  停止 $name (PID $pid)"
            kill "$pid" 2>/dev/null || true
            sleep 0.5
            kill -9 "$pid" 2>/dev/null || true
        fi
        rm -f "$pid_file"
    fi
done

# 2) 保险：按脚本路径再清理一次，防止手动启动的残留
for script in sit.py ros_udp_bridge.py ws_bridge_node.py; do
    pgrep -f "$SCRIPT_DIR/$script" | while read -r pid; do
        echo "  停止残留 $script (PID $pid)"
        kill "$pid" 2>/dev/null || true
        sleep 0.2
        kill -9 "$pid" 2>/dev/null || true
    done
done

# 3) 同时停止原系统运动中枢与桥接节点（避免端口冲突）
echo "同时清理原系统相关进程..."
pkill -f "puppypi_control/sit.py" 2>/dev/null || true
pkill -f "puppy_brain/ws_bridge_node" 2>/dev/null || true
pkill -f "puppy_brain/ros_udp_bridge" 2>/dev/null || true
sleep 0.5

echo "✅ 已停止 servo_tuner_pkg 全部进程。"
