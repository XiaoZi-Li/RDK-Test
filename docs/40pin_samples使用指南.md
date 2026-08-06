# 40pin_samples 模块详细使用指南

## 目录
1. [模块概述](#1-模块概述)
2. [硬件接线说明](#2-硬件接线说明)
3. [环境依赖](#3-环境依赖)
4. [各示例详解](#4-各示例详解)
   - [simple_out.py - GPIO输出](#41-simple_outpy---gpio输出)
   - [simple_input.py - GPIO输入](#42-simple_inputpy---gpio输入)
   - [simple_pwm.py - PWM输出](#43-simple_pwmpy---pwm输出)
   - [button_event.py - 按钮事件检测](#44-button_eventpy---按钮事件检测)
   - [button_interrupt.py - 按钮中断处理](#45-button_interruptpy---按钮中断处理)
   - [button_led.py - 按钮控制LED](#46-button_ledpy---按钮控制led)
   - [test_all_pins.py - 测试所有引脚](#47-test_all_pinspy---测试所有引脚)
   - [test_i2c.py - I2C通信测试](#48-test_i2cpy---i2c通信测试)
   - [test_serial.py - 串口通信测试](#49-test_serialpy---串口通信测试)
   - [test_spi.py - SPI通信测试](#410-test_spipy---spi通信测试)
5. [参数调整指南](#5-参数调整指南)
6. [常见问题解决](#6-常见问题解决)

---

## 1. 模块概述

### 1.1 功能说明
40pin_samples 模块提供基于地平线开发板的 GPIO、I2C、SPI、UART 等硬件接口的 Python 示例代码。通过 `Hobot.GPIO` 库实现对硬件引脚的控制。

### 1.2 目录结构
```
40pin_samples/
├── simple_out.py        # GPIO输出示例
├── simple_input.py       # GPIO输入示例
├── simple_pwm.py         # PWM输出示例
├── button_event.py       # 按钮事件检测
├── button_interrupt.py   # 按钮中断处理
├── button_led.py         # 按钮控制LED
├── test_all_pins.py      # 测试所有引脚
├── test_i2c.py           # I2C通信测试
├── test_serial.py        # 串口通信测试
└── test_spi.py           # SPI通信测试
```

### 1.3 支持的接口类型
| 接口类型 | 支持功能 | 引脚要求 |
|----------|----------|----------|
| GPIO | 数字输入/输出 | 任意GPIO引脚 |
| PWM | 脉宽调制输出 | **仅32和33引脚** |
| I2C | 双线串行通信 | 使用i2cdev库 |
| UART | 串口通信 | 使用pyserial库 |
| SPI | 四线串行通信 | 使用spidev库 |

---

## 2. 硬件接线说明

### 2.1 GPIO引脚对照表

| 功能 | BOARD编号 | BCM编号 | 说明 |
|------|-----------|---------|------|
| GPIO输出(LED) | 31 | - | 接LED正极(带限流电阻) |
| GPIO输入(按钮) | 37 | - | 接按钮，另一端接地 |
| PWM输出 | 32 | - | 仅支持PWM |
| PWM输出 | 33 | - | 仅支持PWM |

### 2.2 典型接线图

#### LED接线
```
开发板GPIO31 ----[电阻(330Ω)]----[LED+]----[LED-]---- GND
```

#### 按钮接线
```
开发板GPIO37 ----[按钮]---- GND
```
**注意**: 按钮另一端必须接地，使用开发板内部上拉电阻

#### PWM接线(舵机为例)
```
开发板GPIO33 ---- 舵机信号线(橙/黄)
开发板5V ---- 舵机红线
开发板GND ---- 舵机棕线
```

---

## 3. 环境依赖

### 3.1 必需库
```bash
# GPIO控制库 (地平线提供)
Hobot.GPIO

# I2C通信库
i2cdev

# 串口通信库
pyserial

# SPI通信库
spidev
```

### 3.2 库安装方法
```bash
# 在开发板上执行
pip3 install Hobot.GPIO
pip3 install i2cdev
pip3 install pyserial
pip3 install spidev
```

### 3.3 权限设置
```bash
# 添加用户到gpio组
sudo usermod -a -G gpio your_username

# 设置GPIO权限
sudo chmod 777 /dev/gpiochip0

# 设置串口权限
sudo chmod 777 /dev/ttyUSB*
```

---

## 4. 各示例详解

### 4.1 simple_out.py - GPIO输出

#### 功能说明
控制GPIO引脚输出高低电平，实现LED闪烁效果。这是GPIO最基础的示例。

#### 完整代码注释
```python
#!/usr/bin/env python3

import sys
import signal
import Hobot.GPIO as GPIO  # 导入地平线GPIO库
import time

# 信号处理函数，捕获Ctrl+C优雅退出
def signal_handler(signal, frame):
    sys.exit(0)

# 定义使用的GPIO通道为37 (BOARD编码)
output_pin = 37

# 禁用警告信息
GPIO.setwarnings(False)

def main():
    # 设置管脚编码模式为硬件编号 BOARD
    # 备选模式: GPIO.BCM (Broadcom编号)
    GPIO.setmode(GPIO.BOARD)

    # 设置为输出模式，初始化为高电平(HIGH)
    GPIO.setup(output_pin, GPIO.OUT, initial=GPIO.HIGH)

    # 记录当前管脚状态
    curr_value = GPIO.HIGH

    print("Starting demo now! Press CTRL+C to exit")

    try:
        # 无限循环，间隔1秒切换电平
        while True:
            time.sleep(1)  # 调整闪烁间隔(秒)
            GPIO.output(output_pin, curr_value)  # 输出电平
            curr_value ^= GPIO.HIGH  # 翻转电平状态
    finally:
        GPIO.cleanup()  # 清理GPIO资源

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
```

#### 使用方法
```bash
# 进入目录
cd /app/40pin_samples

# 运行示例
python3 simple_out.py

# 预期输出
Starting demo now! Press CTRL+C to exit
```
LED将每1秒闪烁一次。

#### 关键参数说明
| 参数 | 位置 | 说明 | 可调整范围 |
|------|------|------|------------|
| output_pin | 第28行 | GPIO引脚号 | 任意GPIO引脚 |
| time.sleep(1) | 第43行 | 闪烁间隔(秒) | 0.1-10秒 |

#### 调整指南
1. **改变引脚**: 修改 `output_pin = 37` 为其他引脚号
2. **改变闪烁频率**: 修改 `time.sleep(1)` 中的数值
   - 0.5 = 每秒闪烁2次
   - 2 = 每2秒闪烁1次
3. **改变初始电平**: 修改 `initial=GPIO.HIGH` 为 `GPIO.LOW`

---

### 4.2 simple_input.py - GPIO输入

#### 功能说明
读取GPIO引脚的输入电平状态，检测按钮或数字传感器信号。

#### 完整代码注释
```python
#!/usr/bin/env python3

import sys
import signal
import Hobot.GPIO as GPIO
import time

def signal_handler(signal, frame):
    sys.exit(0)

# 定义输入引脚为37
input_pin = 37

GPIO.setwarnings(False)

def main():
    prev_value = None  # 上一次读取的值

    # 设置为BOARD编码模式
    GPIO.setmode(GPIO.BOARD)

    # 设置为输入模式
    GPIO.setup(input_pin, GPIO.IN)

    print("Starting demo now! Press CTRL+C to exit")

    try:
        while True:
            # 读取引脚电平
            value = GPIO.input(input_pin)

            # 仅当电平变化时打印
            if value != prev_value:
                if value == GPIO.HIGH:
                    value_str = "HIGH"
                else:
                    value_str = "LOW"

                print("Value read from pin {} : {}".format(input_pin, value_str))
                prev_value = value

            time.sleep(1)  # 采样间隔

    finally:
        GPIO.cleanup()

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
```

#### 使用方法
```bash
python3 simple_input.py
```

#### 关键参数说明
| 参数 | 位置 | 说明 | 调整建议 |
|------|------|------|----------|
| input_pin | 第28行 | 输入引脚号 | 根据实际接线 |
| time.sleep(1) | 第52行 | 采样间隔(秒) | 传感器响应要求 |

#### 调整指南
1. **快速响应**: 减小 `time.sleep(1)` 到 `0.01` 实现100Hz采样
2. **防抖处理**: 增加软件防抖:
```python
def read_with_debounce(pin, delay=0.01):
    time.sleep(delay)
    return GPIO.input(pin)
```

---

### 4.3 simple_pwm.py - PWM输出

#### 功能说明
输出PWM波形，可用于LED调光、电机调速、舵机控制。

#### 完整代码注释
```python
#!/usr/bin/env python3

import sys
import signal
import Hobot.GPIO as GPIO
import time

def signal_handler(signal, frame):
    sys.exit(0)

# 支持PWM的管脚: 32 and 33
# 注意: 使用PWM时必须确保该管脚没有被其他功能占用
output_pin = 33

GPIO.setwarnings(False)

def main():
    # BOARD pin-numbering scheme
    GPIO.setmode(GPIO.BOARD)

    # 支持的频率范围: 48KHz ~ 192MHz
    # 频率设置说明:
    # - 48000 Hz (48KHz): 低速设备
    # - 500000 Hz (500KHz): 中速设备
    # - 12000000 Hz (12MHz): 高速设备
    p = GPIO.PWM(output_pin, 48000)

    # 初始占空比 25%
    # 占空比含义: 一个周期内高电平所占的比例
    # 0% = 完全关闭, 100% = 完全打开
    val = 25
    incr = 5  # 每次变化5%

    # 启动PWM
    p.start(val)

    print("PWM running. Press CTRL+C to exit.")

    try:
        while True:
            time.sleep(0.25)  # 变化周期

            # 达到100%时开始减少
            if val >= 100:
                incr = -incr

            # 达到0%时开始增加
            if val <= 0:
                incr = -incr

            val += incr
            p.ChangeDutyCycle(val)  # 改变占空比

    finally:
        p.stop()       # 停止PWM
        GPIO.cleanup() # 清理GPIO

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
```

#### 使用方法
```bash
python3 simple_pwm.py
```
LED将呈现呼吸灯效果: 渐亮→渐暗→渐亮...

#### 关键参数详解
| 参数 | 位置 | 说明 | 可调整范围 |
|------|------|------|------------|
| output_pin | 第28行 | PWM输出引脚 | **必须为32或33** |
| 48000 | 第37行 | PWM频率(Hz) | 48000-192000000 |
| val = 25 | 第39行 | 初始占空比(%) | 0-100 |
| incr = 5 | 第40行 | 每次变化量(%) | 1-20 |
| time.sleep(0.25) | 第47行 | 变化周期(秒) | 0.01-1 |

#### 调整指南

**1. 舵机控制示例:**
```python
# 舵机通常需要50Hz频率
p = GPIO.PWM(output_pin, 50)

# 角度控制 (参考):
# 0度 = 5%占空比
# 90度 = 7.5%占空比
# 180度 = 10%占空比

p.start(5)  # 从0度开始
time.sleep(1)
p.ChangeDutyCycle(7.5)  # 转到90度
time.sleep(1)
p.ChangeDutyCycle(10)   # 转到180度
```

**2. 电机调速示例:**
```python
# 直流电机通常需要10-25kHz
p = GPIO.PWM(output_pin, 10000)

# 调速范围 20%-100%
p.start(0)  # 停止
p.ChangeDutyCycle(50)  # 半速
p.ChangeDutyCycle(100) # 全速
```

**3. LED调光示例:**
```python
# LED调光适合使用1KHz-10KHz
p = GPIO.PWM(output_pin, 1000)

# 平滑调光
for i in range(0, 101, 5):
    p.ChangeDutyCycle(i)
    time.sleep(0.05)
```

---

### 4.4 button_event.py - 按钮事件检测

#### 功能说明
检测按钮按下事件，按下时LED亮起，1秒后熄灭。

#### 完整代码注释
```python
#!/usr/bin/env python3

import sys
import signal
import Hobot.GPIO as GPIO
import time

def signal_handler(signal, frame):
    sys.exit(0)

# GPIO通道定义:
# 31号作为输出，可以点亮一个LED
# 37号作为输入，可以接一个按钮
led_pin = 31   # BOARD编码 31
but_pin = 37   # BOARD编码 37

GPIO.setwarnings(False)

def main():
    # BOARD编码模式
    GPIO.setmode(GPIO.BOARD)

    # LED设置为输出
    GPIO.setup(led_pin, GPIO.OUT)
    # 按钮设置为输入
    GPIO.setup(but_pin, GPIO.IN)

    # LED初始状态为关闭
    GPIO.output(led_pin, GPIO.LOW)

    print("Starting demo now! Press CTRL+C to exit")

    try:
        while True:
            print("Waiting for button event")

            # 等待按钮按下(下降沿触发)
            # 备选模式:
            # GPIO.RISING - 上升沿(松开时触发)
            # GPIO.BOTH - 任意边沿
            GPIO.wait_for_edge(but_pin, GPIO.FALLING)

            # 按钮按下事件
            print("Button Pressed!")
            GPIO.output(led_pin, GPIO.HIGH)  # LED亮
            time.sleep(1)                    # 保持1秒
            GPIO.output(led_pin, GPIO.LOW)   # LED灭

    finally:
        GPIO.cleanup()

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
```

#### 使用方法
```bash
python3 button_event.py
```
按下按钮，LED亮1秒后熄灭。

#### 关键参数说明
| 参数 | 位置 | 说明 | 可调整范围 |
|------|------|------|------------|
| led_pin | 第30行 | LED引脚 | 任意GPIO |
| but_pin | 第31行 | 按钮引脚 | 任意GPIO |
| time.sleep(1) | 第54行 | LED亮持续时间 | 0.1-10秒 |

#### 调整指南

**1. 改变触发模式:**
```python
# 改为松开触发
GPIO.wait_for_edge(but_pin, GPIO.RISING)

# 改为任意变化触发
GPIO.wait_for_edge(but_pin, GPIO.BOTH)
```

**2. 改变动作行为:**
```python
# 按住按钮期间LED一直亮
while True:
    if GPIO.input(but_pin) == GPIO.LOW:  # 按钮按下
        GPIO.output(led_pin, GPIO.HIGH)
    else:
        GPIO.output(led_pin, GPIO.LOW)
    time.sleep(0.01)
```

---

### 4.5 button_interrupt.py - 按钮中断处理

#### 功能说明
使用中断方式检测按钮，按下时触发回调函数，实现LED闪烁。

#### 完整代码注释
```python
#!/usr/bin/env python3

import sys
import signal
import Hobot.GPIO as GPIO
import time

def signal_handler(signal, frame):
    sys.exit(0)

# GPIO定义:
led_pin_1 = 15   # LED1输出
led_pin_2 = 16   # LED2输出
but_pin = 37     # 按钮输入

GPIO.setwarnings(False)

# 中断回调函数 - 按钮按下时LED2闪烁5次
def blink(channel):
    print("Blink LED 2")
    for i in range(5):
        GPIO.output(led_pin_2, GPIO.HIGH)
        time.sleep(0.5)
        GPIO.output(led_pin_2, GPIO.LOW)
        time.sleep(0.5)

def main():
    GPIO.setmode(GPIO.BOARD)

    # 设置LED为输出
    GPIO.setup([led_pin_1, led_pin_2], GPIO.OUT)
    # 设置按钮为输入
    GPIO.setup(but_pin, GPIO.IN)

    # LED初始关闭
    GPIO.output(led_pin_1, GPIO.LOW)
    GPIO.output(led_pin_2, GPIO.LOW)

    # 注册中断检测
    # 参数说明:
    # - but_pin: 监测的引脚
    # - GPIO.FALLING: 下降沿触发(按钮按下)
    # - callback=blink: 回调函数
    # - bouncetime=10: 消抖时间(毫秒)
    GPIO.add_event_detect(but_pin, GPIO.FALLING, callback=blink, bouncetime=10)

    # LED1缓慢闪烁
    print("Starting demo now! Press CTRL+C to exit")
    try:
        while True:
            GPIO.output(led_pin_1, GPIO.HIGH)
            time.sleep(2)
            GPIO.output(led_pin_1, GPIO.LOW)
            time.sleep(2)
    finally:
        GPIO.cleanup()

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
```

#### 使用方法
```bash
python3 button_interrupt.py
```
- LED1每2秒闪烁一次
- 按下按钮时LED2快速闪烁5次

#### 关键参数说明
| 参数 | 位置 | 说明 | 可调整范围 |
|------|------|------|------------|
| bouncetime | 第59行 | 消抖时间(ms) | 10-500ms |
| range(5) | 第42行 | 闪烁次数 | 1-20 |
| time.sleep(0.5) | 第44-45行 | 闪烁间隔 | 0.1-1秒 |

#### 调整指南

**1. 消抖时间设置:**
```python
# 机械按钮通常需要10-50ms消抖
GPIO.add_event_detect(but_pin, GPIO.FALLING, callback=blink, bouncetime=50)
```

**2. 多种触发模式:**
```python
# 下降沿(按下触发)
GPIO.add_event_detect(but_pin, GPIO.FALLING, callback=blink)

# 上升沿(松开触发)
GPIO.add_event_detect(but_pin, GPIO.RISING, callback=blink)

# 边沿检测(按下和松开都触发)
GPIO.add_event_detect(but_pin, GPIO.BOTH, callback=blink)
```

**3. 移除中断检测:**
```python
GPIO.remove_event_detect(but_pin)
```

---

### 4.6 button_led.py - 按钮控制LED

#### 功能说明
按钮状态直接控制LED，按下亮，松开灭。

#### 完整代码注释
```python
#!/usr/bin/env python3

import sys
import signal
import Hobot.GPIO as GPIO
import time

def signal_handler(signal, frame):
    sys.exit(0)

led_pin = 31   # LED引脚
but_pin = 37   # 按钮引脚

GPIO.setwarnings(False)

def main():
    prev_value = None

    GPIO.setmode(GPIO.BOARD)

    # 设置LED为输出
    GPIO.setup(led_pin, GPIO.OUT)
    # 设置按钮为输入
    GPIO.setup(but_pin, GPIO.IN)

    # LED初始关闭
    GPIO.output(led_pin, GPIO.LOW)

    print("Starting demo now! Press CTRL+C to exit")

    try:
        while True:
            # 读取按钮状态
            curr_value = GPIO.input(but_pin)

            # 状态变化时更新LED
            if curr_value != prev_value:
                # 按下(GPIO.LOW)时LED亮，松开(GPIO.HIGH)时LED灭
                GPIO.output(led_pin, curr_value)
                prev_value = curr_value
                print("Outputting {} to Pin {}".format(curr_value, led_pin))

            time.sleep(1)

    finally:
        GPIO.cleanup()

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
```

#### 使用方法
```bash
python3 button_led.py
```
按住按钮LED亮，松开LED灭。

---

### 4.7 test_all_pins.py - 测试所有引脚

#### 功能说明
自动测试所有可用的GPIO引脚，帮助确认引脚工作状态。

#### 使用方法
```bash
# 测试所有引脚
python3 test_all_pins.py

# 测试指定引脚
python3 test_all_pins.py 15 16 37

# 测试引脚范围
python3 test_all_pins.py 15 16 18 22 37
```

#### 输出说明
```
All gpio pins:  [15, 16, 17, 18, ...]
Testing pin 15 as OUTPUT; CTRL-C to test next pin
```
每个引脚会以250ms间隔切换高低电平。

#### 调整参数
```python
# 修改切换速度
time.sleep(0.25)  # 第45-46行
```

---

### 4.8 test_i2c.py - I2C通信测试

#### 功能说明
扫描I2C总线设备并进行读写测试。

#### 完整代码注释
```python
#!/usr/bin/env python3

import sys
import signal
import os
import time
from i2cdev import I2C  # I2C设备库

def signal_handler(signal, frame):
    sys.exit(0)

def i2cdevTest():
    # 列出所有I2C设备
    print("List of enabled I2C controllers:")
    os.system('ls /dev/i2c*')

    # 获取用户输入
    bus = input("Please input I2C BUS num:")  # 如: 0, 1, 5
    os.system('i2cdetect -y -r ' + bus)  # 扫描总线设备

    device = input("Please input I2C device num(Hex):")  # 如: 0x51
    print("Read data from device %s on I2C bus %s" % (device, bus))

    # 打开I2C设备
    i2c = I2C(eval("0x" + device), int(bus))

    # 读取1字节
    value = i2c.read(1)
    print("read value=", value)

    # 写回数据
    i2c.write(value)

    # 关闭设备
    i2c.close()

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    print("Starting demo now! Press CTRL+C to exit")

    # 列出I2C控制器
    print("List of enabled I2C controllers:")
    os.system('ls /dev/i2c*')

    # 循环测试
    while True:
        i2cdevTest()
```

#### 使用方法
```bash
python3 test_i2c.py
```

#### 交互流程
```
List of enabled I2C controllers:
/dev/i2c-0  /dev/i2c-5

Please input I2C BUS num:5
# 显示总线扫描结果
Please input I2C device num(Hex):51
Read data from device 0x51 on I2C bus 5
read value= [数字]
```

#### 调整指南

**1. 直接指定设备(修改代码):**
```python
def i2cdevTest():
    bus = 5           # I2C总线号
    device = 0x51    # 设备地址(十六进制)

    i2c = I2C(device, bus)
    value = i2c.read(1)
    i2c.write(value)
    i2c.close()
```

**2. 自动扫描脚本:**
```bash
# 扫描所有I2C总线
for i in 0 1 5; do
    echo "Bus $i:"
    i2cdetect -y -r $i
done
```

---

### 4.9 test_serial.py - 串口通信测试

#### 功能说明
测试串口通信，支持多种波特率。

#### 完整代码注释
```python
#!/usr/bin/env python3

import sys
import signal
import os
import time
import serial              # 串口库
import serial.tools.list_ports  # 串口扫描

def signal_handler(signal, frame):
    sys.exit(0)

def serialTest():
    # 列出可用串口
    print("List of enabled UART:")
    os.system('ls /dev/tty[a-zA-Z]*')

    # 获取用户输入
    uart_dev = input("Please enter the name of the serial device to be tested:")

    # 选择波特率
    baudrate = input("Please enter the baud rate(9600,19200,38400,57600,115200,921600):")

    try:
        # 打开串口
        # 参数说明:
        # - port: 串口设备名
        # - baudrate: 波特率
        # - timeout: 读取超时(秒)
        ser = serial.Serial(uart_dev, int(baudrate), timeout=1)

        print(ser)  # 打印串口信息

        # 循环发送接收
        while True:
            test_data = "AA55"  # 测试数据
            write_num = ser.write(test_data.encode('UTF-8'))
            print("Send: ", test_data)

            # 读取相同长度数据
            received_data = ser.read(write_num).decode('UTF-8')
            print("Recv: ", received_data)

            time.sleep(1)

        ser.close()

    except Exception as e:
        print("open serial failed!")

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    serialTest()
```

#### 使用方法
```bash
python3 test_serial.py
```

#### 交互流程
```
List of enabled UART:
/dev/ttyUSB0  /dev/ttyACM0

Please enter the name of the serial device to be tested:/dev/ttyUSB0
Please enter the baud rate(9600,19200,38400,57600,115200,921600):115200
Serial<id=... open=True port='/dev/ttyUSB0' baudrate=115200...>
Starting demo now!
Send:  AA55
Recv:  AA55
```

#### 支持的波特率
| 波特率 | 适用场景 |
|--------|----------|
| 9600 | 慢速设备、GPS |
| 19200 | 串口屏幕 |
| 38400 | 工业设备 |
| 57600 | 中速设备 |
| 115200 | **最常用** |
| 921600 | 高速数据传输 |

#### 调整指南

**1. 修改测试数据:**
```python
test_data = "Hello World"  # 自定义测试数据
test_data = bytes([0x55, 0xAA, 0x01, 0x02])  # 十六进制
```

**2. 自动选择串口:**
```python
def auto_find_serial():
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        print(f"Found: {p.device}")
        if 'USB' in p.device:
            return p.device
    return '/dev/ttyUSB0'

uart_dev = auto_find_serial()
ser = serial.Serial(uart_dev, 115200)
```

---

### 4.10 test_spi.py - SPI通信测试

#### 功能说明
测试SPI总线通信，支持配置总线和片选。

#### 完整代码注释
```python
#!/usr/bin/env python3

import sys
import signal
import os
import time
import spidev  # SPI设备库

def signal_handler(signal, frame):
    sys.exit(0)

def BytesToHex(Bytes):
    """将字节数组转换为十六进制字符串"""
    return ''.join(["0x%02X " % x for x in Bytes]).strip()

def spidevTest():
    # 获取总线和设备号
    spi_bus = input("Please input SPI bus num:")      # 0, 1, 2
    spi_device = input("Please input SPI cs num:")    # 0, 1

    # 创建SPI对象
    spi = spidev.SpiDev()

    # 打开SPI总线
    spi.open(int(spi_bus), int(spi_device))

    # 设置SPI频率
    # 常用频率:
    # - 1MHz: 通用设备
    # - 10MHz: 高速设备
    # - 20MHz: Flash存储
    spi.max_speed_hz = 12000000  # 12MHz

    print("Starting demo now! Press CTRL+C to exit")

    try:
        while True:
            # 发送 [0x55, 0xAA]，接收相同数据
            # xfer2 会同时收发数据
            resp = spi.xfer2([0x55, 0xAA])
            print("Received:", BytesToHex(resp))
            time.sleep(1)

    except KeyboardInterrupt:
        spi.close()

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)

    # 列出SPI设备
    print("List of enabled spi controllers:")
    os.system('ls /dev/spidev*')

    spidevTest()
```

#### 使用方法
```bash
python3 test_spi.py
```

#### 交互流程
```
List of enabled spi controllers:
/dev/spidev0.0  /dev/spidev0.1  /dev/spidev1.0

Please input SPI bus num:0
Please input SPI cs num:0
Starting demo now! Press CTRL+C to exit
Received: 0x55 0xAA
Received: 0x55 0xAA
```

#### 调整指南

**1. 修改SPI模式:**
```python
# SPI模式 0-3
spi.mode = 0  # 模式0: CPOL=0, CPHA=0
spi.mode = 3  # 模式3: CPOL=1, CPHA=1
```

**2. 修改位宽:**
```python
# 每字节位数 (8或16)
spi.bits_per_word = 8
```

**3. 高速设备配置:**
```python
spi.max_speed_hz = 20000000  # 20MHz
spi.mode = 0
spi.bits_per_word = 8
```

---

## 5. 参数调整指南

### 5.1 GPIO模式选择
```python
# BOARD模式 - 使用物理引脚编号
GPIO.setmode(GPIO.BOARD)

# BCM模式 - 使用Broadcom芯片编号
GPIO.setmode(GPIO.BCM)
```

### 5.2 引脚方向设置
```python
# 设置为输出
GPIO.setup(pin, GPIO.OUT)

# 设置为输入
GPIO.setup(pin, GPIO.IN)

# 设置为输出并初始化
GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
```

### 5.3 电平读取和设置
```python
# 读取电平
value = GPIO.input(pin)

# 输出高电平
GPIO.output(pin, GPIO.HIGH)
# 或
GPIO.output(pin, 1)

# 输出低电平
GPIO.output(pin, GPIO.LOW)
# 或
GPIO.output(pin, 0)
```

### 5.4 PWM配置
```python
# 创建PWM对象
# 参数: 引脚, 频率(Hz)
p = GPIO.PWM(pin, 1000)

# 启动PWM
# 参数: 初始占空比(0-100)
p.start(50)

# 改变占空比
p.ChangeDutyCycle(75)

# 停止PWM
p.stop()

# 修改频率
p.ChangeFrequency(2000)
```

### 5.5 中断配置
```python
# 添加边沿检测
GPIO.add_event_detect(pin, GPIO.FALLING, callback=my_callback, bouncetime=200)

# 移除检测
GPIO.remove_event_detect(pin)

# 检查事件是否发生
if GPIO.event_detected(pin):
    print("Event detected!")
```

---

## 6. 常见问题解决

### 6.1 权限问题
```bash
# 解决方法1: 使用sudo运行
sudo python3 simple_out.py

# 解决方法2: 添加用户组
sudo usermod -a -G gpio,dialout,i2c,spi $USER
# 然后重新登录
```

### 6.2 引脚被占用
```python
# 禁用警告
GPIO.setwarnings(False)

# 检查引脚状态
os.system('cat /sys/class/gpio/gpio37/value')
```

### 6.3 I2C设备无响应
```bash
# 检查I2C设备是否挂载
i2cdetect -y -r 5

# 检查驱动加载
lsmod | grep i2c
```

### 6.4 串口无法打开
```bash
# 检查设备权限
ls -la /dev/ttyUSB0

# 检查设备是否被占用
lsof /dev/ttyUSB0
```

### 6.5 SPI通信失败
```bash
# 检查SPI设备
ls -la /dev/spidev*

# 检查内核模块
lsmod | grep spi
```

---

## 附录: 快速参考表

| 功能 | 示例文件 | 关键函数 |
|------|----------|----------|
| LED闪烁 | simple_out.py | GPIO.output() |
| 按钮输入 | simple_input.py | GPIO.input() |
| PWM调光 | simple_pwm.py | GPIO.PWM() |
| 按钮事件 | button_event.py | GPIO.wait_for_edge() |
| 中断处理 | button_interrupt.py | GPIO.add_event_detect() |
| I2C通信 | test_i2c.py | I2C.read()/write() |
| 串口通信 | test_serial.py | serial.Serial() |
| SPI通信 | test_spi.py | spidev.xfer2() |

---

**文档版本**: 1.0
**更新日期**: 2026-04-20
**适用平台**: 地平线 RDK X3/X5 开发板
