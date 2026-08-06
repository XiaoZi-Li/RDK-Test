# MEMORY.md — 长期项目记忆

## PuppyPi 机器人项目（/app/app 工程目录）

### 项目架构概览
整个工程是运行在 RDK X5（地平线）上的四足机器人智能控制系统，分为以下几个层次：

**感知层**：MIPI摄像头(F37, 960x544) → hobot_codec(JPEG编码) → perception_node(YOLOv5s BPU推理)
**手势链**：mipi_cam → mono2d_body_detection → hand_lmk_detection → hand_gesture_detection → gesture_adapter_node
**语音链1（I2C）**：硬件语音模块(I2C总线5, 地址0x79) → voice_control_node → /voice/result_json
**语音链2（USB）**：USB麦克风 → usb_asr_text_node(Vosk) → intent_router_node → /voice/result_json或/chat/input_text
**决策层**：decision_node（汇聚感知+手势+语音，计算跟随控制量）
**执行层**：ros_udp_bridge(UDP:5005) → 幻尔SDK底层
**LLM对话**：intent_router_node → chat_llm_bridge_node → hobot_llamacpp(Qwen2.5-0.5B) → /chat/response_text
**IMU**：imu_node_ros2 → ros_udp_bridge(UDP:5006)

### 核心文件路径
- launch入口: `/app/puppy_ws/src/puppy_brain/launch/full_system.launch.py`
- 感知节点: `/app/puppy_ws/src/puppy_brain/puppy_brain/perception_node.py`
- 决策节点: `/app/puppy_ws/src/puppy_brain/puppy_brain/decision_node.py`
- BPU模型: `/app/model/basic/yolov5s_672x672_nv12.bin`
- LLM模型: `/app/puppy_ws/models/Qwen2.5-0.5B-Instruct-Q4_0.gguf`
- 语音模型: `/app/puppy_ws/models/vosk-model-small-cn-0.22/`
- 底层SDK: `/app/pydev_demo/puppypi_control/`

### 关键参数速查（decision_node）
- `follow_area_near_stop=0.42`：人占画面42%以上时刹车
- `follow_area_far_walk=0.10`：人占画面10%以下时全速前进
- `turn_deadband_ratio=0.09`：9%范围内不转向（防抖）
- `control_smooth_alpha=0.28`：运动平滑系数（低通滤波）
- `voice_action_lock_sec=2.5`：语音指令执行后锁定2.5秒
- 手势映射: 1=follow_on, 2=follow_off, 3=stop, 4=sit, 5=stand

### 优先级规则
语音指令 > 手势指令 > 视觉跟随（三路汇聚到decision_node仲裁）

### 模型库
`/app/model/basic/` 下有34个BPU预编译模型（YOLOv5/8/10/11/12, FCOS, CenterNet, SSD, 分类模型, 分割模型等）

### 编译运行方法
```bash
cd /app/puppy_ws
source /opt/tros/humble/setup.bash
colcon build --packages-select puppy_brain
source /app/puppy_ws/install/setup.bash
ros2 launch puppy_brain full_system.launch.py
```

### 代码完整分析完成时间
2026-04-18，分两部分完整输出了所有代码文件的功能说明、参数含义和使用方法
