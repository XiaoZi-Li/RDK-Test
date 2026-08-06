#!/usr/bin/env python3
# encoding: utf-8
"""
动作组控制模块 - 详细注释版

功能概述:
    这个模块负责机器狗动作组的加载和执行,是动作控制的核心模块。
    动作组以SQLite数据库文件(.d6a/.d6ac)形式存储,包含一系列预先录制好的动作帧。
    每一帧包含执行时间和对应的舵机角度或坐标值。

动作组文件格式:
    - .d6a文件: 包含11个舵机的脉宽值(舵机角度模式)
    - .d6ac文件: 包含12个坐标值(坐标控制模式)
    - 数据库表名: ActionGroup
    - 列结构: Index(自增ID), Time(执行时间ms), Servo1-11/C1-C12

执行模式:
    1. 直接执行模式(runActionGroup): 阻塞等待动作组执行完毕
    2. 后台执行模式(runActionGroup+wait=False): 非阻塞,动作在后台线程执行
    3. 在线执行模式(change_action_value): 支持循环次数控制的后台执行

适用对象: 机器狗开发者、动作设计师

依赖模块:
    - servo_controller: 舵机底层控制
    - PuppyInstantiate: 机器狗实例,包含逆运动学方法
    - sqlite3: 动作组文件读写
    - threading: 多线程支持

硬件平台: 树莓派/嵌入式Linux设备 + 总线舵机控制器
"""

import os
import time
import threading
import sqlite3 as sql
import numpy as np
import sys


from servo_controller import setServoPulse

from PuppyInstantiate import PuppyInstantiate as puppy


# 动作组文件存储路径
action_group_path = '/app/pydev_demo/puppypi_control/ActionGroups/'

# 运行状态标志位
# runningAction: 标识是否有动作组正在运行
runningAction = False

# stopRunning: 停止标志,当设置为True时,当前动作组会立即停止
stopRunning = False

# online_action_num: 当前在线执行的动作组文件名
online_action_num = None

# online_action_times: 动作组剩余执行次数
# -1表示空载(未指定动作)
# 0表示无限循环
# 正数表示具体次数
online_action_times = -1

# update_ok: 标志位,表示是否需要更新执行的动作组
update_ok = False

# action_group_finish: 标志位,表示动作组是否执行完毕
action_group_finish = True


def runActionGroup(num, wait = False):
    """
    运行动作组的主入口函数

    功能说明:
        这是最常用的动作组执行函数,可以指定是否等待动作执行完毕。
        函数内部会启动一个后台线程来执行动作,主线程可以继续做其他事情。

    参数说明:
        num: 动作组文件名,字符串类型
             例如: "stand.d6a", "walk.d6ac"
             注意: 文件名可以包含扩展名,也可以不包含

        wait: 是否等待动作组执行完毕
              False(默认): 非阻塞执行,函数立即返回
              True: 阻塞等待,直到动作组执行完毕或超时(30秒)

    返回值:
        无直接返回值
        当wait=True时,函数会在动作执行完毕后返回

    使用示例:
        # 非阻塞执行,立即返回
        runActionGroup("stand.d6a")

        # 阻塞等待,直到站起来动作完成
        runActionGroup("stand.d6a", wait=True)

        # 执行踢足球动作(假设存在)
        runActionGroup("kick_ball_left.d6ac")

    超时处理:
        当wait=True时,最多等待30秒
        如果动作组在30秒内未完成,会强制退出等待循环

    线程模型:
        使用threading.Thread创建后台线程执行动作
        允许多个动作组请求同时存在,但实际只有最近一个会执行
    """
    global runningAction
    # 启动后台线程执行动作组
    threading.Thread(target=runAction, args=(num, )).start()

    # 如果不需要等待,立即返回
    if wait == False:
        return

    # 等待动作组执行完毕
    t = time.time() # 等待动作组做结束(wait for the action group to finish)
    time.sleep(0.02)
    while time.time() - t < 30:#超时强制跳出(force exit due to timeout)
        time.sleep(0.001)
        if runningAction == False:
            break


def stopActionGroup():
    """
    停止当前正在运行的动作组

    功能说明:
        这是一个重要的安全控制函数,用于紧急停止机器狗的运动。
        设置停止标志位,正在执行的动作组会在下一个动作帧检测到标志后停止。

    实现原理:
        设置全局变量stopRunning=True
        runAction函数中的循环会检测这个标志,发现为True时立即退出循环

    重置状态:
        除了设置stopRunning,还会重置以下状态:
        - update_ok = False
        - online_action_num = None
        - online_action_times = -1

    使用场景:
        - 紧急停止按钮
        - 检测到障碍物需要立即停止
        - 用户中断动作执行
        - 程序结束前的清理

    注意:
        这个函数不会等待动作完全停止,只是发送停止信号
        实际停止可能需要几毫秒时间(取决于当前动作帧的执行时间)
    """
    global stopRunning, online_action_num, online_action_times, update_ok
    update_ok = False
    stopRunning = True
    online_action_num = None
    online_action_times = -1
    time.sleep(0.1)


def stop_servo():
    """
    停止所有舵机(当前已禁用)

    功能说明:
        理论上应该发送停止命令给所有舵机,使它们立即停止运动。
        但目前函数体为空,没有实际实现。

    用途:
        当需要紧急停止机器狗时,除了停止动作组执行,
        还应该停止所有舵机的当前运动。

    扩展:
        如果需要实现此功能,可以使用如下代码:
        for i in range(16):
            stopBusServo(i+1)
    """
    for i in range(16):
        pass
        # stopBusServo(i+1)


def action_finish():
    """
    查询动作组是否执行完毕

    功能说明:
        返回当前动作组的执行状态。
        用于判断一个非阻塞执行的动作组是否已经完成。

    返回值:
        True: 动作组已执行完毕,或者没有动作组在执行
        False: 动作组正在执行中

    使用场景:
        # 在执行非阻塞动作后,轮询等待完成
        runActionGroup("walk.d6a", wait=False)
        while not action_finish():
            time.sleep(0.1)
            # 可以在这里做一些其他事情

        # 或者判断是否可以开始下一个动作
        if action_finish():
            runActionGroup("turn_left.d6a")
    """
    global action_group_finish
    return action_group_finish


def runAction(actNum):
    """
    动作组执行的核心函数

    功能说明:
        这是执行动作组的实际逻辑函数。
        它从SQLite数据库文件读取动作帧,然后逐帧执行。

    参数说明:
        actNum: 动作组文件名,字符串类型
                可以是完整路径,也可以是相对于action_group_path的路径

    执行流程:
        1. 检查动作组文件是否存在
        2. 连接SQLite数据库
        3. 查询ActionGroup表的所有记录
        4. 逐帧读取并执行:
           - 读取执行时间和舵机角度/坐标值
           - 调用setServoPulse或逆运动学控制舵机
           - 等待指定的时间
        5. 循环直到所有帧执行完毕或收到停止信号

    动作帧类型判断:
        act[2]是第一个动作数据的类型:
        - int类型: 舵机角度模式(.d6a文件)
          数据格式: [Index, Time, Servo1, Servo2, ..., Servo11]
        - float类型: 坐标控制模式(.d6ac文件)
          数据格式: [Index, Time, C1, C2, ..., C12]

    坐标控制模式:
        12个坐标值对应4条腿的XYZ坐标:
        - 索引0-2:  右前腿(FR) 的 X, Y, Z
        - 索引3-5:  左前腿(FL) 的 X, Y, Z
        - 索引6-8:  右后腿(BR) 的 X, Y, Z
        - 索引9-11: 左后腿(BL) 的 X, Y, Z

        坐标值需要除以100转换单位(厘米转米)

    停止机制:
        stopRunning全局变量控制是否停止执行
        每一帧执行前都会检查这个标志

    使用示例:
        # 一般不直接调用这个函数,而是通过runActionGroup调用
        runAction("stand.d6a")
    """
    global runningAction
    global stopRunning
    global online_action_times

    # 空动作组检查
    if actNum is None:
        return

    # 拼接完整路径
    actNum = action_group_path + actNum

    # 重置停止标志
    stopRunning = False

    # 检查文件是否存在
    if os.path.exists(actNum) is True:
        # 检查是否有其他动作组在运行
        if runningAction is False:
            runningAction = True

            # 连接SQLite数据库
            ag = sql.connect(actNum)
            cu = ag.cursor()

            # 查询所有动作帧
            cu.execute("select * from ActionGroup")

            # 初始化舵机控制
            puppy.servo_force_run()
            time.sleep(0.01)

            # 逐帧执行动作
            while True:
                # 读取一帧数据
                act = cu.fetchone()

                # 检查停止标志
                if stopRunning is True:
                    stopRunning = False
                    break

                # 如果有数据,执行动作
                if act is not None:
                    # 判断动作帧类型
                    if type(act[2]) is int:
                        # 舵机角度模式: 直接设置舵机脉宽
                        # act[1]是时间,act[2:]是11个舵机的脉宽值
                        for i in range(0, len(act)-2, 1):
                            setServoPulse(i+1, act[2 + i], act[1])

                    elif type(act[2]) is float:
                        # 坐标控制模式: 先逆运动学求解,再控制舵机
                        # 读取12个坐标值
                        rotated_foot_locations = np.zeros(12)
                        for i in range(0, len(act)-2):
                            value = act[i+2]
                            rotated_foot_locations[i] = float(value)

                        # 重组为4x3矩阵(4条腿,每腿3个坐标)
                        rotated_foot_locations = rotated_foot_locations.reshape(4,3)

                        # 转置为3x4矩阵(3个坐标轴,4条腿)
                        rotated_foot_locations = rotated_foot_locations.T

                        # 厘米转米
                        rotated_foot_locations = rotated_foot_locations/100

                        # 逆运动学求解
                        joint_angles = puppy.fourLegsRelativeCoordControl(rotated_foot_locations)

                        # 发送关节角度给舵机
                        puppy.sendServoAngle(joint_angles, act[1])#, force_execute = True

                    # 等待本帧执行时间
                    time.sleep(float(act[1])/1000.0)
                else:
                    # 没有更多数据,动作组执行完毕
                    break

            # 标记动作组执行结束
            runningAction = False
            cu.close()
            ag.close()
    else:
        # 文件不存在
        runningAction = False
        print("未能找到动作组文件")


def online_thread_run_acting():
    """
    在线动作执行线程 - 支持循环次数控制

    功能说明:
        这是一个在后台持续运行的线程函数。
        它根据online_action_num和online_action_times来执行动作组。

    执行模式:
        1. online_action_times == 0: 无限循环执行
        2. online_action_times > 0: 执行指定次数后进入空载
        3. online_action_times == -1: 空载状态,不执行任何动作

    状态转换:
        空载 → (收到动作组) → 执行中 → (完成) → 空载
        或
        空载 → (收到动作组) → 执行中 → (无限循环)

    使用场景:
        这个函数配合change_action_value使用。
        通过change_action_value设置要执行的动作和次数,
        这个线程会自动执行。

    与runActionGroup的区别:
        - runActionGroup: 一次性执行,不支持循环
        - online_thread_run_acting: 支持循环次数控制

    注意:
        这个线程是守护线程(setDaemon=True)
        当主程序退出时,这个线程会自动终止
    """
    global online_action_times, online_action_num, update_ok, action_group_finish

    while True:
        if update_ok:
            if online_action_times == 0:
                # 无限次运行(run indefinitely)
                if action_group_finish:
                    action_group_finish = False
                runAction(online_action_num)

            elif online_action_times > 0:
                # 有次数运行(run for a specified number of times)
                if action_group_finish:
                    action_group_finish = False
                runAction(online_action_num)
                online_action_times -= 1    # 运行完成后,进入空载(enter idle state after execution)
                if online_action_times == 0:
                    online_action_times = -1  # 进入空载状态

            else:
                # 空载(no load)
                if not action_group_finish:
                    action_group_finish = True
                time.sleep(0.001)
        else:
            # update_ok为False,不更新动作
            if not action_group_finish:
                action_group_finish = True
            time.sleep(0.001)


def start_action_thread():
    """
    启动在线动作执行线程

    功能说明:
        启动一个后台守护线程来执行在线动作。
        这个函数应该在程序初始化时调用一次。

    线程特性:
        - 守护线程: 当主线程退出时,会自动终止
        - 持续运行: 线程启动后会一直循环,等待动作指令

    使用场景:
        # 在程序初始化时调用
        start_action_thread()

        # 然后可以通过以下方式控制动作
        change_action_value("walk.d6a", 5)  # 执行5次
        change_action_value("turn_left.d6a", 0)  # 无限循环
        stopActionGroup()  # 停止
    """
    th1 = threading.Thread(target=online_thread_run_acting)
    th1.setDaemon(True)  # 设置为后台线程,这里默认是True(set as background thread, by default, it is True here)
    th1.start()


def change_action_value(actNum, actTimes):
    """
    更改当前在线执行的动作组

    功能说明:
        更改当前要执行的动作组及其循环次数。
        配合start_action_thread启动的后台线程使用。

    参数说明:
        actNum: 动作组文件名
                例如: "stand.d6a", "walk_cycle.d6ac"

        actTimes: 执行次数
                  - 0: 无限循环执行
                  - 正整数: 执行指定次数后停止
                  - -1: 空载,不执行任何动作

    工作流程:
        1. 检查当前动作组是否执行完毕
        2. 如果执行完毕,设置新的动作组和次数
        3. 设置update_ok标志,通知后台线程开始执行

    使用示例:
        # 站立5次
        change_action_value("stand.d6a", 5)

        # 一直走路(无限循环)
        change_action_value("walk.d6a", 0)

        # 停止当前动作
        change_action_value(None, -1)

    与runActionGroup的区别:
        - runActionGroup: 会创建新线程执行,适合一次性任务
        - change_action_value: 配合后台线程,适合需要频繁切换动作的场景
    """
    global online_action_times, online_action_num, update_ok, stopRunning, action_group_finish

    # 只有当前没有动作在执行时才允许更新
    if action_group_finish:
        online_action_times = actTimes
        online_action_num = actNum
        stopRunning = False
        update_ok = True
