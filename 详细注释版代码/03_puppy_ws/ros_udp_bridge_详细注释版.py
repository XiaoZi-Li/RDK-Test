#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ***************************************************************************************************
# 逐行详细注释版 - 专门为零基础学习者编写
# ***************************************************************************************************
#
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │                         《ROS2 UDP转发节点》                                    │
# │                                                                             │
# │  功能说明:                                                                   │
# │  将ROS2话题的消息通过UDP协议转发给机器狗底层SDK                                  │
# │  这是ROS2系统与底层控制之间的"桥梁"                                            │
# │                                                                             │
# │  为什么需要UDP转发？                                                         │
# │  ┌─────────────────────────────────────────────────────────────────┐       │
# │  │                                                                 │       │
# │  │   高层控制 (ROS2)              底层执行 (机器狗SDK)             │       │
# │  │        │                              │                          │       │
# │  │        │     UDP转发 (ros_udp_bridge) │                          │       │
# │  │        │            │                  │                          │       │
# │  │        │            ▼                  ▼                          │       │
# │  │        │   ┌─────────────────┐                                 │       │
# │  │        │   │ ros_udp_bridge │                                 │       │
# │  │        │   │  协议转换      │                                 │       │
# │  │        │   └─────────────────┘                                 │       │
# │  │                                                                 │       │
# │  └─────────────────────────────────────────────────────────────────┘       │
# │                                                                             │
# │  学习目标:                                                                   │
# │  1. 理解ROS2与底层通信的桥接模式                                             │
# │  2. 理解UDP网络编程                                                         │
# │  3. 理解协议转换的概念                                                      │
# └─────────────────────────────────────────────────────────────────────────────┘

# ***************************************************************************************************
# 第一部分：导入必要的库
# ***************************************************************************************************

# ROS2相关
import rclpy                    # ROS2 Python客户端
from rclpy.node import Node     # ROS2节点基类
from std_msgs.msg import String  # 字符串消息
from sensor_msgs.msg import Imu  # IMU传感器消息

# 标准库
import socket                    # Python网络编程库
import json                      # JSON数据解析
import time                     # 时间控制
import threading                 # 线程（用于UDP发送）

# ***************************************************************************************************
# 第二部分：常量定义
# ***************************************************************************************************

# UDP配置
UDP_IP = '127.0.0.1'       # 目标IP地址（本地回环）
UDP_PORT = 5005             # 控制命令端口
IMU_UDP_IP = '127.0.0.1'   # IMU数据目标IP
IMU_UDP_PORT = 5006         # IMU数据端口

# ROS2话题
ACTION_TOPIC = '/puppy_action'  # 动作控制话题
IMU_TOPIC = '/ros_robot_controller/imu_raw'  # IMU话题

# ***************************************************************************************************
# 第三部分：ROS UDP桥接类
# ***************************************************************************************************

class RosUdpBridge(Node):
    """
    RosUdpBridge - ROS到UDP的桥接节点

    这个节点是ROS2与底层机器狗SDK之间的"翻译官"

    它的工作：
    1. 订阅ROS2话题（/puppy_action）
    2. 将消息转换为UDP数据报
    3. 发送到指定的IP和端口

    ┌─────────────────────────────────────────────────────────────────┐
    │                                                                 │
    │   ROS2世界                        机器狗底层                      │
    │                                                                 │
    │   ┌─────────────────┐              ┌─────────────────┐          │
    │   │ decision_node   │              │                 │          │
    │   │                 │              │                 │          │
    │   │ 发布:           │              │                 │          │
    │   │ /puppy_action  │────────────▶│  机器狗SDK     │          │
    │   │                 │  ros_udp_   │                 │          │
    │   │                 │   bridge    │                 │          │
    │   └─────────────────┘              └─────────────────┘          │
    │                                                                 │
    └─────────────────────────────────────────────────────────────────┘
    """

    def __init__(self):
        """
        __init__ - 初始化节点
        """

        # -------------------- 调用父类 --------------------
        super().__init__('ros_udp_bridge')

        # -------------------- 初始化UDP --------------------
        print("=" * 60)
        print("初始化ROS UDP桥接器...")
        print("=" * 60)

        # 创建UDP socket
        # socket.AF_INET = IPv4
        # socket.SOCK_DGRAM = UDP (不是流式)
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # 设置socket选项
        # SO_BROADCAST = 允许发送广播
        # SO_REUSEADDR = 允许地址重用
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # 设置为非阻塞（可选）
        # self.udp_socket.setblocking(False)

        print(f"✓ UDP socket已创建")
        print(f"  控制目标: {UDP_IP}:{UDP_PORT}")
        print(f"  IMU目标: {IMU_UDP_IP}:{IMU_UDP_PORT}")

        # -------------------- 统计 --------------------
        self.action_count = 0  # 动作消息计数
        self.imu_count = 0    # IMU消息计数
        self.start_time = time.time()  # 启动时间

        # -------------------- 创建订阅者 --------------------

        # 订阅动作控制话题
        self.action_sub = self.create_subscription(
            String,                      # 消息类型
            ACTION_TOPIC,                 # 话题名
            self.action_callback,         # 回调函数
            10                          # 队列大小
        )

        # 订阅IMU话题
        self.imu_sub = self.create_subscription(
            Imu,                        # 消息类型
            IMU_TOPIC,                  # 话题名
            self.imu_callback,          # 回调函数
            10                         # 队列大小
        )

        # -------------------- 打印信息 --------------------
        self.get_logger().info("=" * 50)
        self.get_logger().info("ROS UDP Bridge 已启动!")
        self.get_logger().info("=" * 50)
        self.get_logger().info(f"订阅话题:")
        self.get_logger().info(f"  - {ACTION_TOPIC} (动作控制)")
        self.get_logger().info(f"  - {IMU_TOPIC} (IMU)")
        self.get_logger().info(f"转发目标:")
        self.get_logger().info(f"  - {UDP_IP}:{UDP_PORT} (动作)")
        self.get_logger().info(f"  - {IMU_UDP_IP}:{IMU_UDP_PORT} (IMU)")
        self.get_logger().info("=" * 50)

    # ***********************************************************************
    # 回调函数
    # ***********************************************************************

    def action_callback(self, msg: String):
        """
        action_callback - 动作控制回调

        当收到 /puppy_action 话题的消息时调用

        参数:
            msg: String消息，格式如 {"action": "walk", "source": "follow"}

        执行流程:
        1. 解析JSON数据
        2. 发送到UDP目标
        """
        try:
            # 解析JSON数据
            # msg.data 是字符串，如 '{"action": "walk", "source": "follow"}'
            data = json.loads(msg.data)

            # 提取动作信息
            action = data.get('action', 'stop')
            source = data.get('source', 'unknown')

            # -------------------- 通过UDP发送 --------------------
            #
            # socket.sendto() 发送UDP数据报
            # 参数:
            # - 数据（字节串）
            # - 目标地址 (IP, 端口)
            #
            # encode('utf-8') 将字符串转为字节
            self.udp_socket.sendto(
                msg.data.encode('utf-8'),
                (UDP_IP, UDP_PORT)
            )

            # -------------------- 统计 --------------------
            self.action_count += 1

            # 每100条打印一次日志
            if self.action_count % 100 == 0:
                elapsed = time.time() - self.start_time
                rate = self.action_count / elapsed
                self.get_logger().info(
                    f"动作计数: {self.action_count}, "
                    f"速率: {rate:.1f}/s, "
                    f"当前: {action} (来源:{source})"
                )

        except json.JSONDecodeError as e:
            # JSON解析失败
            self.get_logger().error(f"JSON解析失败: {e}")
            self.get_logger().error(f"原始数据: {msg.data}")

        except Exception as e:
            # 其他错误
            self.get_logger().error(f"发送失败: {e}")

    def imu_callback(self, msg: Imu):
        """
        imu_callback - IMU回调

        当收到IMU话题的消息时调用

        参数:
            msg: Imu消息

        消息结构:
        Imu:
            header: Header (时间戳和坐标系)
            orientation: Quaternion (四元数姿态)
            angular_velocity: Vector3 (角速度)
            linear_acceleration: Vector3 (线加速度)
        """
        try:
            # -------------------- 提取IMU数据 --------------------
            # 四元数姿态
            qx = msg.orientation.x
            qy = msg.orientation.y
            qz = msg.orientation.z
            qw = msg.orientation.w

            # 角速度 (陀螺仪)
            gx = msg.angular_velocity.x
            gy = msg.angular_velocity.y
            gz = msg.angular_velocity.z

            # 线加速度
            ax = msg.linear_acceleration.x
            ay = msg.linear_acceleration.y
            az = msg.linear_acceleration.z

            # -------------------- 创建JSON消息 --------------------
            imu_data = {
                "type": "imu",
                "timestamp": time.time(),
                "orientation": {"x": qx, "y": qy, "z": qz, "w": qw},
                "angular_velocity": {"x": gx, "y": gy, "z": gz},
                "linear_acceleration": {"x": ax, "y": ay, "z": az}
            }

            imu_json = json.dumps(imu_data)

            # -------------------- 发送到UDP --------------------
            self.udp_socket.sendto(
                imu_json.encode('utf-8'),
                (IMU_UDP_IP, IMU_UDP_PORT)
            )

            # -------------------- 统计 --------------------
            self.imu_count += 1

            # 每1000条打印一次
            if self.imu_count % 1000 == 0:
                elapsed = time.time() - self.start_time
                rate = self.imu_count / elapsed
                self.get_logger().info(
                    f"IMU计数: {self.imu_count}, 速率: {rate:.1f}/s"
                )

        except Exception as e:
            self.get_logger().error(f"IMU发送失败: {e}")

    # ***********************************************************************
    # 清理
    # ***********************************************************************

    def cleanup(self):
        """
        cleanup - 清理资源

        关闭UDP socket
        """
        if self.udp_socket:
            self.udp_socket.close()
            self.get_logger().info("UDP socket已关闭")

# ***************************************************************************************************
# 第四部分：主函数
# ***************************************************************************************************

def main(args=None):
    """
    main - 程序入口
    """

    # -------------------- 初始化 --------------------
    rclpy.init(args=args)

    # -------------------- 创建节点 --------------------
    bridge = RosUdpBridge()

    # -------------------- 运行 --------------------
    try:
        bridge.get_logger().info("开始转发...")
        rclpy.spin(bridge)

    except KeyboardInterrupt:
        bridge.get_logger().info("收到中断信号...")

    finally:
        # -------------------- 清理 --------------------
        bridge.cleanup()
        bridge.destroy_node()
        rclpy.shutdown()
        bridge.get_logger().info("节点已关闭")

# ***************************************************************************************************
# 第五部分：入口
# ***************************************************************************************************

if __name__ == '__main__':
    main()

# ***************************************************************************************************
# 知识详解
# ***************************************************************************************************
#
# 1. UDP vs TCP
#
#    UDP和TCP是两种网络协议
#    ┌─────────────────────────────────────────────────────────────────┐
#    │                                                                 │
#    │   TCP (传输控制协议)                                            │
#    │   - 面向连接（三次握手）                                        │
#    │   - 可靠传输（确认、重传）                                      │
#    │   - 有顺序                                                       │
#    │   - 较慢                                                         │
#    │   用途: 网页、文件传输、邮件                                      │
#    │                                                                 │
#    │   UDP (用户数据报协议)                                          │
#    │   - 无连接（直接发送）                                          │
#    │   - 不可靠传输（不确认）                                         │
#    │   - 无顺序                                                       │
#    │   - 较快                                                           │
#    │   用途: 视频流、语音、游戏、实时控制                              │
#    │                                                                 │
#    └─────────────────────────────────────────────────────────────────┘
#
#    为什么机器狗用UDP？
#    - 实时性要求高，宁可丢帧也不等待                                   │
#    - 控制指令需要高速传输                                             │
#    - 即使丢一帧，下一帧马上跟上                                      │
#
# 2. Socket编程
#
#    Socket是网络编程的基础
#    ┌─────────────────────────────────────────────────────────────────┐
#    │                                                                 │
#    │   创建socket:                                                  │
#    │   sock = socket.socket(family, type)                           │
#    │                                                                 │
#    │   TCP服务器:                                                   │
#    │   sock.bind((ip, port))    # 绑定地址                          │
#    │   sock.listen()            # 监听                              │
#    │   conn, addr = sock.accept()  # 接受连接                        │
#    │                                                                 │
#    │   TCP客户端:                                                   │
#    │   sock.connect((ip, port))  # 连接服务器                       │
#    │                                                                 │
#    │   UDP (双方对等):                                              │
#    │   sock.sendto(data, (ip, port))   # 发送                      │
#    │   data, addr = sock.recvfrom(size)  # 接收                     │
#    │                                                                 │
#    └─────────────────────────────────────────────────────────────────┘
#
# 3. 协议转换
#
#    这个节点做的是"协议转换"
#    ┌─────────────────────────────────────────────────────────────────┐
#    │                                                                 │
#    │   ROS2消息 (JSON字符串)                                         │
#    │        │                                                        │
#    │        │ json.loads()                                          │
#    │        ▼                                                        │
#    │   Python字典                                                     │
#    │        │                                                        │
#    │        │ json.dumps()                                          │
#    │        ▼                                                        │
#    │   JSON字节串                                                     │
#    │        │                                                        │
#    │        │ socket.sendto()                                       │
#    │        ▼                                                        │
#    │   UDP数据报                                                     │
#    │        │                                                        │
#    │        ▼                                                        │
#    │   底层SDK                                                       │
#    │                                                                 │
#    └─────────────────────────────────────────────────────────────────┘
#
# 4. 机器狗控制指令格式
#
#    JSON格式的控制指令：
#    ┌─────────────────────────────────────────────────────────────────┐
#    │                                                                 │
#    │   {                                                            │
#    │     "action": "walk",      // 动作名称                           │
#    │     "source": "follow",   // 来源                               │
#    │     "timestamp": 1234567890.123  // 时间戳                      │
#    │   }                                                            │
#    │                                                                 │
#    │   常用动作：                                                    │
#    │   - "walk"      : 前进                                         │
#    │   - "backward"  : 后退                                         │
#    │   - "turn_left" : 左转                                         │
#    │   - "turn_right": 右转                                         │
#    │   - "stop"      : 停止                                         │
#    │   - "sit"       : 坐下                                         │
#    │   - "stand"     : 站立                                         │
#    │                                                                 │
#    └─────────────────────────────────────────────────────────────────┘
#
# ***************************************************************************************************
# 常见问题
# ***************************************************************************************************
#
# Q: UDP发送失败？
#   - 检查目标IP和端口是否正确
#   - 检查防火墙是否阻止
#   - 检查目标服务是否在监听
#
# Q: 机器狗没反应？
#   - 检查底层SDK是否运行
#   - 检查UDP端口是否匹配
#   - 使用网络调试工具测试连通性
#
# Q: 消息丢失？
#   - UDP本身不保证可靠传输
#   - 这是设计如此，实时性>可靠性
#
# ***************************************************************************************************

print("=" * 60)
print("ROS UDP Bridge ROS到UDP桥接器")
print("=" * 60)
