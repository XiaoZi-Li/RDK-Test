#!/usr/bin/env python3

################################################################################
# Copyright (c) 2024,D-Robotics.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
################################################################################

"""
PWM(脉宽调制)输出示例 - 详细注释版

功能概述:
    这个程序演示如何在开发板上使用GPIO管脚输出PWM信号,
    控制LED实现呼吸灯效果。

PWM技术原理:
    PWM(Pulse Width Modulation)即脉宽调制,是一种通过数字信号
    控制模拟电路的技术。基本原理如下:

    1. 占空比(Duty Cycle): 一个周期内高电平时间占整个周期的比例
       - 占空比0%: 完全低电平,LED熄灭
       - 占空比50%: 一半时间高电平,LED半亮
       - 占空比100%: 完全高电平,LED全亮

    2. 频率(Frequency): 单位时间内完整周期出现的次数
       - 本程序使用48KHz(48000Hz)频率
       - 频率越高,人眼越难察觉到闪烁

    3. 呼吸灯原理:
       周期性地增加和减少占空比,让LED呈现渐明渐暗的效果
       | 占空比
       |    100% ─────────┐
       |              ／   ＼
       |           ／        ＼
       |        ／            ＼
       |     ／                ＼
       |  ／                    ＼
       | 0%                      └────────────── 时间
       |       ◢──◣    ◢──◣    ◢──◣
       |        增加   减少   增加

硬件连接:
    ┌─────────────────────────────────────────┐
    │           开发板                         │
    │  ┌──────┐                              │
    │  │ GPIO │──────┐                       │
    │  │  33  │      │   限流电阻            │
    │  └──────┘      ├───330Ω──┬──► LED ──┬─── GND
    │                  │          │          │
    │                  └──────────┴──────────┘
    └─────────────────────────────────────────┘

    注意: 必须使用支持PWM的管脚,本程序使用GPIO 33

参数说明:
    - 输出管脚: GPIO 33 (BOARD编号模式下的33号物理引脚)
    - PWM频率: 48KHz (48000Hz),范围48KHz~192MHz
    - 占空比: 0%~100%循环变化
    - 变化步进: 每次变化5%
    - 变化周期: 每0.25秒变化一次

适用场景:
    - LED亮度控制
    - 电机速度控制
    - 舵机角度控制
    - 音频信号生成
    - 电源管理

依赖库:
    - Hobot.GPIO: 地平线开发板的GPIO控制库
    - signal: 信号处理,用于优雅退出

使用方法:
    sudo python3 simple_pwm_详细注释版.py

    运行效果:
    - LED会从暗到亮,再从亮到暗,循环往复
    - 按Ctrl+C可以安全退出程序
"""

import sys
import signal
import Hobot.GPIO as GPIO
import time

def signal_handler(signal, frame):
    """
    信号处理函数 - 实现优雅退出

    功能:
        当用户按下Ctrl+C时,SIGINT信号会被触发,
        此函数会安全地停止PWM输出并清理GPIO资源

    为什么需要这个函数:
        如果直接按Ctrl+C退出,可能不会执行GPIO cleanup,
        导致GPIO管脚保持当前状态。下次运行时可能出现问题。

    参数:
        signal: 信号类型(如SIGINT)
        frame: 当前堆栈帧
    """
    sys.exit(0)

# 支持PWM的管脚: 32 and 33
# 在使用PWM时，必须确保该管脚没有被其他功能占用
output_pin = 33

GPIO.setwarnings(False)

def main():
    """
    主函数 - PWM呼吸灯控制

    执行流程:
        1. 设置GPIO引脚编号模式为BOARD(物理引脚号)
        2. 在指定引脚上创建PWM对象,频率48KHz
        3. 初始化占空比为25%,启动PWM
        4. 进入主循环,不断调整占空比实现呼吸灯效果
        5. 退出时停止PWM并清理GPIO资源
    """
    # Pin Setup:
    # Board pin-numbering scheme
    # 使用BOARD编号模式,即使用物理引脚号而非GPIO号
    # 这样更容易对应开发板上的丝印编号
    GPIO.setmode(GPIO.BOARD)

    # 支持的频率范围: 48KHz ~ 192MHz
    # 创建PWM对象,频率设为48KHz
    # 频率选择说明:
    # - 48KHz是人类听觉范围外的频率,不会有噪音
    # - 对于LED控制,这个频率足够高,不会看到闪烁
    # - 频率太高会增加CPU负担和EMI辐射
    p = GPIO.PWM(output_pin, 48000)

    # 初始占空比 25%
    # 先每0.25秒增加5%占空比，达到100%之后再每0.25秒减少5%占空比
    val = 25      # 当前占空比,初始25%
    incr = 5      # 变化增量,每次变化5%

    # 改变占空比并启动PWM
    # 注意: ChangeDutyCycle需要在Start之后才能使用
    p.ChangeDutyCycle(val)
    p.start(val)

    print("PWM running. Press CTRL+C to exit.")
    try:
        # 主循环: 呼吸灯效果
        while True:
            # 等待0.25秒
            time.sleep(0.25)

            # 如果达到100%,开始减少
            if val >= 100:
                incr = -incr

            # 如果达到0%,开始增加
            if val <= 0:
                incr = -incr

            # 更新占空比
            val += incr

            # 设置新的占空比
            # 这个值会在下一个周期生效
            p.ChangeDutyCycle(val)

            # 呼吸灯效果示意:
            #
            # 时间 →→→
            # val
            # 100% │          ●●●●●
            #      │        ●       ●
            #  75% │      ●           ●
            #      │    ●               ●
            #  50% │  ●                 ●
            #      │ ●                   ●
            #  25% │●                     ●
            #      │└─────────────────────┘
            #      0%
            #
            # ● = 增量方向改变点

    finally:
        # 清理资源
        # 停止PWM信号输出
        p.stop()
        # 重置GPIO管脚到默认状态
        GPIO.cleanup()

if __name__ == '__main__':
    # 注册SIGINT信号处理器
    # 当Ctrl+C被按下时,会调用signal_handler
    signal.signal(signal.SIGINT, signal_handler)

    # 启动主程序
    main()
