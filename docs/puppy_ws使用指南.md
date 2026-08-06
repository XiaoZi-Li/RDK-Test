# puppy_ws 模块详细使用指南

## 目录
1. [模块概述](#1-模块概述)
2. [系统架构](#2-系统架构)
3. [目录结构](#3-目录结构)
4. [编译与部署](#4-编译与部署)
5. [核心节点详解](#5-核心节点详解)
   - [perception_node 视觉感知](#51-perception_node-视觉感知)
   - [decision_node 决策仲裁](#52-decision_node-决策仲裁)
   - [ros_udp_bridge UDP转发](#53-ros_udp_bridge-udp转发)
   - [gesture_adapter_node 手势适配](#54-gesture_adapter_node-手势适配)
   - [voice_control_node 语音控制](#55-voice_control_node-语音控制)
   - [imu_node_ros2 IMU发布](#56-imu_node_ros2-imu发布)
6. [启动文件详解](#6-启动文件详解)
7. [话题与服务](#7-话题与服务)
8. [参数调整指南](#8-参数调整指南)
9. [工具脚本](#9-工具脚本)
10. [常见问题解决](#10-常见问题解决)

---

## 1. 模块概述

### 1.1 功能说明
puppy_ws 是基于 ROS2 Humble 的四足机器狗（PuppyPi）控制系统，集成了视觉感知、目标检测、人体跟随、手势识别、语音控制、IMU传感等功能。

### 1.2 核心能力
| 功能 | 说明 |
|------|------|
| 目标检测 | YOLOv5 实时目标检测 |
| 人体跟随 | 基于面积和位置的跟随控制 |
| 手势识别 | 支持手势控制（手势定义值1-5） |
| 语音控制 | I2C语音模块和USB麦克风 |
| IMU感知 | 陀螺仪和加速度计数据 |
| LLM对话 | Qwen2.5-0.5B 大模型对话 |

### 1.3 硬件平台
| 组件 | 型号 |
|------|------|
| 主控 | 地平线 RDK X5 |
| 摄像头 | MIPI F37 (960×544) |
| IMU | BMI08X/ICM42688 |
| 语音模块 | I2C 0x79@bus5 |

---

## 2. 系统架构

### 2.1 数据流图
```
┌──────────────────────────────────────────────────────────────────┐
│                         硬件输入层                                │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐       │
│   │ MIPI摄像头   │     │ I2C语音模块  │     │ USB麦克风    │       │
│   │ (F37)      │     │ (0x79)     │     │ (Vosk)     │       │
│   └──────┬──────┘     └──────┬──────┘     └──────┬──────┘       │
│          │                   │                   │              │
│          ▼                   ▼                   ▼              │
│   ┌──────────────────────────────────────────────────────┐       │
│   │                   ROS2 消息总线                       │       │
│   │  /hbmem_img  /voice/result  /asr/text  /imu_raw     │       │
│   └──────────────────────────────────────────────────────┘       │
│                              │                                    │
├──────────────────────────────┼──────────────────────────────────┤
│                              ▼                                    │
│                    ┌─────────────────┐                           │
│                    │ perception_node  │ ← YOLOv5 目标检测         │
│                    │ (BPU 推理)      │                           │
│                    └────────┬────────┘                           │
│                             │ /perception/result_json            │
│                             ▼                                    │
│                    ┌─────────────────┐                           │
│                    │ decision_node   │ ← 决策仲裁核心             │
│                    │ (最核心)        │                           │
│                    └────────┬────────┘                           │
│                             │ /puppy_action                      │
│          ┌──────────────────┼──────────────────┐                │
│          ▼                  ▼                  ▼                │
│   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐           │
│   │ros_udp_bridge│   │debug_preview│   │chat_llm_bridge│         │
│   │(UDP转发)    │   │(调试显示)   │   │(LLM对话)    │           │
│   └──────┬──────┘   └─────────────┘   └─────────────┘           │
│          │                                                       │
│          ▼                                                       │
│   ┌─────────────┐                                               │
│   │ 机器狗底层   │ ← 执行动作 (站立/行走/坐下/转向)             │
│   │ SDK         │                                               │
│   └─────────────┘                                               │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 手势定义
| 手势值 | 手势 | 对应动作 |
|--------|------|----------|
| 1.0 | 手掌张开 | follow_on (开启跟随) |
| 2.0 | 握拳 | follow_off (关闭跟随) |
| 3.0 | OK手势 | stop (停止) |
| 4.0 | 点赞 | sit (坐下) |
| 5.0 | 竖食指 | stand (站立) |

### 2.3 跟随控制逻辑
```
目标检测结果 → 计算目标面积占比 → 判断距离
                ↓
         面积 > 0.42 → stop (太近停止)
         面积 < 0.10 → walk (太远行走)
         其他 → 根据中心位置转向
                ↓
           偏左 → turn_left
           居中 → walk
           偏右 → turn_right
```

---

## 3. 目录结构

```
puppy_ws/
├── src/
│   └── puppy_brain/
│       ├── launch/                      # 启动文件
│       │   ├── full_system.launch.py    # 完整系统启动
│       │   ├── follow_only.launch.py    # 仅跟随模式
│       │   ├── gesture_only.launch.py    # 仅手势控制
│       │   ├── gesture_control_test.launch.py
│       │   └── gesture_official_test.launch.py
│       │
│       ├── puppy_brain/                 # 核心节点
│       │   ├── __init__.py
│       │   ├── perception_node.py       # 视觉感知节点
│       │   ├── decision_node.py          # 决策仲裁节点
│       │   ├── ros_udp_bridge.py        # UDP转发节点
│       │   ├── gesture_adapter_node.py  # 手势适配节点
│       │   ├── voice_control_node.py    # 语音控制节点
│       │   ├── imu_node_ros2.py         # IMU发布节点
│       │   ├── debug_preview_node.py    # 调试预览节点
│       │   ├── chat_llm_bridge_node.py # LLM对话桥
│       │   ├── intent_router_node.py    # 意图路由节点
│       │   └── usb_asr_text_node.py    # USB语音识别
│       │
│       ├── resource/
│       │   └── puppy_brain              # 资源标识
│       │
│       ├── test/                        # 测试文件
│       │   ├── test_copyright.py
│       │   ├── test_flake8.py
│       │   └── test_pep257.py
│       │
│       ├── package.xml                  # 包描述
│       ├── setup.py                    # 安装配置
│       └── setup.cfg                   # setuptools配置
│
├── install/                             # colcon build输出
├── log/                                 # 日志目录
├── build/                               # 编译目录
├── models/                              # LLM模型
│   ├── Qwen2.5-0.5B-Instruct-Q4_0.gguf
│   ├── vosk-model-small-cn-0.22/
│   └── sherpa_kws/
│
├── docs/                               # 文档
│   └── PuppyPi_从零上手极详细指南.md
│
└── tools/                              # 工具脚本
    ├── asr_wakeup_loop_router.py
    ├── asr_wakeup_once_router.py
    ├── sherpa_kws_mic_test.py
    └── usb_mic_check.sh
```

---

## 4. 编译与部署

### 4.1 前置条件检查
```bash
# 1. 确认平台
uname -m
# 应输出: aarch64

# 2. 确认ROS2 Humble环境
ls /opt/tros/humble/
# 应有: setup.bash, lib/, share/

# 3. 确认TROS环境
echo $ROS_DISTRO
# 应输出: humble
```

### 4.2 编译步骤
```bash
# 进入工作空间
cd /app/puppy_ws

# 加载ROS2环境
source /opt/tros/humble/setup.bash

# 编译
colcon build

# 加载本地环境
source install/setup.bash
```

### 4.3 快速启动
```bash
# 完整系统 (包含所有功能)
ros2 launch puppy_brain full_system.launch.py

# 仅跟随模式 (只开启视觉跟随)
ros2 launch puppy_brain follow_only.launch.py

# 仅手势控制 (只开启手势识别)
ros2 launch puppy_brain gesture_only.launch.py
```

### 4.4 环境变量说明
```bash
# ROS2 Humble
source /opt/tros/humble/setup.bash

# 本地工作空间
source /app/puppy_ws/install/setup.bash

# Python包路径 (如使用hobot_dnn_rdkx5)
export PYTHONPATH=$PYTHONPATH:/usr/lib/python3/dist-packages
```

---

## 5. 核心节点详解

### 5.1 perception_node 视觉感知

**文件**: perception_node.py

**功能**: 接收摄像头图像，进行 YOLOv5 目标检测，发布检测结果。

#### 订阅话题
| 话题 | 类型 | 来源 |
|------|------|------|
| /image | CompressedImage | hobot_codec |

#### 发布话题
| 话题 | 类型 | 内容 |
|------|------|------|
| /perception/result_json | String | 检测结果JSON |

#### 检测结果格式
```json
{
  "detections": [
    {
      "name": "person",      // 类别名
      "bbox": [x1, y1, x2, y2],  // 边界框
      "score": 0.92          // 置信度
    }
  ]
}
```

#### 核心代码结构
```python
class PerceptionNode(Node):
    def __init__(self):
        # 1. 加载模型
        self.models = dnn.load(model_path)

        # 2. 订阅图像话题
        self.image_sub = self.create_subscription(
            CompressedImage,
            '/image',
            self.image_callback,
            10
        )

        # 3. 发布检测结果
        self.result_pub = self.create_publisher(
            String,
            '/perception/result_json',
            10
        )

    def image_callback(self, msg):
        # 1. 解码JPEG
        img = self.decode_image(msg)

        # 2. 预处理 -> NV12
        nv12_data = self.bgr2nv12(img)

        # 3. BPU推理
        outputs = self.models[0].forward(nv12_data)

        # 4. 后处理
        results = self.post_process(outputs)

        # 5. 发布结果
        self.result_pub.publish(json.dumps(results))
```

#### 参数说明
```python
{
    'model_path': '/app/model/basic/yolov5s_672x672_nv12.bin',
    'score_threshold': 0.25,       # 置信度阈值
    'nms_threshold': 0.45,        # NMS阈值
    'nms_top_k': 20,              # Top-K
    'input_width': 672,           # 模型输入宽度
    'input_height': 672,          # 模型输入高度
    'orig_width': 960,            # 原始图像宽度
    'orig_height': 544,           # 原始图像高度
    'image_topic': '/image',      # 图像话题
    'log_interval_sec': 5.0,      # 日志间隔
}
```

---

### 5.2 decision_node 决策仲裁

**文件**: decision_node.py

**功能**: 接收感知、手势、语音结果，进行决策仲裁，输出控制指令。**这是系统的核心节点**。

#### 订阅话题
| 话题 | 类型 | 来源 |
|------|------|------|
| /perception/result_json | String | perception_node |
| /gesture/result_json | String | gesture_adapter_node |
| /voice/result_json | String | voice_control_node |

#### 发布话题
| 话题 | 类型 | 内容 |
|------|------|------|
| /puppy_action | String | 控制指令JSON |

#### 控制指令格式
```json
{
  "action": "walk",           // 动作: walk/turn_left/turn_right/stop/sit/stand
  "source": "follow",          // 来源: follow/gesture/voice
  "timestamp": 1234567890.123  // 时间戳
}
```

#### 核心逻辑

**1. 手势处理:**
```python
def gesture_callback(self, msg):
    gesture_value = float(payload['gesture_value'])

    if gesture_value == 1.0:  # 手掌张开
        self.follow_enabled = True
    elif gesture_value == 2.0:  # 握拳
        self.follow_enabled = False
    elif gesture_value == 3.0:  # OK手势
        return 'stop'
    elif gesture_value == 4.0:  # 点赞
        return 'sit'
    elif gesture_value == 5.0:  # 竖食指
        return 'stand'
```

**2. 跟随决策:**
```python
def decide_follow_action(self, detections):
    # 找最大的人体目标
    for det in detections:
        if det['name'] != 'person':
            continue

        bbox = det['bbox']
        area_ratio = (bbox[2]-bbox[0]) * (bbox[3]-bbox[1]) / (image_width * image_height)
        x_center = (bbox[0] + bbox[2]) / 2 / image_width

        # 距离判断
        if area_ratio > self.follow_area_near_stop:  # 太近
            return 'stop'
        elif area_ratio < self.follow_area_far_walk:  # 太远
            return 'walk'

        # 方向判断
        if x_center < self.turn_left_ratio:
            return 'turn_left'
        elif x_center > self.turn_right_ratio:
            return 'turn_right'
        else:
            return 'walk'
```

#### 参数说明
```python
# ========== 图像参数 ==========
'image_width': 960.0,           # 图像宽度
'image_height': 544.0,          # 图像高度

# ========== 跟随距离阈值 ==========
'follow_area_near_stop': 0.42,  # 目标面积>42%则停止
'follow_area_far_walk': 0.10,   # 目标面积<10%则行走
'min_valid_area_ratio': 0.015,  # 最小有效目标比例

# ========== 转向参数 ==========
'center_ratio': 0.50,           # 中心位置比例
'turn_deadband_ratio': 0.09,    # 转向死区
'max_turn_error_ratio': 0.28,    # 最大转向误差
'turn_gain': 0.85,              # 转向增益

# ========== 速度参数 ==========
'forward_min': 0.0,             # 前进最小值
'forward_max': 0.95,            # 前进最大值

# ========== 时间参数 ==========
'ghost_memory_time': 0.30,      # 目标消失记忆时间
'publish_repeat_sec': 0.15,     # 发布重复间隔

# ========== 手势参数 ==========
'gesture_hold_sec': 0.8,        # 手势保持时间
'gesture_action_lock_sec': 2.5, # 手势锁定时间 (sit/stand)
'gesture_stop_lock_sec': 1.0,   # stop手势锁定时间

# ========== 跟随开关 ==========
'follow_default_enabled': True,  # 默认开启跟随

# ========== 平滑参数 ==========
'control_smooth_alpha': 0.28,   # 平滑系数 (0-1)

# ========== 零点阈值 ==========
'turn_zero_threshold': 0.05,    # 转向零点阈值
'forward_zero_threshold': 0.05, # 前进零点阈值
```

---

### 5.3 ros_udp_bridge UDP转发

**文件**: ros_udp_bridge.py

**功能**: 将ROS话题转换为UDP数据报，发送给机器狗底层SDK。

#### 订阅话题
| 话题 | 类型 |
|------|------|
| /puppy_action | String |
| /ros_robot_controller/imu_raw | Imu |

#### UDP配置
```python
{
    'udp_ip': '127.0.0.1',       # UDP目标IP
    'udp_port': 5005,            # 控制端口
    'imu_udp_ip': '127.0.0.1',   # IMU目标IP
    'imu_udp_port': 5006,       # IMU端口
}
```

#### 发送格式
```python
# 动作控制
{"action": "walk", "source": "follow"}

# IMU数据
{"accel_x": 0.1, "accel_y": -0.2, "accel_z": 9.8,
 "gyro_x": 0.01, "gyro_y": -0.02, "gyro_z": 0.0}
```

---

### 5.4 gesture_adapter_node 手势适配

**文件**: gesture_adapter_node.py

**功能**: 将TROS手势检测结果转换为统一格式。

#### 订阅话题
| 话题 | 类型 | 来源 |
|------|------|------|
| /hobot_hand_gesture_detection | PerceptionTargets | hand_gesture_detection |

#### 发布话题
| 话题 | 类型 | 内容 |
|------|------|------|
| /gesture/result_json | String | 手势结果 |

#### 手势映射
```python
# TROS手势ID -> 标准手势值
TROS_GESTURE_ID = {
    1: 1.0,   # 伸手 -> follow_on
    2: 2.0,   # 握拳 -> follow_off
    3: 3.0,   # OK -> stop
    4: 4.0,   # 点赞 -> sit
    5: 5.0,   # 食指 -> stand
}
```

---

### 5.5 voice_control_node 语音控制

**文件**: voice_control_node.py

**功能**: 通过I2C接口读取语音控制模块的指令。

#### 硬件配置
```python
{
    'i2c_bus': 5,           # I2C总线号
    'i2c_addr': 0x79,       # I2C设备地址
    'mode': 1,              # 工作模式
    'poll_interval': 0.10,  # 轮询间隔(秒)
    'cooldown_sec': 1.5,    # 指令冷却时间(秒)
}
```

#### 支持指令
| 指令 | 动作 |
|------|------|
| "前进" / "forward" | walk |
| "后退" / "backward" | 后退 |
| "左转" / "left" | turn_left |
| "右转" / "right" | turn_right |
| "停止" / "stop" | stop |
| "站立" / "stand" | stand |
| "坐下" / "sit" | sit |

---

### 5.6 imu_node_ros2 IMU发布

**文件**: imu_node_ros2.py

**功能**: 读取IMU传感器数据并发布。

#### 发布话题
| 话题 | 类型 | 频率 |
|------|------|------|
| /ros_robot_controller/imu_raw | Imu | 50Hz |

#### IMU消息格式
```python
Imu:
    header:
        stamp: now()
        frame_id: "imu_link"
    orientation: [x, y, z, w]      # 四元数
    angular_velocity: [x, y, z]    # 陀螺仪 (rad/s)
    linear_acceleration: [x, y, z] # 加速度 (m/s^2)
```

#### 参数说明
```python
{
    'topic_name': '/ros_robot_controller/imu_raw',
    'publish_hz': 50.0,            # 发布频率
}
```

---

## 6. 启动文件详解

### 6.1 full_system.launch.py 完整系统启动

**路径**: launch/full_system.launch.py

这是最常用的启动文件，包含了所有功能模块。

#### 启动的节点
```python
LaunchDescription([
    # 1. 环境变量
    SetEnvironmentVariable('LANG', 'C.UTF-8'),
    SetEnvironmentVariable('LC_ALL', 'C.UTF-8'),

    # 2. 摄像头和编解码
    Node(package='mipi_cam', executable='mipi_cam'),           # MIPI摄像头
    Node(package='hobot_codec', executable='hobot_codec_republish'),  # 图像编码

    # 3. TROS官方AI检测 (手势用)
    Node(package='mono2d_body_detection', executable='mono2d_body_detection'),
    Node(package='hand_lmk_detection', executable='hand_lmk_detection'),
    Node(package='hand_gesture_detection', executable='hand_gesture_detection'),

    # 4. puppy_brain自定义节点
    Node(package='puppy_brain', executable='gesture_adapter_node'),
    Node(package='puppy_brain', executable='perception_node'),
    Node(package='puppy_brain', executable='voice_control_node'),
    Node(package='puppy_brain', executable='decision_node'),
    Node(package='puppy_brain', executable='ros_udp_bridge'),
    Node(package='puppy_brain', executable='imu_node_ros2'),

    # 5. LLM对话 (可选)
    llama_node,          # LLM推理节点
    chat_llm_bridge_node, # 对话桥接

    # 6. Web调试 (可选)
    websocket_node,      # WebSocket
])
```

### 6.2 follow_only.launch.py 仅跟随模式

只开启视觉跟随功能，不包含手势和语音。

### 6.3 gesture_only.launch.py 仅手势控制

只开启手势识别和跟随控制。

---

## 7. 话题与服务

### 7.1 完整话题列表

| 话题名 | 消息类型 | 发布者 | 订阅者 | 说明 |
|--------|----------|--------|--------|------|
| /hbmem_img | hbm_img | mipi_cam | hobot_codec | 摄像头原始帧 |
| /image | CompressedImage | hobot_codec | perception_node | JPEG压缩图像 |
| /hobot_mono2d_body_detection | PerceptionTargets | mono2d_body | hand_lmk | 人体检测 |
| /hobot_hand_lmk_detection | PerceptionTargets | hand_lmk | hand_gesture | 手部关键点 |
| /hobot_hand_gesture_detection | PerceptionTargets | hand_gesture | gesture_adapter | 手势分类 |
| /gesture/result_json | String | gesture_adapter | decision_node | 手势结果 |
| /perception/result_json | String | perception_node | decision_node | 检测结果 |
| /voice/result_json | String | voice_control | decision_node | 语音指令 |
| /asr/text | String | usb_asr_text | intent_router | 语音识别文本 |
| /chat/input_text | String | intent_router | chat_llm_bridge | 对话输入 |
| /prompt_text | String | chat_llm_bridge | llama_cpp | LLM输入 |
| /tts_text | String | llama_cpp | chat_llm_bridge | LLM输出 |
| /chat/response_text | String | chat_llm_bridge | - | 对话回复 |
| /puppy_action | String | decision_node | ros_udp_bridge | 控制指令 |
| /ros_robot_controller/imu_raw | Imu | imu_node_ros2 | ros_udp_bridge | IMU数据 |

### 7.2 常用ROS2命令
```bash
# 查看话题列表
ros2 topic list

# 查看特定话题
ros2 topic echo /perception/result_json

# 查看节点列表
ros2 node list

# 查看节点信息
ros2 node info /decision_node

# 手动发布动作测试
ros2 topic pub /puppy_action std_msgs/String "data: '{\"action\":\"stand\"}'"

# 手动发布手势测试
ros2 topic pub /gesture/result_json std_msgs/String "data: '{\"gesture_value\": 4.0}'"
```

---

## 8. 参数调整指南

### 8.1 perception_node 参数

```python
# 模型路径
'model_path': '/app/model/basic/yolov5s_672x672_nv12.bin'

# 置信度阈值 (越小检测越灵敏，但误检增加)
'score_threshold': 0.25,  # 范围: 0.1-0.9

# NMS阈值 (越小抑制越多)
'nms_threshold': 0.45,    # 范围: 0.3-0.7

# Top-K (每类最多检测数)
'nms_top_k': 20,         # 范围: 10-100
```

**调整建议:**
- 检测**太远/太小目标** → 减小 score_threshold 到 0.15
- **误检太多** → 增大 score_threshold 到 0.35
- **重叠框太多** → 减小 nms_threshold 到 0.35

### 8.2 decision_node 参数

#### 距离控制参数
```python
# 目标面积占比计算: bbox面积 / 图像面积
# 图像面积 = 960 * 544 = 522240

# 太近停止阈值 (建议范围: 0.35-0.50)
'follow_area_near_stop': 0.42

# 太远行走阈值 (建议范围: 0.08-0.15)
'follow_area_far_walk': 0.10
```

**调整示例:**
```python
# 如果机器人离目标太近不停
'follow_area_near_stop': 0.38  # 减小阈值

# 如果机器人离目标太远不走
'follow_area_far_walk': 0.15  # 增大阈值
```

#### 转向控制参数
```python
# 中心区域比例
'center_ratio': 0.50

# 转向死区 (在center_ratio ± deadband内为直行)
'turn_deadband_ratio': 0.09

# 例如:
# center_ratio = 0.50, deadband = 0.09
# 目标位置 < 0.41 → 左转
# 目标位置 > 0.59 → 右转
# 目标位置 0.41-0.59 → 直行
```

**调整示例:**
```python
# 如果转向太频繁
'turn_deadband_ratio': 0.12  # 增大死区

# 如果转向太迟钝
'turn_deadband_ratio': 0.06  # 减小死区
```

#### 平滑参数
```python
# 控制平滑系数 (0-1，越大响应越快但抖动)
'control_smooth_alpha': 0.28

# 调整建议:
# 动作抖动 → 减小到 0.15
# 响应太慢 → 增大到 0.45
```

#### 锁定时间参数
```python
# sit/stand手势的锁定时间
'gesture_action_lock_sec': 2.5

# stop手势的锁定时间
'gesture_stop_lock_sec': 1.0

# 手势结果保持时间
'gesture_hold_sec': 0.8
```

### 8.3 ros_udp_bridge 参数

```python
{
    'udp_ip': '127.0.0.1',       # 底层SDK的IP
    'udp_port': 5005,            # 控制命令端口
    'imu_udp_ip': '127.0.0.1',   # IMU数据接收IP
    'imu_udp_port': 5006,        # IMU数据端口
}
```

### 8.4 摄像头参数

```python
# mipi_cam参数
{
    'out_format': 'nv12',        # 输出格式
    'io_method': 'shared_mem',   # 共享内存方式
    'video_device': 'F37',       # 传感器型号
    'image_width': 960,          # 输出宽度
    'image_height': 544,         # 输出高度
}

# hobot_codec参数
{
    'sub_topic': '/hbmem_img',   # 输入话题
    'pub_topic': '/image',       # 输出话题
    'in_format': 'nv12',        # 输入格式
    'out_format': 'jpeg',       # 输出格式
    'jpg_quality': 60.0,         # JPEG质量 (10-100)
}
```

---

## 9. 工具脚本

### 9.1 asr_wakeup_loop_router.py
语音唤醒循环路由脚本。

### 9.2 sherpa_kws_mic_test.py
KWS(关键词识别)麦克风测试。

### 9.3 usb_mic_check.sh
USB麦克风检测脚本。

### 9.4 vosk_wav_test.py
Vosk语音识别WAV文件测试。

---

## 10. 常见问题解决

### 10.1 编译错误

**问题**: `colcon build` 失败

**解决**:
```bash
# 清理后重新编译
cd /app/puppy_ws
rm -rf build install log
source /opt/tros/humble/setup.bash
colcon build
```

### 10.2 节点启动失败

**问题**: `package 'puppy_brain' not found`

**解决**:
```bash
# 确认环境变量
source /opt/tros/humble/setup.bash
source /app/puppy_ws/install/setup.bash

# 检查包是否被发现
ros2 pkg list | grep puppy
```

### 10.3 摄像头无图像

**问题**: /image 话题无数据

**解决**:
```bash
# 检查摄像头设备
ls -la /dev/video*

# 检查mipi_cam节点
ros2 node list
ros2 topic echo /hbmem_img

# 重启摄像头
# 检查F37传感器是否正确连接
```

### 10.4 目标检测无输出

**问题**: /perception/result_json 无数据

**解决**:
```bash
# 检查模型文件
ls -la /app/model/basic/yolov5s_672x672_nv12.bin

# 检查perception_node日志
ros2 run puppy_brain perception_node

# 确认/image话题有数据
ros2 topic echo /image
```

### 10.5 跟随无响应

**问题**: decision_node 收到检测但不输出动作

**解决**:
```bash
# 检查decision_node日志
ros2 run puppy_brain decision_node

# 测试手动发布动作
ros2 topic pub /puppy_action std_msgs/String "data: '{\"action\":\"walk\"}'"

# 检查跟随是否开启
# 发送手势开启跟随
ros2 topic pub /gesture/result_json std_msgs/String "data: '{\"gesture_value\": 1.0}'"
```

### 10.6 UDP转发无响应

**问题**: 底层机器狗不执行动作

**解决**:
```bash
# 检查UDP端口
netstat -anp | grep 5005

# 确认底层SDK正在监听
# 检查ros_udp_bridge日志
ros2 run puppy_brain ros_udp_bridge

# 测试UDP连接
nc -u 127.0.0.1 5005
```

---

## 附录: 动作指令参考

```bash
# 站立
ros2 topic pub /puppy_action std_msgs/String "data: '{\"action\":\"stand\",\"source\":\"test\"}'"

# 坐下
ros2 topic pub /puppy_action std_msgs/String "data: '{\"action\":\"sit\",\"source\":\"test\"}'"

# 行走
ros2 topic pub /puppy_action std_msgs/String "data: '{\"action\":\"walk\",\"source\":\"test\"}'"

# 停止
ros2 topic pub /puppy_action std_msgs/String "data: '{\"action\":\"stop\",\"source\":\"test\"}'"

# 左转
ros2 topic pub /puppy_action std_msgs/String "data: '{\"action\":\"turn_left\",\"source\":\"test\"}'"

# 右转
ros2 topic pub /puppy_action std_msgs/String "data: '{\"action\":\"turn_right\",\"source\":\"test\"}'"
```

---

## 附录: 参数速查表

| 参数 | 文件位置 | 默认值 | 调整范围 | 作用 |
|------|----------|--------|----------|------|
| score_threshold | full_system.launch.py | 0.25 | 0.1-0.5 | 检测灵敏度 |
| nms_threshold | full_system.launch.py | 0.45 | 0.3-0.7 | 重叠抑制 |
| follow_area_near_stop | full_system.launch.py | 0.42 | 0.35-0.50 | 停止距离 |
| follow_area_far_walk | full_system.launch.py | 0.10 | 0.08-0.15 | 行走距离 |
| turn_deadband_ratio | full_system.launch.py | 0.09 | 0.05-0.15 | 转向死区 |
| control_smooth_alpha | full_system.launch.py | 0.28 | 0.15-0.50 | 平滑度 |
| gesture_action_lock_sec | full_system.launch.py | 2.5 | 1.0-5.0 | 手势锁定 |
| follow_default_enabled | full_system.launch.py | True | True/False | 默认跟随 |

---

**文档版本**: 1.0
**更新日期**: 2026-04-20
**适用平台**: 地平线 RDK X5 + PuppyPi 机器狗
**ROS2版本**: Humble
