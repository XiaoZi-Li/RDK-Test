# multimedia_samples 模块详细使用指南

## 目录
1. [模块概述](#1-模块概述)
2. [目录结构](#2-目录结构)
3. [编译方法](#3-编译方法)
4. [sample_codec 视频编解码详解](#4-sample_codec-视频编解码详解)
   - [功能说明](#41-功能说明)
   - [配置文件详解](#42-配置文件详解)
   - [使用方法](#43-使用方法)
5. [sample_osd OSD区域叠加详解](#5-sample_osd-osd区域叠加详解)
   - [功能说明](#51-功能说明)
   - [工作模式](#52-工作模式)
   - [使用方法](#53-使用方法)
6. [sample_vse 视频处理详解](#6-sample_vse-视频处理详解)
7. [sample_vin 视频输入详解](#7-sample_vin-视频输入详解)
8. [sample_isp ISP处理详解](#8-sample_isp-isp处理详解)
9. [sample_hbmem 共享内存详解](#9-sample_hbmem-共享内存详解)
10. [sample_imu IMU传感器详解](#10-sample_imu-imu传感器详解)
11. [sample_pipeline 流水线详解](#11-sample_pipeline-流水线详解)
12. [常见问题解决](#12-常见问题解决)

---

## 1. 模块概述

### 1.1 功能说明
multimedia_samples 模块提供基于地平线 X5 平台的多媒体处理示例，包括：
- 视频编解码 (H.264/H.265/MJPEG)
- OSD区域叠加 (文字/线条/马赛克/覆盖)
- 视频缩放/裁剪/旋转 (VSE)
- 视频输入捕获 (VIN)
- ISP图像处理
- 共享内存管理
- IMU传感器读取

### 1.2 技术特点
| 特性 | 说明 |
|------|------|
| 硬件加速 | 利用VPU进行视频编解码 |
| 零拷贝 | 使用共享内存减少数据传输 |
| 多通道 | 支持多个视频输入/输出通道 |
| 实时处理 | 支持实时视频流处理 |

---

## 2. 目录结构

```
multimedia_samples/
├── sample_codec/           # 视频编解码
│   ├── sample_codec.c      # 主程序
│   ├── sample_codec.h      # 头文件
│   ├── codec_config.ini    # 配置文件
│   ├── 1920x1080_NV12.yuv  # 测试视频
│   ├── 1920x1080_30fps.h264 # H.264测试码流
│   └── Readme.md           # 使用说明
│
├── sample_osd/             # OSD叠加
│   ├── sample_osd.c        # 主程序
│   ├── 1280x720_NV12.yuv  # 测试图像
│   └── Makefile
│
├── sample_vse/             # 视频处理
│   ├── sample_vse.c        # 主程序
│   └── Makefile
│
├── sample_vin/             # 视频输入
│   └── get_vin_data/       # 获取VIN数据
│
├── sample_isp/             # ISP处理
│   ├── get_isp_data/       # 获取ISP数据
│   ├── get_isp_rgb_ir/     # 获取RGB-IR数据
│   ├── isp_feedback/       # ISP反馈
│   └── multi_isp_vflow/    # 多ISP流水线
│
├── sample_hbmem/           # 共享内存
│   ├── sample.c            # 基本示例
│   ├── sample_alloc.c      # 内存分配
│   ├── sample_pool.c       # 内存池
│   ├── sample_queue.c      # 队列
│   ├── sample_share.c      # 共享内存
│   ├── sample_share_pool.c # 共享内存池
│   ├── sample_common.c/h   # 公共函数
│   └── Makefile
│
├── sample_imu/             # IMU传感器
│   ├── sample_imu.c        # 主程序
│   ├── imu_manager.c/h     # IMU管理器
│   ├── bmi08x.c           # BMI08X陀螺仪
│   ├── icm42688.c         # ICM42688陀螺仪
│   ├── imu_interface.h    # 接口定义
│   └── Makefile
│
├── sample_pipeline/         # 视频流水线
│   ├── common/            # 公共组件
│   │   ├── bpu_common.h
│   │   ├── bpu_wraper.c/h
│   │   ├── mqueue.c/h     # 消息队列
│   │   ├── mthread.c/h    # 线程管理
│   │   ├── util.h
│   │   ├── vp_codec.c/h   # 编解码封装
│   │   ├── vp_display.c/h # 显示封装
│   │   ├── vp_pipeline.c/h # 流水线封装
│   │   └── uthash.h
│   ├── Makefile
│   └── README.md
│
├── sample_dsp/             # DSP处理
├── sample_gpu_2d/          # 2D GPU处理
├── sample_gpu_3d/          # 3D GPU处理
├── sample_audio/           # 音频处理
├── sample_gdc/             # GDC几何校正
├── sample_usb/             # USB设备
├── sample_trustzone/       # 安全世界
├── sample_vot/             # VOT跟踪
├── sunrise_camera/         # 摄像头示例
├── tuning_tool/            # 调优工具
├── sysinfopro/            # 系统信息
├── vp_sensors/            # 传感器配置
└── Makefile               # 顶层Makefile
```

---

## 3. 编译方法

### 3.1 编译全部示例
```bash
cd /app/multimedia_samples
make
```

### 3.2 编译单个示例
```bash
cd /app/multimedia_samples/sample_codec
make

cd /app/multimedia_samples/sample_osd
make
```

### 3.3 清理编译文件
```bash
cd /app/multimedia_samples
make clean
```

---

## 4. sample_codec 视频编解码详解

### 4.1 功能说明

sample_codec 提供视频编码和解码功能：

| 功能 | 支持格式 |
|------|----------|
| 编码 | H.264, H.265, MJPEG, JPEG |
| 解码 | H.264, H.265, MJPEG |
| 输入格式 | NV12 YUV |
| 输出格式 | 码流文件(.264/.265) 或 YUV文件 |

### 4.2 配置文件详解

**codec_config.ini:**
```ini
[encode]
# 启用编码，按位运算
# 0x0 = 不编码
# 0x01 = venc_stream1
# 0x02 = venc_stream2
# 0x03 = venc_stream1 + venc_stream2
# 0x07 = 前三路
encode_streams = 0x1

[venc_stream1]
# 编码类型: 0=H264, 1=H265, 2=MJPEG, 3=JPEG
codec_type = 0

# 输出分辨率
width = 1920
height = 1080

# 帧率 (fps)
frame_rate = 30

# 码率 (kbps)
bit_rate = 8192

# 输入文件 (NV12 YUV格式)
input = 1920x1080.yuv

# 输出码流文件
output = 1920x1080_30fps.264

# 编码帧数 (0=无限)
frame_num = 100

[venc_stream2]
# 可以定义第二路编码流
codec_type = 1
width = 1280
height = 720
frame_rate = 30
bit_rate = 4096
input = 1280x720.yuv
output = 1280x720_30fps.265
frame_num = 100

[decode]
# 启用解码，按位运算
# 0x01 = vdec_stream1
# 0x02 = vdec_stream2
# 0x03 = vdec_stream1 + vdec_stream2
decode_streams = 0x0

[vdec_stream1]
# 解码类型: 0=H264, 1=H265
codec_type = 0

# 解码后分辨率
width = 1920
height = 1080

# 输入码流文件
input = 1920x1080_30fps.264

# 输出YUV文件
output = 1920x1080.yuv
```

### 4.3 使用方法

#### 基本命令
```bash
# 使用默认配置编码
./sample_codec

# 使用默认配置解码
./sample_codec

# 启用详细模式
./sample_codec -v
```

#### 指定编码流
```bash
# 只启用编码流1
./sample_codec -e 0x1

# 启用编码流1和2
./sample_codec -e 0x3

# 启用前三路编码流
./sample_codec -e 0x7
```

#### 指定解码流
```bash
# 只启用解码流1
./sample_codec -d 0x1

# 启用解码流1和2
./sample_codec -d 0x3
```

#### 同时启用编码和解码
```bash
./sample_codec -e 0x1 -d 0x1
```

### 4.4 参数调整指南

#### 编码质量调整
```ini
# 高质量低压缩 (H.264)
bit_rate = 8192        # 高码率
frame_rate = 30        # 正常帧率

# 低质量高压缩 (H.264)
bit_rate = 2048        # 低码率
frame_rate = 15        # 低帧率
```

#### 分辨率选择
```ini
# 1080P
width = 1920
height = 1080

# 720P
width = 1280
height = 720

# 480P
width = 640
height = 480
```

#### 编码类型选择
```ini
# H.264 - 最佳兼容性
codec_type = 0

# H.265 - 更高压缩率
codec_type = 1

# MJPEG - 动态编码
codec_type = 2

# JPEG - 静态图像
codec_type = 3
```

---

## 5. sample_osd OSD区域叠加详解

### 5.1 功能说明

sample_osd 提供在视频上叠加OSD(区域叠加显示)的功能：

| 功能 | 说明 |
|------|------|
| COVER | 多边形/矩形区域覆盖 |
| OSD | 文字叠加 |
| LINE | 线条绘制 |
| MOSAIC | 马赛克效果 |

### 5.2 工作模式

| 模式 | 值 | 说明 |
|------|---|------|
| cover_test | 1 | 多边形/矩形覆盖 |
| draw_word_test | 2 | 绘制文字(时间戳等) |
| draw_line_test | 3 | 绘制线条 |
| mosaic_test | 4 | 区域马赛克 |

### 5.3 使用方法

#### 基本命令
```bash
# 覆盖测试
./sample_osd -i input.yuv -w 1280 -h 720 -m 1

# 文字测试
./sample_osd -i input.yuv -w 1280 -h 720 -m 2

# 线条测试
./sample_osd -i input.yuv -w 1280 -h 720 -m 3

# 马赛克测试
./sample_osd -i input.yuv -w 1280 -h 720 -m 4

# 反馈模式
./sample_osd -i input.yuv -w 1280 -h 720 -m 1 -f
```

#### 参数说明
```bash
-i, --input_file    输入YUV文件路径
-w, --input_width   输入宽度
-h, --input_height  输入高度
-m, --work_mode     工作模式 (1-4)
-f, --feedback      启用反馈模式
```

### 5.4 COVER模式详解

COVER模式支持多边形和矩形覆盖:

#### 代码配置示例
```c
// 多边形覆盖配置
region_polygon.type = COVER_RGN;
region_polygon.color = FONT_COLOR_PINK;
region_polygon.cover_attr.cover_type = COVER_POLYGON;
region_polygon.cover_attr.polygon.side_num = 3;  // 三角形
region_polygon.cover_attr.polygon.vertex[0].x = 100;
region_polygon.cover_attr.polygon.vertex[0].y = 100;
region_polygon.cover_attr.polygon.vertex[1].x = 300;
region_polygon.cover_attr.polygon.vertex[1].y = 400;
region_polygon.cover_attr.polygon.vertex[2].x = 500;
region_polygon.cover_attr.polygon.vertex[2].y = 200;

// 矩形覆盖配置
region_rect.type = COVER_RGN;
region_rect.color = FONT_COLOR_BROWN;
region_rect.cover_attr.cover_type = COVER_RECT;
region_rect.cover_attr.size.width = 160;
region_rect.cover_attr.size.height = 200;
```

#### 颜色定义
```c
FONT_COLOR_PINK     // 粉色
FONT_COLOR_BROWN    // 棕色
FONT_COLOR_ORANGE   // 橙色
FONT_COLOR_YELLOW   // 黄色
FONT_COLOR_WHITE    // 白色
FONT_COLOR_DARKBLUE // 深蓝色
FONT_COLOR_DARKGRAY // 深灰色
```

### 5.5 文字绘制模式详解

#### 代码配置示例
```c
// 字体设置
draw_word.font_size = FONT_SIZE_MEDIUM;       // 字体大小
draw_word.font_color = FONT_COLOR_WHITE;     // 字体颜色
draw_word.bg_color = FONT_COLOR_DARKGRAY;    // 背景颜色
draw_word.font_alpha = 15;                    // 字体透明度
draw_word.bg_alpha = 2;                      // 背景透明度
draw_word.point.x = 0;
draw_word.point.y = 0;
draw_word.draw_string = (uint8_t*)str;      // 要显示的字符串

// 时间戳示例
time_t tt = time(0);
strftime(str, sizeof(str), "%Y-%m-%d %H:%M:%S", localtime(&tt));
```

### 5.6 线条绘制模式详解

#### 代码配置示例
```c
// 线条样式
draw_line.thick = 4;                 // 线宽
draw_line.flush_en = false;          // 是否刷新
draw_line.color = FONT_COLOR_RED;    // 线条颜色
draw_line.alpha = 15;                // 透明度

// 绘制线段
draw_line.start_point.x = 20;
draw_line.start_point.y = 20;
draw_line.end_point.x = 200;
draw_line.end_point.y = 20;

// 执行绘制
ret = hbn_rgn_draw_line(&draw_line);
```

### 5.7 马赛克模式详解

#### 代码配置示例
```c
// 马赛克区域设置
region_rectangle.type = MOSAIC_RGN;
region_rectangle.mosaic_chn.size.width = 400;   // 马赛克宽度
region_rectangle.mosaic_chn.size.height = 200; // 马赛克高度

// 位置设置
rgn_chn.show = true;
rgn_chn.invert_en = 0;
rgn_chn.display_level = 1;
rgn_chn.point.x = 100;  // X坐标
rgn_chn.point.y = 100;  // Y坐标
```

---

## 6. sample_vse 视频处理详解

### 6.1 功能说明
VSE (Video Scaling Engine) 提供视频缩放、裁剪功能。

### 6.2 使用方法
```bash
# 编译
cd sample_vse && make

# 运行
./sample_vse
```

---

## 7. sample_vin 视频输入详解

### 7.1 功能说明
VIN (Video Input) 模块从摄像头捕获视频。

### 7.2 使用方法
```bash
# 进入目录
cd sample_vin/get_vin_data

# 编译
make

# 查看支持传感器
./get_vin_data -h

# 运行 (选择传感器)
./get_vin_data -s 0
```

### 7.3 参数说明
```bash
-s, --sensor  传感器索引号
```

---

## 8. sample_isp ISP处理详解

### 8.1 功能说明
ISP (Image Signal Processor) 进行图像信号处理，包括：
- 坏点校正
- 噪声去除
- 颜色校正
- 锐化
- 自动曝光/白平衡

### 8.2 子目录说明

| 目录 | 功能 |
|------|------|
| get_isp_data | 获取ISP处理后的图像 |
| get_isp_rgb_ir | 获取RGB-IR数据 |
| isp_feedback | ISP反馈控制 |
| multi_isp_vflow | 多ISP流水线 |

### 8.3 使用方法
```bash
cd sample_isp/get_isp_data
make
./get_isp_data -h    # 查看帮助
./get_isp_data -s 0  # 运行
```

---

## 9. sample_hbmem 共享内存详解

### 9.1 功能说明
HBMEM (High Bandwidth Memory) 提供高效共享内存管理。

### 9.2 示例文件说明

| 文件 | 功能 |
|------|------|
| sample.c | 基本共享内存操作 |
| sample_alloc.c | 内存分配示例 |
| sample_pool.c | 内存池管理 |
| sample_queue.c | 队列操作 |
| sample_share.c | 共享内存创建/映射 |
| sample_share_pool.c | 共享内存池 |

### 9.3 核心API
```c
// 分配内存
int hb_mem_alloc_graph_buf(int width, int height, int fmt,
                          uint64_t alloc_flags, ...);

// 释放内存
int hb_mem_free_buf(int fd);

// 获取物理地址
uint64_t hb_mem_get_phyaddr(void *buf);

// 内存映射
void* hb_mem_map(uint64_t phyaddr, int size);
```

---

## 10. sample_imu IMU传感器详解

### 10.1 功能说明
IMU (Inertial Measurement Unit) 读取陀螺仪和加速度计数据。

### 10.2 支持传感器

| 型号 | 类型 |
|------|------|
| BMI08X | 6轴IMU (陀螺仪+加速度计) |
| ICM42688 | 6轴IMU (高精度) |

### 10.3 使用方法
```bash
cd sample_imu
make
./sample_imu
```

### 10.4 输出格式
```bash
# 加速度计数据
accel_x: 0.123  accel_y: -0.456  accel_z: 9.810

# 陀螺仪数据
gyro_x: 0.001  gyro_y: -0.002  gyro_z: 0.000

# 温度
temperature: 25.5
```

---

## 11. sample_pipeline 流水线详解

### 11.1 功能说明
提供模块化的视频处理流水线框架。

### 11.2 核心组件

```c
// 消息队列
typedef struct {
    void *data;
    int size;
    int type;
} mqueue_msg_t;

// 线程管理
typedef struct {
    pthread_t tid;
    int running;
    mqueue_t *queue;
} mthread_t;

// 管道上下文
typedef struct {
    int vin_chn;
    int vps_chn;
    int bpu_chn;
    int display_chn;
} pipe_contex_t;
```

### 11.3 流水线类型

| 类型 | 说明 |
|------|------|
| VIN → ISP → VSE → DISPLAY | 基础预览 |
| VIN → ISP → BPU → DISPLAY | AI检测预览 |
| DECODE → VPS → BPU → DISPLAY | RTSP流检测 |

---

## 12. 常见问题解决

### 12.1 编译错误

**问题**: `undefined reference to 'hb_mem_alloc_graph_buf'`

**解决**:
```bash
# 确保链接了正确的库
-l:libmem.so
```

### 12.2 运行时错误

**问题**: `i2c open failed`

**解决**:
```bash
# 检查I2C设备
ls -la /dev/i2c-*

# 设置权限
chmod 777 /dev/i2c-*
```

### 12.3 视频格式不支持

**问题**: `unsupported video format`

**解决**:
```bash
# 确保输入是NV12格式
# 使用ffmpeg转换
ffmpeg -i input.mp4 -pix_fmt nv12 -s 1280x720 output.yuv
```

### 12.4 内存不足

**问题**: `hb_mem_alloc failed`

**解决**:
```bash
# 减小分辨率
# 减少通道数
# 释放不需要的资源
```

---

## 附录: 命令速查表

```bash
# 编译所有
cd /app/multimedia_samples && make

# 编译单个示例
cd /app/multimedia_samples/sample_codec && make

# 运行编解码
./sample_codec -e 0x1 -d 0x0 -v

# 运行OSD
./sample_osd -i input.yuv -w 1280 -h 720 -m 1

# 获取VIN数据
./get_vin_data -s 0

# 获取ISP数据
./get_isp_data -s 0

# 运行IMU
./sample_imu
```

---

**文档版本**: 1.0
**更新日期**: 2026-04-20
**适用平台**: 地平线 X5 开发板
