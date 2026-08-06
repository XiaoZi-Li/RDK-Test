# YOLOv8 BPU Inference Sample

## 概述

这是基于官方YOLOv5示例改造的YOLOv8 BPU推理示例程序。由于官方没有提供直接的YOLOv8 Python示例，本示例使用相同的BPU推理框架来运行YOLOv8模型。

## 文件说明

- `test_yolov8_simple.py` - 简化版YOLOv8推理示例（推荐）
- `test_yolov8.py` - 完整版YOLOv8推理示例（需要修复后处理）

## 运行方式

```bash
cd /app/pydev_demo/13_yolov8_sample
/usr/bin/python3.10 test_yolov8_simple.py
```

## 模型信息

- **模型文件**: `/app/pydev_demo/models/yolov8_640x640_nv12.bin`
- **输入尺寸**: 640x640 NV12格式
- **输出数量**: 6个张量（包含检测框和分类信息）
- **推理时间**: ~8-9ms (BPU加速)

## 输出说明

YOLOv8输出6个张量：
- Output 0, 2, 4: 检测框坐标 (float32)
- Output 1, 3, 5: 分类置信度 (int32)

每个尺度的输出对应不同的特征图尺寸：
- 80x80：小目标检测
- 40x40：中等目标检测  
- 20x20：大目标检测

## 注意事项

1. 必须使用系统Python运行：`/usr/bin/python3.10`
2. 模型已验证可以在BPU上正常运行
3. 完整的后处理需要根据YOLOv8的输出格式定制
4. 当前示例展示了BPU推理的核心功能

## 性能

- 推理速度：8-9ms
- BPU使用：推理期间BPU使用率会上升，完成后回到0%
- 内存占用：低，适合嵌入式部署