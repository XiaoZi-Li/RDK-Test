#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
imu_node_ros2.py - IMU传感器节点
================================================================================

【程序功能】
本程序是Puppy机器人ROS2系统中的IMU（惯性测量单元）传感器节点。
负责从机器人底板读取IMU数据（加速度、角速度），并以ROS2标准格式发布。

【IMU数据类型】
1. 线加速度 (linear_acceleration)
   - ax: X轴加速度
   - ay: Y轴加速度
   - az: Z轴加速度
   - 单位: m/s²

2. 角速度 (angular_velocity)
   - gx: X轴角速度（翻滚）
   - gy: Y轴角速度（俯仰）
   - gz: Z轴角速度（偏航）
   - 单位: rad/s

【ROS2消息格式】
sensor_msgs/Imu:
  std_msgs/Header header
    time stamp        # 时间戳
    string frame_id   # 坐标系ID (imu_link)
  geometry_msgs/Vector3 angular_velocity     # 角速度
  geometry_msgs/Vector3 linear_acceleration # 线加速度
  float64 orientation      # 四元数（暂未使用）
  float64 orientation_covariance
  float64 angular_velocity_covariance
  float64 linear_acceleration_covariance

【硬件连接】
- IMU通过I2C或串口连接到机器人底板
- 底板通过USB或串口与主控通信
- 使用ros_robot_controller_sdk读取数据

【参数配置】
- topic_name: 发布话题名（默认 /ros_robot_controller/imu_raw）
- publish_hz: 发布频率（默认 50Hz）

【运行方式】
ros2 run puppy_brain imu_node_ros2

【标定注意事项】
- IMU使用前需要标定
- 静止状态下Z轴应该有约9.8m/s²的重力加速度
- 长时间运行会有漂移，需要软件补偿

================================================================================
"""

import os
import sys
import time
from threading import Lock

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu

SDK_DIR = '/app/pydev_demo/puppypi_control'
if SDK_DIR not in sys.path:
    sys.path.append(SDK_DIR)

from ros_robot_controller_sdk import Board


class ImuNodeRos2(Node):
    """
    IMU传感器节点

    【功能】
        1. 初始化底板通信
        2. 定时读取IMU数据
        3. 转换为ROS2标准格式并发布
    """

    def __init__(self):
        """节点初始化"""
        super().__init__('imu_node_ros2')

        # 声明参数
        self.declare_parameter('topic_name', '/ros_robot_controller/imu_raw')
        self.declare_parameter('publish_hz', 50.0)

        # 获取参数值
        self.topic_name = str(self.get_parameter('topic_name').value)
        self.publish_hz = float(self.get_parameter('publish_hz').value)

        # 创建发布者
        self.imu_pub = self.create_publisher(Imu, self.topic_name, 10)

        # 初始化底板通信
        self.board = Board()
        self.board.enable_reception()

        # 线程安全锁
        self.data_lock = Lock()
        self.last_log_time = 0.0

        # 创建定时器
        timer_period = 1.0 / self.publish_hz
        self.timer = self.create_timer(timer_period, self.timer_callback)

        self.get_logger().info(
            f'imu_node_ros2 started. publish topic={self.topic_name}, hz={self.publish_hz}'
        )


    def timer_callback(self):
        """
        定时器回调 - 读取并发布IMU数据

        【数据格式】
            board.get_imu()返回6个值:
            - data[0]: ax (X轴加速度)
            - data[1]: ay (Y轴加速度)
            - data[2]: az (Z轴加速度)
            - data[3]: gx (X轴角速度)
            - data[4]: gy (Y轴角速度)
            - data[5]: gz (Z轴角速度)
        """
        try:
            data = self.board.get_imu()
        except Exception as e:
            now = time.time()
            if now - self.last_log_time > 1.0:
                self.get_logger().warn(f'get_imu() exception: {e}')
                self.last_log_time = now
            return

        if data is None:
            now = time.time()
            if now - self.last_log_time > 1.0:
                self.get_logger().warn('get_imu() returned None')
                self.last_log_time = now
            return

        # 数据有效性检查
        if not isinstance(data, (list, tuple)) or len(data) < 6:
            now = time.time()
            if now - self.last_log_time > 1.0:
                self.get_logger().warn(f'get_imu() invalid data: {data}')
                self.last_log_time = now
            return

        # 创建IMU消息
        imu_msg = Imu()

        # 设置消息头
        imu_msg.header.stamp = self.get_clock().now().to_msg()
        imu_msg.header.frame_id = 'imu_link'

        # 填充线加速度数据
        imu_msg.linear_acceleration.x = float(data[0])
        imu_msg.linear_acceleration.y = float(data[1])
        imu_msg.linear_acceleration.z = float(data[2])

        # 填充角速度数据
        imu_msg.angular_velocity.x = float(data[3])
        imu_msg.angular_velocity.y = float(data[4])
        imu_msg.angular_velocity.z = float(data[5])

        # 四元数方向（当前未标定，设为默认值）
        imu_msg.orientation.x = 0.0
        imu_msg.orientation.y = 0.0
        imu_msg.orientation.z = 0.0
        imu_msg.orientation.w = 1.0

        # 发布消息
        self.imu_pub.publish(imu_msg)

        # 定期打印日志（每1秒）
        now = time.time()
        if now - self.last_log_time > 1.0:
            self.get_logger().info(
                'publish imu: '
                f'acc=({imu_msg.linear_acceleration.x:.3f}, '
                f'{imu_msg.linear_acceleration.y:.3f}, '
                f'{imu_msg.linear_acceleration.z:.3f}) '
                f'gyro=({imu_msg.angular_velocity.x:.3f}, '
                f'{imu_msg.angular_velocity.y:.3f}, '
                f'{imu_msg.angular_velocity.z:.3f})'
            )
            self.last_log_time = now


def main(args=None):
    """主函数"""
    rclpy.init(args=args)
    node = ImuNodeRos2()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()

# ================================================================================
# 【IMU坐标系说明】
# ================================================================================
# 机器人IMU坐标系通常定义为：
#
#        +X (前方)
#         │
#         │
#         ▼
#    +Z   ────── +Y (右方)
#
# X轴: 指向前进方向
# Y轴: 指向机器人右侧
# Z轴: 垂直向上
#
# 【加速度说明】
# - 静止时，az ≈ 9.8 m/s² (受到重力)
# - 向前加速时，ax > 0
# - 向右移动时，ay > 0
#
# 【角速度说明】
# - 绕X轴旋转: 翻滚角速度 (roll rate)
# - 绕Y轴旋转: 俯仰角速度 (pitch rate)
# - 绕Z轴旋转: 偏航角速度 (yaw rate)
#
# 【使用场景】
# - 平衡控制: 使用角速度反馈保持机器人平衡
# - 导航: 结合陀螺仪进行姿态估计
# - 跌倒检测: 检测机器人是否摔倒
# - 运动检测: 检测机器人运动状态
