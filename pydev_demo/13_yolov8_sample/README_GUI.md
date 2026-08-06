# YOLOv8 BPU GUI示例程序

## 📁 文件说明

### 1. GUI演示程序

| 文件名 | 功能 | 适用场景 |
|--------|------|----------|
| `test_yolov8_gui.py` | 完整GUI示例，支持摄像头/图像输入 | 需要完整检测显示 |
| `test_simple_gui.py` | 简化GUI演示，显示推理性能 | 性能测试和演示 |
| `test_headless.py` | 无GUI版本，纯性能测试 | 服务器环境或批量测试 |

## 🚀 运行方式

### 简单演示（推荐）

```bash
cd /app/pydev_demo/13_yolov8_sample
/usr/bin/python3.10 test_headless.py
```

### GUI演示（需要显示界面）

```bash
# 简单GUI演示
/usr/bin/python3.10 test_simple_gui.py

# 带摄像头的GUI演示
/usr/bin/python3.10 test_simple_gui.py camera
```

### 完整GUI接口

```bash
/usr/bin/python3.10 test_yolov8_gui.py
```

## 📊 性能数据

### 最新测试结果
- **平均FPS**: 84.5
- **平均推理时间**: 11.83 ms
- **最快推理**: 6.63 ms
- **理论最大FPS**: 150.8
- **BPU使用率**: 6%（推理期间）

### 输出张量信息
- **输入**: 640×640 NV12格式
- **输出**: 6个张量
  - 3个检测框输出（80×80, 40×40, 20×20）
  - 3个分类输出（对应尺寸）

## 🎯 功能特点

### `test_headless.py`（无GUI版本）
- ✅ 完整性能测试
- ✅ 50次迭代统计
- ✅ 输出张量分析
- ✅ BPU使用率监控
- ✅ 适合服务器环境

### `test_simple_gui.py`（简化GUI）
- ✅ 实时FPS显示
- ✅ 推理时间统计
- ✅ 绘制测试场景
- ✅ 支持摄像头输入
- ✅ ESC键退出

### `test_yolov8_gui.py`（完整GUI）
- ✅ 完整检测流程
- ✅ COCO类别显示
- ✅ 边界框绘制
- ✅ 摄像头/图像双模式
- ✅ 交互式界面

## 🖥️ 显示效果

### GUI界面包含
1. **实时推理画面**
2. **性能统计面板**
   - FPS显示
   - 推理时间（当前/平均/最小/最大）
   - BPU使用率
3. **检测结果**（边界框+类别标签）

### 无GUI版本输出
```
============================================================
PERFORMANCE RESULTS
============================================================
Test iterations: 50
Average inference time: 11.83 ms
Average FPS: 84.5
Theoretical max FPS: 150.8
============================================================
```

## ⚠️ 注意事项

1. **必须使用系统Python**: `/usr/bin/python3.10`
2. **GUI需要X11显示**: 如果没有显示器，使用headless版本
3. **摄像头支持**: 需要连接USB摄像头
4. **BPU模型**: 使用预量化的`.bin`文件，自动BPU加速

## 🔧 故障排除

### GUI无法显示
- 确认有显示器连接
- 使用headless版本替代
- 检查X11转发设置

### 摄像头无法打开
- 确认USB摄像头已连接
- 检查设备权限：`sudo usermod -a -G video $USER`
- 使用图像模式替代

### 性能低于预期
- 检查BPU温度：`cat /sys/class/thermal/thermal_zone0/temp`
- 确认没有其他BPU任务运行
- 使用更大的测试图片提高准确性