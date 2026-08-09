#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GS130W 轻量版 launch: 只跑避障必需的链路
   mipi_cam(双目) + stereonet(视差/深度) + hobot_shm

   与完整版的区别 (省 CPU/BPU/带宽):
   - 无 hobot_codec (不出 jpeg 流)
   - 无 websocket 节点 (官方 8000 页面不可用)
   - 无 mono2d/face/hand AI 叠加节点
   - 无 mjpeg_bridge (8071/8072/8073 不可用)

   stereonet 保留 publish_visual_enabled=True: 它是避障
   stereo_avoidance_node 的 fallback 深度源 (visual_cb)。
"""
import os
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python import get_package_share_directory

TROS = '/opt/tros/humble'
GDC_BIN = '/root/multimedia_samples/vp_sensors/gdc_bin/sc132gs_1088X1280_gdc.bin'
CALIB_YAML = f'{TROS}/lib/mipi_cam/config/SC132gs_dual_calibration.yaml'
STEREONET_MODEL = f'{TROS}/share/hobot_stereonet/config/DStereoV2.0.bin'

# ============ mipi_cam 双目 (参数与完整版完全一致, 不动原始链路) ============
mipi_node = IncludeLaunchDescription(
    PythonLaunchDescriptionSource(
        os.path.join(
            get_package_share_directory('mipi_cam'),
            'launch/mipi_cam_dual_channel.launch.py')),
    launch_arguments={
        'mipi_image_width': '1280',
        'mipi_image_height': '1088',
        'mipi_sub_image_width': '1280',
        'mipi_sub_image_height': '1088',
        'mipi_image_framerate': '10.0',
        'mipi_io_method': 'ros',
        'device_mode': 'dual',
        'dual_combine': '2',
        'mipi_channel': '2',
        'mipi_channel2': '0',
        'mipi_lpwm_enable': 'True',
        'mipi_camera_calibration_file_path': CALIB_YAML,
        'mipi_gdc_bin_file': GDC_BIN,
        'mipi_rotation': '90.0',
        'mipi_cal_rotation': '0.0',
        'mipi_gdc_enable': 'True',
        'mipi_stream_mode': '1',
        'mipi_sub_stream_enable': 'True',
        'mipi_frame_ts_type': 'sensor',
    }.items()
)

# ============ 共享内存传输 ============
shared_mem_node = IncludeLaunchDescription(
    PythonLaunchDescriptionSource(
        os.path.join(
            get_package_share_directory('hobot_shm'),
            'launch/hobot_shm.launch.py'))
)

# ============ stereonet 立体匹配 (避障数据源, 禁存盘) ============
stereonet_node = Node(
    package='hobot_stereonet',
    executable='stereonet_model_node',
    name='StereoNetNode',
    output='screen',
    parameters=[{
        'stereonet_model_file_path': STEREONET_MODEL,
        'stereo_image_topic': '/image_combine_raw',
        'publish_visual_enabled': True,   # 避障 fallback, 保留
        'publish_pcd_enabled': False,
        'publish_rectify_bgr': False,
        'render_type': 'indoor',
        'render_perf': True,
        'log_level': 'warn',
        'save_result_flag': False,
        'save_stereo_flag': False,
        'save_origin_flag': False,
        'save_disp_flag': False,
        'save_uncert_flag': False,
        'save_depth_flag': False,
        'save_visual_flag': False,
        'save_pcd_flag': False,
        'save_dir': '/dev/null',
    }],
    arguments=['--ros-args', '--log-level', 'warn']
)


def generate_launch_description():
    return LaunchDescription([
        shared_mem_node,
        mipi_node,
        stereonet_node,
    ])
