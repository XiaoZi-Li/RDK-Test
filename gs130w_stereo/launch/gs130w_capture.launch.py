#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GS130W 拍摄标定专用 launch: 最小链路, 只出左右眼画面, 不做深度

   hobot_shm + mipi_cam(双目) + hobot_codec(主路 jpeg)
   → /image_combine_jpeg 给 stereo_capture.py 订阅

   不起: stereonet / websocket / AI叠加 / 子路codec (省 BPU/CPU)
"""
import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python import get_package_share_directory

TROS = '/opt/tros/humble'
GDC_BIN = '/root/multimedia_samples/vp_sensors/gdc_bin/sc132gs_1088X1280_gdc.bin'
CALIB_YAML = f'{TROS}/lib/mipi_cam/config/SC132gs_dual_calibration.yaml'

# ============ mipi_cam 双目 (参数与避障链路完全一致, 保证拍到的图 = 深度算法输入) ============
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

# ============ 主路 jpeg 编码 (供 stereo_capture.py 订阅, 硬件 VPU 编码开销低) ============
jpeg_codec_node = IncludeLaunchDescription(
    PythonLaunchDescriptionSource(
        os.path.join(
            get_package_share_directory('hobot_codec'),
            'launch/hobot_codec_encode.launch.py')),
    launch_arguments={
        'codec_name': 'jpeg_codec_node',
        'codec_in_mode': 'ros',
        'codec_out_mode': 'ros',
        'codec_in_format': 'nv12',
        'codec_jpg_quality': '90.0',
        'codec_sub_topic': '/image_combine_raw',
        'codec_pub_topic': '/image_combine_jpeg',
    }.items()
)


def generate_launch_description():
    return LaunchDescription([
        shared_mem_node,
        mipi_node,
        jpeg_codec_node,
    ])
