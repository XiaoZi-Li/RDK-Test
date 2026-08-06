# cdev_demo 模块详细使用指南

## 目录
1. [模块概述](#1-模块概述)
2. [目录结构](#2-目录结构)
3. [编译方法](#3-编译方法)
4. [BPU加速器示例详解](#4-bpu加速器示例详解)
   - [hb_dnn_test.cpp 核心文件](#41-hb_dnn_testcpp-核心文件)
   - [支持的模型类型](#42-支持的模型类型)
   - [命令行参数](#43-命令行参数)
5. [各模型使用详解](#5-各模型使用详解)
   - [YOLOv5 目标检测](#51-yolov5-目标检测)
   - [FCOS 目标检测](#52-fcos-目标检测)
   - [YOLOv3 目标检测](#53-yolov3-目标检测)
   - [SSD MobileNetV1](#54-ssd-mobilenetv1)
   - [CenterNet](#55-centernet)
   - [MobileNetV1 分类](#56-mobilenetv1-分类)
   - [UNet 语义分割](#57-unet-语义分割)
6. [后处理参数调整](#6-后处理参数调整)
7. [多线程架构分析](#7-多线程架构分析)
8. [模型文件说明](#8-模型文件说明)
9. [常见问题解决](#9-常见问题解决)

---

## 1. 模块概述

### 1.1 功能说明
cdev_demo 模块提供基于 **BPU (Byte Processing Unit) 深度学习加速器** 的 AI 推理示例。通过字符设备接口直接调用 BPU 硬件加速器进行模型推理，实现高性能目标检测、图像分类、语义分割等任务。

### 1.2 技术特点
| 特性 | 说明 |
|------|------|
| 硬件加速 | 利用 BPU 加速器进行神经网络推理 |
| 多线程 | 预处理、BPU推理、后处理并行执行 |
| 多模型支持 | 支持 YOLO、FCOS、SSD、CenterNet、UNet 等 |
| 实时显示 | 支持 HDMI 显示检测结果 |

### 1.3 核心组件
| 组件 | 说明 |
|------|------|
| hb_dnn_test.cpp | 主程序，包含所有模型推理逻辑 |
| hb_dnn_test.hpp | 头文件，定义结构和常量 |
| post_process 文件 | 各模型后处理实现 |
| Makefile | 编译配置 |

---

## 2. 目录结构

```
cdev_demo/
├── bpu/
│   ├── README.md              # 使用说明
│   ├── include/              # 头文件目录
│   │   ├── hb_dnn_test.hpp
│   │   ├── yolov3_post_process.hpp
│   │   ├── yolov5_post_process.hpp
│   │   ├── fcos_post_process.hpp
│   │   ├── ptq_ssd_post_process_method.hpp
│   │   ├── ptq_unet_post_process_method.hpp
│   │   └── ...
│   ├── src/
│   │   ├── bin/
│   │   │   ├── sample           # 编译后的可执行文件
│   │   │   └── 1080p_.h264     # 测试视频
│   │   ├── build/               # 编译临时文件
│   │   ├── Makefile
│   │   ├── hb_dnn_test.cpp     # 主程序
│   │   ├── yolov3_post_process.cpp
│   │   ├── yolov5_post_process.cpp
│   │   ├── fcos_post_process.cpp
│   │   └── ...
│   └── Makefile
├── decode2display/            # 解码显示示例
├── rtsp2display/              # RTSP流显示示例
├── v4l2/                      # V4L2示例
├── vio2display/                # 视频输入输出显示
├── vio2encoder/               # 视频输入编码
└── vio_capture/               # 视频捕获
```

---

## 3. 编译方法

### 3.1 编译步骤

```bash
# 进入BPU示例目录
cd /app/cdev_demo/bpu/src

# 清理之前的编译文件
make clean

# 编译
make

# 编译完成后，可执行文件位于 bin/ 目录
ls -la ../bin/
```

### 3.2 编译输出
```
sample  # 可执行文件
```

### 3.3 依赖项
| 依赖 | 说明 |
|------|------|
| OpenCV | 图像处理 |
| pthread | 多线程 |
| argp | 命令行参数解析 |
| hb_dnn | BPU推理库 |
| hb_vio | 视频输入输出库 |

---

## 4. BPU加速器示例详解

### 4.1 hb_dnn_test.cpp 核心文件

#### 主函数结构
```cpp
int main(int argc, char *argv[])
{
    // 1. 信号处理设置
    signal(SIGINT, signal_handler_func);

    // 2. 解析命令行参数
    argp_parse(&argp, argc, argv, ARGP_IN_ORDER, 0, &args);

    // 3. 根据模式选择不同处理流程
    if (post_mode == 0)      // YOLOv5
        yolov5_pipeline();
    else if (post_mode == 1)  // FCOS
        fcos_pipeline();
    else if (post_mode == 2) // YOLOv3
        yolov3_pipeline();
    // ... 其他模式

    return 0;
}
```

#### 核心数据结构

**bpu_work 结构体:**
```cpp
struct bpu_work {
    std::chrono::high_resolution_clock::time_point start_time;  // 时间戳
    void* payload;  // 输出tensor数据
};
```

**YOLOv5Result 结构体:**
```cpp
struct YoloV5Result {
    float xmin, ymin, xmax, ymax;  // 边界框
    float score;                     // 置信度
    int class_id;                    // 类别ID
    std::string class_name;          // 类别名称
};
```

### 4.2 支持的模型类型

| 模式值 | 模型 | 输入尺寸 | 功能 | 模型文件 |
|--------|------|----------|------|----------|
| 0 | YOLOv5s | 672×672 | 目标检测 | yolov5s_672x672_nv12.bin |
| 1 | FCOS | 512×512 | 目标检测 | fcos_512x512_nv12.bin |
| 2 | YOLOv3 | 416×416 | 目标检测 | yolov3_darknet53_416x416_nv12.bin |
| 4 | YOLOv5x | 672×672 | 目标检测(大模型) | yolov5x_672x672_nv12.bin |
| 5 | SSD MobileNetV1 | 300×300 | 目标检测 | ssd_mobilenetv1_300x300_nv12.bin |
| 6 | CenterNet ResNet50 | 512×512 | 目标检测 | centernet_resnet101_512x512_nv12.bin |
| 7 | CenterNet ResNet101 | 512×512 | 目标检测 | centernet_resnet101_512x512_nv12.bin |
| 8 | MobileNetV1 | 224×224 | 图像分类 | mobilenetv1_224x224_nv12.bin |
| 9 | UNet | 1024×2048 | 语义分割 | mobilenet_unet_1024x2048_nv12.bin |

### 4.3 命令行参数

```bash
./sample [选项]

必选参数:
  -m <type>          模型类型 (0-9)
  -f <model_file>    模型文件路径

可选参数:
  -i <video_path>    视频文件路径 (用于FCOS模式)
  -h <height>        视频高度 (用于FCOS模式)
  -w <width>         视频宽度 (用于FCOS模式)
  -d                 启用调试模式，显示FPS
```

#### 参数说明

| 参数 | 说明 | 适用模式 |
|------|------|----------|
| -m 0 | YOLOv5 目标检测 | 所有 |
| -m 1 | FCOS 目标检测 | 需要视频文件 |
| -m 2 | YOLOv3 目标检测 | 所有 |
| -m 4 | YOLOv5x 目标检测 | 所有 |
| -m 5 | SSD 目标检测 | 所有 |
| -m 6 | CenterNet-ResNet50 | 所有 |
| -m 7 | CenterNet-ResNet101 | 所有 |
| -m 8 | MobileNetV1 分类 | 所有 |
| -m 9 | UNet 语义分割 | 所有 |
| -i | 输入视频路径 | 仅 FCOS |
| -h | 视频高度 | 仅 FCOS |
| -w | 视频宽度 | 仅 FCOS |
| -d | 调试模式 | 所有 |

---

## 5. 各模型使用详解

### 5.1 YOLOv5 目标检测

#### 功能说明
实时目标检测，支持80类COCO目标。

#### 使用命令
```bash
# 基本用法
./sample -m 0 -f /app/model/basic/yolov5s_672x672_nv12.bin

# 启用调试模式
./sample -m 0 -f /app/model/basic/yolov5s_672x672_nv12.bin -d
```

#### 核心参数 (代码中)
```cpp
// 输入尺寸
int width[2] = {672, disp_w};   // BPU输入和显示宽度
int height[2] = {672, disp_h}; // BPU输入和显示高度

// 帧缓冲大小
std::shared_ptr<char> buffer_672p(new char[FRAME_BUFFER_SIZE(672, 672)]);
```

#### 后处理关键参数
```cpp
// NMS阈值
float nms_threshold_ = 0.45;    // 非极大值抑制阈值

// Top-K参数
int nms_top_k_ = 20;           // 每类最多保留目标数
```

#### 可用模型文件
| 模型 | 文件名 | 说明 |
|------|--------|------|
| YOLOv5s | yolov5s_672x672_nv12.bin | 轻量级 |
| YOLOv5s v6 | yolov5s_v6_640x640_nv12.bin | 更新版本 |
| YOLOv5s v7 | yolov5s_v7_640x640_nv12.bin | 最新版本 |
| YOLOv5x | yolov5x_672x672_nv12.bin | 大模型，更高精度 |

#### 调整指南
1. **降低置信度阈值** (减少漏检):
   - 找到 `score_threshold` 相关代码
   - 从默认值 0.25 改为 0.15

2. **调整NMS阈值** (减少重叠检测):
   - 修改 `nms_threshold_` 从 0.45 到 0.5

3. **增加检测数量**:
   - 修改 `nms_top_k_` 从 20 到 50

---

### 5.2 FCOS 目标检测

#### 功能说明
基于视频文件的目标检测，适合离线视频分析。

#### 使用命令
```bash
./sample -m 1 \
    -f /app/model/basic/fcos_efficientnetb2_768x768_nv12.bin \
    -i /app/cdev_demo/bpu/src/bin/1080p_.h264 \
    -h 1080 -w 1920
```

#### 核心参数
```cpp
// 视频参数
std::string stream_file;  // 视频文件路径
int video_w = 1920;       // 视频宽度
int video_h = 1080;       // 视频高度

// FCOS 输入尺寸
int width[2] = {512, disp_w};
int height[2] = {512, disp_h};
```

#### 解码器配置
```cpp
// 初始化解码器
auto decoder = sp_initDecoderModule();

// 启动解码
ret = sp_start_decode(decoder,
                      stream_file.c_str(),
                      0,                    // channel
                      SP_ENCODER_H264,      // 编码格式
                      video_w, video_h);    // 分辨率
```

#### 调整指南
1. **支持其他视频格式**:
```bash
# H.265 编码
SP_ENCODER_H265

# 修改命令
./sample -m 1 -f model.bin -i video.265 -h 1080 -w 1920
```

2. **调整输入分辨率**:
```cpp
// 在 fcos_feed_bpu 函数中修改
ret = sp_vio_get_frame(vps, buffer_512p.get(), 512, 512, 500);
// 将 512 改为模型实际输入尺寸
```

---

### 5.3 YOLOv3 目标检测

#### 功能说明
YOLOv3 DarkNet53 模型目标检测。

#### 使用命令
```bash
./sample -m 2 -f /app/model/basic/yolov3_darknet53_416x416_nv12.bin
```

#### 核心参数
```cpp
// YOLOv3 输入尺寸
int width[2] = {416, disp_w};
int height[2] = {416, disp_h};

// YOLOv3 输出层数
int yolov3_output_nums_ = 3;  // 3个输出层
```

#### 可用模型文件
| 模型 | 文件名 |
|------|--------|
| YOLOv3 DarkNet53 | yolov3_darknet53_416x416_nv12.bin |
| YOLOv3 | yolov3_416x416_nv12.bin |

---

### 5.4 SSD MobileNetV1

#### 功能说明
SSD(Single Shot Detector)目标检测，轻量级高速。

#### 使用命令
```bash
./sample -m 5 -f /app/model/basic/ssd_mobilenetv1_300x300_nv12.bin
```

#### 核心参数
```cpp
// SSD 输入尺寸
int width[2] = {300, disp_w};
int height[2] = {300, disp_h};

// SSD 输出张量数
int ssd_output_nums_ = 12;  // 12个输出层
```

---

### 5.5 CenterNet

#### 功能说明
CenterNet 基于关键点的目标检测。

#### 使用命令
```bash
# ResNet50 版本
./sample -m 6 -f /app/model/basic/centernet_resnet101_512x512_nv12.bin

# ResNet101 版本 (RDK Ultra)
./sample -m 7 -f /app/model/basic/centernet_resnet101_512x512_nv12.bin
```

#### 核心参数
```cpp
// CenterNet 输入尺寸
int width[2] = {512, disp_w};
int height[2] = {512, disp_h};

// CenterNet 输出层数
int centernet_output_nums_ = 3;  // heatmap, size, offset
```

---

### 5.6 MobileNetV1 分类

#### 功能说明
图像分类模型，输出1000类ImageNet分类结果。

#### 使用命令
```bash
./sample -m 8 -f /app/model/basic/mobilenetv1_224x224_nv12.bin
```

#### 核心参数
```cpp
// MobileNetV1 输入尺寸
int width[2] = {224, disp_w};   // 实际代码使用300x300输入
int height[2] = {224, disp_h};

// 分类阈值
float classification_threshold_ = 0.3;

// 输出类别数
int num_classes_ = 1000;
```

#### 分类结果输出
```cpp
// 打印分类结果
printf("classification_result: \n");
for (size_t i = 0; i < results.size(); i++) {
    std::cout << results[i] << std::endl;  // 输出: 类别ID, 置信度, 类别名
}
```

---

### 5.7 UNet 语义分割

#### 功能说明
语义分割模型，输出像素级分割掩码。

#### 使用命令
```bash
./sample -m 9 -f /app/model/basic/mobilenet_unet_1024x2048_nv12.bin
```

#### 核心参数
```cpp
// UNet 输入尺寸
int width[2] = {1024, disp_w};   // 模型输入宽度
int height[2] = {2048, disp_h};  // 模型输入高度

// 分割类别数
int num_classes_ = 20;  // Cityscapes 19类 + 背景
```

#### 输出格式
```cpp
// 分割结果结构
struct Segmentation {
    std::vector<uint8_t> seg;     // 分割掩码
    int num_classes;              // 类别数
    int width;                    // 宽度
    int height;                   // 高度
};

// 打印输出
printf("unet_result: size:%ld, num_classes:%d, %dx%d\n",
       results.seg.size(), results.num_classes,
       results.width, results.height);
```

---

## 6. 后处理参数调整

### 6.1 置信度阈值

```cpp
// 修改位置: 各do_post函数中
// 例如 YOLOv5
yolov5_postprocess_info.score_threshold = 0.4;  // 默认0.3

// 调整建议:
score_threshold = 0.5   // 高精度要求，减少误检
score_threshold = 0.2   // 高召回要求，减少漏检
```

### 6.2 NMS阈值 (非极大值抑制)

```cpp
// 修改位置: 各do_post函数中
// NMS阈值用于合并重叠的检测框
nms_threshold_ = 0.45;  // 默认值

// 调整建议:
nms_threshold_ = 0.3   // 更多重叠框被抑制
nms_threshold_ = 0.6   // 更多重叠框被保留
```

### 6.3 Top-K参数

```cpp
// 每类最多保留的目标数
nms_top_k_ = 20;  // 默认值

// 调整建议:
nms_top_k_ = 10   // 只保留最可信的10个
nms_top_k_ = 50   // 保留更多目标
```

### 6.4 显示分辨率

```cpp
// 自动选择最匹配显示分辨率
for (int i = 0; i < 20; i++) {
    if(video_w >= disp_w_list[i] && video_h >= disp_h_list[i]) {
        disp_w = disp_w_list[i];
        disp_h = disp_h_list[i];
        break;
    }
}

// 手动指定
int disp_w = 1920;  // 强制1080P
int disp_h = 1080;
```

---

## 7. 多线程架构分析

### 7.1 线程模型

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  预处理线程      │     │   BPU推理线程    │     │  后处理线程      │
│  (feed_bpu)     │ ──> │  (BPU Forward)  │ ──> │  (do_post)      │
│                 │     │                 │     │                 │
│ 1. 获取摄像头帧  │     │ 1. 输入预处理    │     │ 1. 解析输出张量 │
│ 2. 图像缩放     │     │ 2. BPU推理调用   │     │ 2. NMS处理     │
│ 3. 送入BPU      │     │ 3. 结果入队      │     │ 3. 绘制框      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                                               │
         └───────────────── 环形缓冲 ─────────────────────┘
```

### 7.2 环形缓冲机制

```cpp
// 使用5组张量作为环形缓冲
std::vector<std::vector<hbDNNTensor>> output_tensors(5, ...);

int cur_ouput_buf_idx = 0;
while (!is_stop) {
    // 获取张量缓冲
    bpu_handle->output_tensor = output_tensors[cur_ouput_buf_idx].data();

    // BPU推理
    sp_bpu_start_predict(bpu_handle, buffer_672p.get());

    // 工作入队
    yolov5_work_deque.push_back(yolov5_work);

    // 环形索引更新
    cur_ouput_buf_idx++;
    cur_ouput_buf_idx %= 5;  // 模5循环
}
```

### 7.3 线程同步

```cpp
// 使用互斥锁保护队列
static std::mutex yolo_mtx;

// 使用条件变量实现同步
static std::condition_variable yolo_cv;

// 标志位
static std::atomic_bool yolo_finish;
static std::atomic_bool is_stop;
```

---

## 8. 模型文件说明

### 8.1 模型文件位置
```
/app/model/basic/
├── yolov5s_672x672_nv12.bin          # YOLOv5 轻量级
├── yolov5s_v6_640x640_nv12.bin       # YOLOv5 v6
├── yolov5s_v7_640x640_nv12.bin       # YOLOv5 v7
├── yolov5x_672x672_nv12.bin          # YOLOv5 大模型
├── yolov3_darknet53_416x416_nv12.bin # YOLOv3
├── fcos_512x512_nv12.bin             # FCOS
├── fcos_efficientnetb2_768x768_nv12.bin # FCOS 高分辨率
├── ssd_mobilenetv1_300x300_nv12.bin  # SSD
├── centernet_resnet101_512x512_nv12.bin # CenterNet
├── mobilenetv1_224x224_nv12.bin       # MobileNet 分类
├── mobilenet_unet_1024x2048_nv12.bin # UNet 分割
└── ...
```

### 8.2 模型输入格式
- 所有模型输入格式为 **NV12** (YUV420)
- 内存布局: Y平面 + UV交错平面

### 8.3 模型加载

```cpp
// 通过BPU模块加载模型
bpu_module *bpu_obj = sp_init_bpu_module(model_file.c_str());

// 获取模型信息
int tensor_count = sp_init_bpu_tensors(bpu_handle, output_tensors[0].data());
```

---

## 9. 常见问题解决

### 9.1 编译错误

**问题**: `fatal error: hb_dnn_test.hpp: No such file or directory`

**解决**:
```bash
# 检查头文件路径
ls /app/cdev_demo/bpu/include/

# 确保在正确目录编译
cd /app/cdev_demo/bpu/src
make clean && make
```

### 9.2 运行时错误

**问题**: `display error!` 或 `BAD ATTR`

**解决**:
```bash
# 检查输入分辨率是否匹配
# 确保视频分辨率与模型输入匹配

# 对于FCOS模式
./sample -m 1 -f model.bin -i video.h264 -h 1080 -w 1920
#                      ^^^^^^^ 确保分辨率正确
```

### 9.3 模型加载失败

**问题**: `prepare model output tensor failed`

**解决**:
```bash
# 检查模型文件是否存在
ls -la /app/model/basic/yolov5s_672x672_nv12.bin

# 检查模型文件权限
chmod 644 /app/model/basic/*.bin
```

### 9.4 摄像头问题

**问题**: 程序启动失败或无图像

**解决**:
```bash
# 确保摄像头已连接
ls /dev/video*

# 确保摄像头已开启电源
# 检查摄像头配置
```

---

## 附录: 完整命令参考

```bash
# 1. YOLOv5 目标检测
./sample -m 0 -f /app/model/basic/yolov5s_672x672_nv12.bin

# 2. FCOS 目标检测 (需要视频)
./sample -m 1 -f /app/model/basic/fcos_512x512_nv12.bin \
    -i /app/cdev_demo/bpu/src/bin/1080p_.h264 -h 1080 -w 1920

# 3. YOLOv3 目标检测
./sample -m 2 -f /app/model/basic/yolov3_darknet53_416x416_nv12.bin

# 4. YOLOv5x 大模型检测
./sample -m 4 -f /app/model/basic/yolov5x_672x672_nv12.bin

# 5. SSD 目标检测
./sample -m 5 -f /app/model/basic/ssd_mobilenetv1_300x300_nv12.bin

# 6. CenterNet ResNet50
./sample -m 6 -f /app/model/basic/centernet_resnet101_512x512_nv12.bin

# 7. CenterNet ResNet101 (RDK Ultra)
./sample -m 7 -f /app/model/basic/centernet_resnet101_512x512_nv12.bin

# 8. MobileNetV1 分类
./sample -m 8 -f /app/model/basic/mobilenetv1_224x224_nv12.bin

# 9. UNet 语义分割
./sample -m 9 -f /app/model/basic/mobilenet_unet_1024x2048_nv12.bin

# 调试模式 (显示FPS)
./sample -m 0 -f /app/model/basic/yolov5s_672x672_nv12.bin -d
```

---

**文档版本**: 1.0
**更新日期**: 2026-04-20
**适用平台**: 地平线 RDK X3/X5 开发板
