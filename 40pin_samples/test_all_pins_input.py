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

from __future__ import print_function
import sys
import signal
import Hobot.GPIO as GPIO

def signal_handler(signal, frame):
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# 获取所有可以控制的管脚 BOARD 编号
all_pins = list(GPIO.all_pin_data['BOARD'].keys())
all_pins.sort()

# 从命令行参数里面获取需要测试的管脚号序列
if len(sys.argv) > 1:
    all_pins = map(int, sys.argv[1:])

print("All gpio pins: ", all_pins)

# 禁用警告信息
GPIO.setwarnings(False)

# 读取所有管脚的电平
for pin in all_pins:
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(pin, GPIO.IN)
    value = GPIO.input(pin)
    print("Pin %d input value %d" % (pin, value))
    GPIO.cleanup()
