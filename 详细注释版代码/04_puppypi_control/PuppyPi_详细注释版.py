#!/usr/bin/env python3
# encoding: utf-8
"""
PuppyPi 机器狗控制软件 - 详细注释版

功能概述:
    这是一个基于PyQt5开发的四足机器狗图形化控制软件,提供以下核心功能:
    1. 舵机控制与校准 - 通过滑块和数值框实时控制多个舵机角度
    2. 动作组编辑 - 创建、保存、编辑机器狗的动作序列
    3. 坐标控制 - 通过XYZ坐标直接控制四条腿的空间位置
    4. 舵机调试工具 - 读取和设置舵机ID、偏差、温度限制、电压限制等参数
    5. 中英文界面切换

适用对象: 机器狗初学者、开发者、机器人爱好者

依赖库:
    - PyQt5: GUI界面开发
    - sqlite3: 动作组数据存储
    - numpy: 数值计算和坐标变换
    - cv2: 图像处理(备用)
    - threading: 多线程支持
    - servo_controller: 舵机控制驱动
    - action_group_control: 动作组执行控制
    - arm_kinematics: 手臂运动学逆解

硬件平台: 树莓派/嵌入式Linux设备 + 舵机控制器
"""

import os
import re
import cv2
import sys
import math
import time
import sqlite3
import threading
import resource_rc
from socket import *

from PuppyUi import Ui_Form
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
from PyQt5 import QtGui, QtWidgets
from PyQt5.QtSql import QSqlDatabase, QSqlQuery
from language import language

from servo_controller import *
from action_group_control import runActionGroup, stopActionGroup
from arm_kinematics.ArmMoveIK import *
import numpy as np
from common import Misc

WORKING_DIR = '/home/ubuntu/software/puppypi_control'
SERVO_MIDDLE_VALUE = 1500

from PuppyInstantiate import PuppyInstantiate as puppy



class MainWindow(QtWidgets.QWidget, Ui_Form):
    """
    主窗口类 - 继承自Qt Designer生成的Ui_Form界面类

    界面结构:
        Tab 1 (主控制标签页):
            - 左侧: 舵机角度控制面板 (11个舵机的滑块和数值框)
            - 右侧: 动作组编辑表格和播放控制
            - 底部: 动作组列表下拉框和运行/停止按钮

        Tab 2 (坐标控制标签页):
            - 12个坐标输入框 (4条腿 × 3个坐标轴XYZ)
            - 坐标动作组编辑表格
            - 坐标动作组播放控制

        Tab 3 (舵机调试标签页):
            - 舵机ID显示/设置
            - 偏差值调节
            - 温度限制设置
            - 角度范围设置
            - 电压范围设置
            - 当前位置显示
    """

    def __init__(self):
        """
        初始化函数 - 构建整个GUI界面

        初始化流程:
            1. 调用父类构造函数和setupUi生成界面
            2. 设置窗口图标和默认标签页
            3. 初始化舵机偏差显示
            4. 绑定所有滑块和按钮的信号槽
            5. 初始化动作组列表
            6. 设置坐标控制界面的默认值

        重要成员变量:
            - horizontalSliderServoDeviation: 11个偏差校准滑块
            - LineEditServo: 11个舵机角度数值输入框
            - horizontalSliderServo: 11个舵机角度控制滑块
            - doubleSpinBox_legs: 12个腿部坐标输入框
            - tableWidget: 动作组编辑表格(舵机角度模式)
            - tableWidget_Coord: 动作组编辑表格(坐标模式)
        """
        super(MainWindow, self).__init__()
        self.setupUi(self)
        self.setWindowIcon(QIcon(':/images/Puppy.png'))
        self.tabWidget.setCurrentIndex(0)  # 设置默认标签为第一个标签(set the default label to the first label)
        self.tableWidget.setSelectionBehavior(QAbstractItemView.SelectRows)  # 设置选中整行，若不设置默认选中单元格(set to select the entire row, if not set, cells are selected by default)
        self.message = QMessageBox()
        # self.timer = QTimer()
        self.ak = ArmIK()
        self.resetServos_ = False
        self.path = WORKING_DIR
        self.actdir = self.path + "/ActionGroups/"
        self.button_controlaction_clicked('refresh')
        self.button_control_action_coord_clicked(self.Button_Refresh_Coord.objectName())

        ########################主界面###############################

        # 偏差校准滑块和标签初始化
        # 硬件偏差补偿: 用于校准每个舵机的制造误差,使多个同型号舵机能运动到相同位置
        self.horizontalSliderServoDeviation = [self.horizontalSlider_deviation1, self.horizontalSlider_deviation2, self.horizontalSlider_deviation3
                                        , self.horizontalSlider_deviation4, self.horizontalSlider_deviation5, self.horizontalSlider_deviation6
                                        , self.horizontalSlider_deviation7, self.horizontalSlider_deviation8, self.horizontalSlider_deviation9
                                        , self.horizontalSlider_deviation10, self.horizontalSlider_deviation11]

        self.servoDeviationLabel = [self.label_d1, self.label_d2, self.label_d3, self.label_d4
                                , self.label_d5, self.label_d6, self.label_d7, self.label_d8
                                , self.label_d9, self.label_d10, self.label_d11]

        # 从硬件读取每个舵机的偏差值并显示到界面上
        # getServoDeviation(idx+1) 读取第idx+1号舵机的偏差值(-125到+125)
        for idx, ServoD in enumerate(self.horizontalSliderServoDeviation):
            d = getServoDeviation(idx + 1)
            ServoD.setValue(d)
            self.servoDeviationLabel[idx].setText(str(d))

        self.readDevOk = True

        # 将11个偏差滑块的值变化信号连接到偏差处理函数
        # 当用户拖动滑块时,自动保存偏差值到硬件
        self.horizontalSlider_deviation1.valueChanged.connect(lambda: self.servoDeviationValuechange(self.horizontalSlider_deviation1.objectName()))
        self.horizontalSlider_deviation2.valueChanged.connect(lambda: self.servoDeviationValuechange(self.horizontalSlider_deviation2.objectName()))
        self.horizontalSlider_deviation3.valueChanged.connect(lambda: self.servoDeviationValuechange(self.horizontalSlider_deviation3.objectName()))
        self.horizontalSlider_deviation4.valueChanged.connect(lambda: self.servoDeviationValuechange(self.horizontalSlider_deviation4.objectName()))
        self.horizontalSlider_deviation5.valueChanged.connect(lambda: self.servoDeviationValuechange(self.horizontalSlider_deviation5.objectName()))
        self.horizontalSlider_deviation6.valueChanged.connect(lambda: self.servoDeviationValuechange(self.horizontalSlider_deviation6.objectName()))
        self.horizontalSlider_deviation7.valueChanged.connect(lambda: self.servoDeviationValuechange(self.horizontalSlider_deviation7.objectName()))
        self.horizontalSlider_deviation8.valueChanged.connect(lambda: self.servoDeviationValuechange(self.horizontalSlider_deviation8.objectName()))
        self.horizontalSlider_deviation9.valueChanged.connect(lambda: self.servoDeviationValuechange(self.horizontalSlider_deviation9.objectName()))
        self.horizontalSlider_deviation10.valueChanged.connect(lambda: self.servoDeviationValuechange(self.horizontalSlider_deviation10.objectName()))
        self.horizontalSlider_deviation11.valueChanged.connect(lambda: self.servoDeviationValuechange(self.horizontalSlider_deviation11.objectName()))

        # 舵机角度数值输入框初始化
        # 设置整数验证器: 允许输入500-2500之间的整数(对应舵机PWM脉宽)
        self.LineEditServo = [self.lineEdit_servo1, self.lineEdit_servo2, self.lineEdit_servo3, self.lineEdit_servo4
                                , self.lineEdit_servo5, self.lineEdit_servo6, self.lineEdit_servo7, self.lineEdit_servo8
                                , self.lineEdit_servo9, self.lineEdit_servo10, self.lineEdit_servo11]

        for s in self.LineEditServo:
            s.setValidator(QIntValidator(500, 2500))

        # 滑竿同步对应文本框的数值,及滑竿控制相应舵机转动与valuechange函数绑定(synchronize the slider with the corresponding textbox value, and bind the slider control to the servo motor rotation with the valueChange function)

        # 11个舵机角度控制滑块
        # 滑块范围500-2500对应舵机PWM脉宽范围
        # 舵机中值1500对应90度(中立位置)
        self.horizontalSliderServo = [self.horizontalSlider_servo1, self.horizontalSlider_servo2, self.horizontalSlider_servo3
                                        , self.horizontalSlider_servo4, self.horizontalSlider_servo5, self.horizontalSlider_servo6
                                        , self.horizontalSlider_servo7, self.horizontalSlider_servo8, self.horizontalSlider_servo9
                                        , self.horizontalSlider_servo10, self.horizontalSlider_servo11]

        for s in self.horizontalSliderServo:
            s.setMinimum(500)
            s.setMaximum(2500)

        # 将11个舵机滑块的值变化信号连接到处理函数
        # 当滑块值改变时,同步更新数值框并控制对应舵机转动
        self.horizontalSlider_servo1.valueChanged.connect(lambda: self.horizontalSliderServoValuechange(self.horizontalSlider_servo1.objectName()))
        self.horizontalSlider_servo2.valueChanged.connect(lambda: self.horizontalSliderServoValuechange(self.horizontalSlider_servo2.objectName()))
        self.horizontalSlider_servo3.valueChanged.connect(lambda: self.horizontalSliderServoValuechange(self.horizontalSlider_servo3.objectName()))
        self.horizontalSlider_servo4.valueChanged.connect(lambda: self.horizontalSliderServoValuechange(self.horizontalSlider_servo4.objectName()))
        self.horizontalSlider_servo5.valueChanged.connect(lambda: self.horizontalSliderServoValuechange(self.horizontalSlider_servo5.objectName()))
        self.horizontalSlider_servo6.valueChanged.connect(lambda: self.horizontalSliderServoValuechange(self.horizontalSlider_servo6.objectName()))
        self.horizontalSlider_servo7.valueChanged.connect(lambda: self.horizontalSliderServoValuechange(self.horizontalSlider_servo7.objectName()))
        self.horizontalSlider_servo8.valueChanged.connect(lambda: self.horizontalSliderServoValuechange(self.horizontalSlider_servo8.objectName()))
        self.horizontalSlider_servo9.valueChanged.connect(lambda: self.horizontalSliderServoValuechange(self.horizontalSlider_servo9.objectName()))
        self.horizontalSlider_servo10.valueChanged.connect(lambda: self.horizontalSliderServoValuechange(self.horizontalSlider_servo10.objectName()))
        self.horizontalSlider_servo11.valueChanged.connect(lambda: self.horizontalSliderServoValuechange(self.horizontalSlider_servo11.objectName()))

        # self.chinese = True
        self.language = 'Chinese'

        # 语言切换 - 中文/英文单选按钮
        # toggled信号: 当radioButton被选中时触发
        # lambda传递radioButton对象本身,以便在处理函数中判断哪个被选中
        self.radioButton_zn.toggled.connect(lambda: self.LanguageSetting(self.radioButton_zn))
        self.radioButton_en.toggled.connect(lambda: self.LanguageSetting(self.radioButton_en))

        # 机械臂使能复选框
        # 选中时显示额外的3个舵机控制(机械臂)
        self.arm_en.toggled.connect(self.arm_state)
        self.radioButton_zn.setChecked(True)

        # 初始隐藏机械臂相关的控制滑块(舵机9,10,11)
        # 这些在arm_en被勾选后会显示
        self.widget_id9.hide()
        self.widget_id10.hide()
        self.widget_id11.hide()

        # tableWidget点击获取定位的信号与icon_position函数（添加运行图标）绑定(bind the signal for obtaining the positioning from the tableWidget click to the icon_position function (adding the running icon))
        self.tableWidget.pressed.connect(self.icon_position)

        # 动作组时间输入验证器: 允许20-30000ms的时间值
        # 这是因为舵机控制有最小时间要求,太短的动作无法正确执行
        self.lineEdit_time.setValidator(QIntValidator(20, 30000))

        # 将编辑动作组的按钮点击时的信号与button_editaction_clicked函数绑定(bind the signal for clicking the "Edit Action Group" button to the button_editaction_clicked function)
       # self.Button_ServoPowerDown.pressed.connect(lambda: self.button_editaction_clicked('servoPowerDown'))

        # 角度读取: 读取当前所有舵机角度,添加到动作组表格
        self.Button_AngularReadback.pressed.connect(lambda: self.button_editaction_clicked('angularReadback'))

        # 动作组编辑按钮: 添加、删除、删除全部、更新、插入、上移、下移
        self.Button_AddAction.pressed.connect(lambda: self.button_editaction_clicked('addAction'))
        self.Button_DelectAction.pressed.connect(lambda: self.button_editaction_clicked('delectAction'))
        self.Button_DelectAllAction.pressed.connect(lambda: self.button_editaction_clicked('delectAllAction'))
        self.Button_UpdateAction.pressed.connect(lambda: self.button_editaction_clicked('updateAction'))
        self.Button_InsertAction.pressed.connect(lambda: self.button_editaction_clicked('insertAction'))
        self.Button_MoveUpAction.pressed.connect(lambda: self.button_editaction_clicked('moveUpAction'))
        self.Button_MoveDownAction.pressed.connect(lambda: self.button_editaction_clicked('moveDownAction'))

        # 将运行及停止运行按钮点击的信号与button_runonline函数绑定(bind the signals for clicking the "Run" and "Stop" buttons to the button_runonline function)
        self.Button_Run.clicked.connect(lambda: self.button_run('run'))

        # 文件操作按钮: 打开、保存、串接动作组、下载偏差
        self.Button_OpenActionGroup.pressed.connect(lambda: self.button_flie_operate('openActionGroup'))
        self.Button_SaveActionGroup.pressed.connect(lambda: self.button_flie_operate('saveActionGroup'))
        # self.Button_ReadDeviation.pressed.connect(lambda: self.button_flie_operate('readDeviation'))
        self.Button_DownloadDeviation.pressed.connect(lambda: self.button_flie_operate('downloadDeviation'))
        self.Button_TandemActionGroup.pressed.connect(lambda: self.button_flie_operate('tandemActionGroup'))
        self.Button_ReSetServos.pressed.connect(lambda: self.button_re_clicked('reSetServos'))


        # 将控制动作的按钮点击的信号与action_control_clicked函数绑定(bind the signals for clicking the control action buttons to the action_control_clicked function)
        # 这些按钮控制动作组的运行: 删除单个、全部删除、运行、停止、刷新、退出
        self.Button_DelectSingle.pressed.connect(lambda: self.button_controlaction_clicked('delectSingle'))
        self.Button_AllDelect.pressed.connect(lambda: self.button_controlaction_clicked('allDelect'))
        self.Button_RunAction.pressed.connect(lambda: self.button_controlaction_clicked('runAction'))
        self.Button_StopAction.pressed.connect(lambda: self.button_controlaction_clicked('stopAction'))
        self.Button_Refresh.pressed.connect(lambda: self.button_controlaction_clicked('refresh'))
        self.Button_Quit.pressed.connect(lambda: self.button_controlaction_clicked('quit'))



        # self.devNew = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        self.dev_change = False
        self.totalTime = 0  # 动作组总时间(毫秒)
        self.row = 0

        # 初始化偏差标签显示
        for idx, ServoD in enumerate(self.horizontalSliderServoDeviation):
            self.servoDeviationLabel[idx].setText(str(ServoD.value()))


        #################################坐标控制界面1(coordinate control interface 1)#######################################
        # 坐标名称到索引的映射表
        # 用于将界面上12个坐标输入框与4条腿(FR右前、FL左前、BR右后、BL左后)关联
        # 每条腿有X(左右)、Y(前后)、Z(上下)三个方向的坐标
        self.coordNameToIndexTable = {'legFR_X':0, 'legFR_Y':1, 'legFR_Z':2,
                                        'legFL_X':3, 'legFL_Y':4, 'legFL_Z':5,
                                        'legBR_X':6, 'legBR_Y':7, 'legBR_Z':8,
                                        'legBL_X':9, 'legBL_Y':10, 'legBL_Z':11, }

        # 默认复位坐标值
        # 3行分别对应X、Y、Z坐标
        # 4列分别对应FR、FL、BR、BL四条腿
        # 单位是厘米,Z轴为负值表示向下运动
        self.default_reset_coord = np.array([[ 0.,  0., 0., 0.],
                                             [ 0.,  0., 0., 0.],
                                             [-10,   -10,  -10,   -10, ]])

        # 12个腿部坐标输入框的列表
        # 顺序: FR_X, FR_Y, FR_Z, FL_X, FL_Y, FL_Z, BR_X, BR_Y, BR_Z, BL_X, BL_Y, BL_Z
        self.doubleSpinBox_legs = [self.doubleSpinBox_legFR_X, self.doubleSpinBox_legFR_Y, self.doubleSpinBox_legFR_Z
                                , self.doubleSpinBox_legFL_X, self.doubleSpinBox_legFL_Y, self.doubleSpinBox_legFL_Z
                                , self.doubleSpinBox_legBR_X, self.doubleSpinBox_legBR_Y, self.doubleSpinBox_legBR_Z
                                , self.doubleSpinBox_legBL_X, self.doubleSpinBox_legBL_Y, self.doubleSpinBox_legBL_Z]

        # 初始化腿部坐标输入框的值
        for i,leg in enumerate(self.doubleSpinBox_legs):
            leg.setValue(self.default_reset_coord.T.flatten()[i])
            # Z轴范围: -15到-1(只能向下运动,防止向上撞坏机器)
            if '_Z' in leg.objectName():
                leg.setMinimum(-15)
                leg.setMaximum(-1)
            # X轴范围: -15到+15(左右移动范围)
            if '_X' in leg.objectName():
                leg.setMinimum(-15)
                leg.setMaximum(15)

        # 将12个坐标输入框的值变化信号连接到坐标处理函数
        # 当任一坐标改变时,自动计算逆运动学并更新所有舵机角度
        self.doubleSpinBox_legFL_X.valueChanged.connect(lambda: self.coordValueChange('legFL_X'))
        self.doubleSpinBox_legFL_Y.valueChanged.connect(lambda: self.coordValueChange('legFL_Y'))
        self.doubleSpinBox_legFL_Z.valueChanged.connect(lambda: self.coordValueChange('legFL_Z'))
        self.doubleSpinBox_legFR_X.valueChanged.connect(lambda: self.coordValueChange('legFR_X'))
        self.doubleSpinBox_legFR_Y.valueChanged.connect(lambda: self.coordValueChange('legFR_Y'))
        self.doubleSpinBox_legFR_Z.valueChanged.connect(lambda: self.coordValueChange('legFR_Z'))
        self.doubleSpinBox_legBL_X.valueChanged.connect(lambda: self.coordValueChange('legBL_X'))
        self.doubleSpinBox_legBL_Y.valueChanged.connect(lambda: self.coordValueChange('legBL_Y'))
        self.doubleSpinBox_legBL_Z.valueChanged.connect(lambda: self.coordValueChange('legBL_Z'))
        self.doubleSpinBox_legBR_X.valueChanged.connect(lambda: self.coordValueChange('legBR_X'))
        self.doubleSpinBox_legBR_Y.valueChanged.connect(lambda: self.coordValueChange('legBR_Y'))
        self.doubleSpinBox_legBR_Z.valueChanged.connect(lambda: self.coordValueChange('legBR_Z'))

        # 禁用键盘跟踪 - 防止微小的键盘输入被立即处理
        # 这样只有在用户按回车或焦点离开时才会触发值变化
        for s in self.doubleSpinBox_legs:
            s.setKeyboardTracking(False)

        # 坐标表格点击信号
        self.tableWidget_Coord.pressed.connect(self.icon_position_coord)

        # 坐标动作组文件操作按钮
        self.Button_SaveActionGroup_Coord.pressed.connect(lambda: self.button_flie_operate(self.Button_SaveActionGroup_Coord.objectName()))
        self.Button_OpenActionGroup_Coord.pressed.connect(lambda: self.button_flie_operate(self.Button_OpenActionGroup_Coord.objectName()))
        self.Button_TandemActionGroup_Coord.pressed.connect(lambda: self.button_flie_operate(self.Button_TandemActionGroup_Coord.objectName()))

        # 坐标动作组编辑按钮: 添加、更新、删除、删除全部、插入、上移、下移、运行
        self.Button_AddCoord.pressed.connect(lambda: self.button_editCoord_clicked(self.Button_AddCoord.objectName()))
        self.Button_UpdateCoord.pressed.connect(lambda: self.button_editCoord_clicked(self.Button_UpdateCoord.objectName()))
        self.Button_DelectCoord.pressed.connect(lambda: self.button_editCoord_clicked(self.Button_DelectCoord.objectName()))
        self.Button_DelectAllCoord.pressed.connect(lambda: self.button_editCoord_clicked(self.Button_DelectAllCoord.objectName()))
        self.Button_InsertCoord.pressed.connect(lambda: self.button_editCoord_clicked(self.Button_InsertCoord.objectName()))
        self.Button_Run_Coord.pressed.connect(lambda: self.button_editCoord_clicked(self.Button_Run_Coord.objectName()))
        self.Button_MoveUpCoord.pressed.connect(lambda: self.button_editCoord_clicked(self.Button_MoveUpCoord.objectName()))
        self.Button_MoveDownCoord.pressed.connect(lambda: self.button_editCoord_clicked(self.Button_MoveDownCoord.objectName()))

        # 将坐标运行及停止运行按钮点击的信号与button_run_coord_online函数绑定(bind the signals for clicking the coordinate run and stop buttons to the button_run_coord_online function)
        self.Button_Run_Coord.clicked.connect(lambda: self.button_run_coord(self.Button_Run_Coord.objectName()))
        self.Button_Reset_Coord.pressed.connect(lambda: self.button_reset_coord(self.Button_Reset_Coord.objectName()))

        # 将控制坐标动作的按钮点击的信号与action_control_clicked函数绑定(bind the signals for clicking the coordinate action control buttons to the action_control_clicked function)
        self.Button_DelectSingle_Coord.pressed.connect(lambda: self.button_control_action_coord_clicked(self.Button_DelectSingle_Coord.objectName()))
        self.Button_AllDelect_Coord.pressed.connect(lambda: self.button_control_action_coord_clicked(self.Button_AllDelect_Coord.objectName()))
        self.Button_RunAction_Coord.pressed.connect(lambda: self.button_control_action_coord_clicked(self.Button_RunAction_Coord.objectName()))
        self.Button_StopAction_Coord.pressed.connect(lambda: self.button_control_action_coord_clicked(self.Button_StopAction_Coord.objectName()))
        self.Button_Refresh_Coord.pressed.connect(lambda: self.button_control_action_coord_clicked(self.Button_Refresh_Coord.objectName()))

        self.totalTime_coord = 0
        self.mask_coordValueChange = False

        #################################副界面1(sub-interface 1)#######################################
        # 舵机调试面板的成员变量
        self.id = 0                          # 当前舵机ID
        self.dev = 0                         # 当前舵机偏差值
        self.servoTemp = 0                    # 温度限制值
        self.servoMin = 0                     # 角度最小值
        self.servoMax = 0                     # 角度最大值
        self.servoMinV = 0                    # 电压最小值
        self.servoMaxV = 0                    # 电压最大值
        self.servoMove = 0                    # 当前位置

        # 舵机调试面板的滑块信号绑定
        self.horizontalSlider_servoTemp.valueChanged.connect(lambda: self.horizontalSlider_valuechange('servoTemp'))
        self.horizontalSlider_servoMin.valueChanged.connect(lambda: self.horizontalSlider_valuechange('servoMin'))
        self.horizontalSlider_servoMax.valueChanged.connect(lambda: self.horizontalSlider_valuechange('servoMax'))
        self.horizontalSlider_servoMinV.valueChanged.connect(lambda: self.horizontalSlider_valuechange('servoMinV'))
        self.horizontalSlider_servoMaxV.valueChanged.connect(lambda: self.horizontalSlider_valuechange('servoMaxV'))
        self.horizontalSlider_servoMove.valueChanged.connect(lambda: self.horizontalSlider_valuechange('servoMove'))

        # 舵机调试面板的按钮信号绑定
        self.pushButton_read.pressed.connect(lambda: self.button_clicked('read'))
        self.pushButton_set.pressed.connect(lambda: self.button_clicked('set'))
        self.pushButton_default.pressed.connect(lambda: self.button_clicked('default'))
        self.pushButton_quit2.pressed.connect(lambda: self.button_clicked('quit2'))
        self.pushButton_resetPos.pressed.connect(lambda: self.button_clicked('resetPos'))

        # 偏差输入框验证器: 允许-125到+125的偏差值
        self.validator2 = QIntValidator(-125, 125)
        self.lineEdit_servoDev.setValidator(self.validator2)

        # Tab页切换信号
        self.tabWidget.currentChanged['int'].connect(self.tabchange)
        self.readOrNot = False

        # 初始化所有舵机角度为中值1500
        for s in self.LineEditServo:
            s.setText(str(SERVO_MIDDLE_VALUE))

        # 移除第三个tab(舵机调试工具页),后续根据需要可以添加回来
        self.tabWidget.removeTab(2)
        self.tabWidget.setCurrentIndex(0)

    def arm_state(self):
        """
        机械臂使能状态切换函数

        工作原理:
            当用户勾选"机械臂使能"复选框时,显示额外的3个舵机控制(舵机9,10,11)
            这些舵机用于控制机械臂的关节
            未使能时隐藏这些控制,避免误操作

        舵机分配(典型配置):
            - 舵机1-8: 四足狗的8个腿部关节(每条腿2个关节)
            - 舵机9-11: 机械臂的3个关节(可选配置)
        """
        if self.arm_en.isChecked():

            self.widget_id9.show()
            self.widget_id10.show()
            self.widget_id11.show()

        else:

            self.widget_id9.hide()
            self.widget_id10.hide()
            self.widget_id11.hide()

    def message_From(self, str):
        """
        消息弹窗函数 - 显示一个简单的信息提示框

        参数:
            str: 要显示的消息文本

        使用场景:
            - 操作成功/失败提示
            - 错误警告信息
            - 使用说明提示
        """
        try:
            QMessageBox.about(self, '', str)
            time.sleep(0.01)
        except:
            pass


    # 弹窗提示函数(pop-up window prompt function)
    def message_delect(self, str):
        """
        确认删除对话框 - 显示一个带确定/取消按钮的确认框

        参数:
            str: 确认框中的提示文本

        返回值:
            0: 用户点击了确定按钮
            1: 用户点击了取消按钮

        使用场景:
            - 删除动作组前的确认
            - 清除所有数据前的确认
            - 不可恢复操作前的二次确认
        """
        messageBox = QMessageBox()
        messageBox.setWindowTitle(' ')
        messageBox.setText(str)
        messageBox.addButton(QPushButton('OK'), QMessageBox.YesRole)
        messageBox.addButton(QPushButton('Cancel'), QMessageBox.NoRole)
        return messageBox.exec_()


    # 窗口退出(window exit)
    def closeEvent(self, e):
        """
        窗口关闭事件处理函数

        功能:
            - 用户点击窗口关闭按钮时调用
            - 清理相机资源
            - 退出程序

        参数:
            e: 关闭事件对象

        注意:
            这里会设置camera_ui_break标志,用于通知其他线程退出
        """
        # result = QMessageBox.question(self,
        #                             "关闭窗口提醒",
        #                             "exit?",
        #                             QMessageBox.Yes | QMessageBox.No,
        #                             QMessageBox.No)
        result = QMessageBox.Yes
        if result == QMessageBox.Yes:
            self.camera_ui = True
            self.camera_ui_break = True
            QWidget.closeEvent(self, e)

            # try:
            #     rospy.ServiceProxy('/puppy_control/set_running', SetBool)(True)
            # except rospy.ServiceException as e:
            #     print("Service call failed: %s"%e)
        else:
            e.ignore()

    def LanguageSetting(self, name):
        """
        语言设置函数 - 切换界面中英文显示

        参数:
            name: 触发该函数的单选按钮对象

        工作原理:
            - 根据哪个单选按钮被选中来设置语言
            - 调用PanelLanguage函数更新所有界面文本

        界面文本存储:
            所有界面文本存储在language字典中
            结构: language[类别][键名][语言] = 文本
        """
        if name.text() == '中文':
            self.language = 'Chinese'
        else:
            self.language = 'English'

        self.PanelLanguage(self.language)


    def keyPressEvent(self, event):
        """
        键盘按键事件处理 - Enter键快速复位所有舵机到中值

        工作原理:
            - 当用户按下Enter键且当前在主控制标签页时
            - 将所有11个舵机的角度设置为1500(中立位置)
            - 同时更新滑块和数值框的显示

        应用场景:
            - 快速将机器狗恢复到初始姿态
            - 紧急停止并复位
        """
        if (event.key() == 16777220 or event.key() == 16777221) and self.tabWidget.currentIndex() == 0:
            self.resetServos_ = True

            for idx, l in enumerate(self.LineEditServo):
                pulse = int(l.text())
                self.horizontalSliderServo[idx].setValue(pulse)
                setServoPulse(idx+1, pulse, SERVO_MIDDLE_VALUE)

            self.resetServos_ = False

    def tabchange(self):
        """
        Tab页切换事件处理

        工作原理:
            - 当用户切换到特定Tab页时显示提示信息
            - 主要用于舵机调试页的警告提示

        警告内容:
            调试单个舵机时请确保只连接一个舵机
            否则可能产生总线冲突
        """
        if self.tabWidget.currentIndex() == 2:
        # if self.tabWidget.getTabText(self.tabWidget.currentIndex()) == '舵机调试工具':
            # if self.chinese:
            #     self.message_From('使用此面板时，请确保只连接了一个舵机，否则会引起冲突！')
            # else:
            #     self.message_From('Before debugging servo,make sure that the servo controller is connected with ONE servo.Otherwise it may cause a conflict!')
            self.message_From(language['MessageBox']['tabchange'][self.language])

    # 滑竿同步对应文本框的数值,及滑竿控制相应舵机转动(synchronize the slider with the corresponding textbox value and control the corresponding servo motor rotation with the slider)
    def horizontalSliderServoValuechange(self, name):
        """
        舵机滑块值变化处理函数

        工作原理:
            1. 从滑块对象名称解析出舵机ID(最后1-2位数字)
            2. 获取滑块当前值
            3. 同步更新对应数值输入框
            4. 调用setServoPulse控制舵机转动到指定位置

        参数:
            name: 滑块的对象名称,格式如"horizontalSlider_servo1"

        舵机控制参数:
            - 舵机ID: 1-11
            - 脉宽值: 500-2500(对应舵机角度范围)
            - 时间: 20ms(控制响应速度)

        注意:
            resetServos_标志用于防止滑块回位时的递归调用
        """
        if not self.resetServos_:
            try:
                servoId = int(name[-2:])
            except:
                servoId = int(name[-1])

            servoAngle = str(self.horizontalSliderServo[servoId-1].value())
            self.LineEditServo[servoId-1].setText(servoAngle)
            setServoPulse(servoId, int(servoAngle), 20)


    def servoDeviationValuechange(self, name):
        """
        舵机偏差值变化处理函数

        功能:
            - 当用户调整某个舵机的偏差校准滑块时调用
            - 自动保存偏差值到硬件/配置文件

        偏差值范围: -125 到 +125
        用途: 补偿同型号舵机的制造误差

        参数:
            name: 滑块对象名称
        """
        try:
            servoId = int(name[-2:])
        except:
            servoId = int(name[-1])
        d = self.horizontalSliderServoDeviation[servoId-1].value()
        self.servoDeviationLabel[servoId-1].setText(str(d))
        #setServoPulse(servoId,self.horizontalSliderServo[servoId -1].value(),0)
        #time.sleep(0.03)
        setServoDeviation(servoId, d)


    def coordValueChange(self, name):
        """
        坐标值变化处理函数 - 核心逆运动学控制

        工作原理:
            1. 读取所有12个坐标输入框的值(4腿×3坐标)
            2. 将坐标值从厘米转换为米(除以100)
            3. 调用fourLegsRelativeCoordControl进行逆运动学计算
            4. 将计算出的关节角度发送给舵机

        坐标系统:
            - X轴: 机器狗左右方向(正右负左)
            - Y轴: 机器狗前后方向(正前负后)
            - Z轴: 机器狗上下方向(负值表示向下)

        参数:
            name: 触发变化的坐标名称(如'legFR_X')

        运动学流程:
            用户输入末端位置(XYZ)
                ↓
            逆运动学求解
                ↓
            得到各关节角度
                ↓
            舵机执行
        """
        if self.mask_coordValueChange:
            return

        # 读取所有12个坐标值,组织成3×4矩阵
        # 行0=X, 行1=Y, 行2=Z
        # 列0=FR, 列1=FL, 列2=BR, 列3=BL
        rotated_foot_locations = np.array(
            [[ self.doubleSpinBox_legFR_X.value(),  self.doubleSpinBox_legFL_X.value(), self.doubleSpinBox_legBR_X.value(), self.doubleSpinBox_legBL_X.value()],
            [self.doubleSpinBox_legFR_Y.value(),   self.doubleSpinBox_legFL_Y.value(),  self.doubleSpinBox_legBR_Y.value(),   self.doubleSpinBox_legBL_Y.value(), ],
            [self.doubleSpinBox_legFR_Z.value(),    self.doubleSpinBox_legFL_Z.value(),    self.doubleSpinBox_legBR_Z.value(),    self.doubleSpinBox_legBL_Z.value(),   ]])

        rotated_foot_locations = rotated_foot_locations/100

        # 逆运动学计算: 将末端位置转换为关节角度
        joint_angles = puppy.fourLegsRelativeCoordControl(rotated_foot_locations)
        puppy.servo_force_run()
        puppy.sendServoAngle(joint_angles)#, force_execute = True

        # msg = Polygon(list(map(Point32, rotated_foot_locations[0,:], rotated_foot_locations[1,:], rotated_foot_locations[2,:])))
        # self.fourLegsRelativeCoordControl_pub.publish(msg)


    def button_reset_coord(self, name):
        """
        坐标复位按钮处理函数

        功能:
            - 将所有12个坐标值恢复为默认值
            - 复位后躯干高度约为4cm(Z=-10)
            - 调用逆运动学控制机器狗恢复初始姿态
        """
        self.mask_coordValueChange = True

        # 恢复所有坐标为默认值
        for i, value in enumerate(self.default_reset_coord.T.flatten()) :
            self.doubleSpinBox_legs[i].setValue(float(value))

        # joint_angles = four_legs_inverse_kinematics_manual(reset/100,config)
        # hardware_interface.set_actuator_postions(joint_angles, 800)

        # 计算复位姿态的关节角度并执行
        joint_angles = puppy.fourLegsRelativeCoordControl(self.default_reset_coord/100)
        puppy.servo_force_run()
        puppy.sendServoAngle(joint_angles, 800)#, force_execute = True

        # 机械臂复位到初始位置
        self.ak.setPitchRangeMoving((8.3,0,4),500)
        time.sleep(0.5)
        self.mask_coordValueChange = False

    # 复位按钮点击事件(reset button click event)
    def button_re_clicked(self, name):
        """
        舵机复位按钮处理函数

        功能:
            - 将所有11个舵机的角度设置为1500(中立位置)
            - 复位时间1秒,保证平滑复位

        使用场景:
            - 紧急停止后的姿态恢复
            - 测试前初始化
        """
        self.resetServos_ = True
        if name == 'reSetServos':
            for idx, l in enumerate(self.LineEditServo):
                l.setText(str(SERVO_MIDDLE_VALUE))
                self.horizontalSliderServo[idx].setValue(SERVO_MIDDLE_VALUE)
                setServoPulse(idx+1, SERVO_MIDDLE_VALUE, 1000)

            self.resetServos_ = False

    # 选项卡选择标签状态，获取对应舵机数值(tab selection label state, retrieve corresponding servo values)
    def tabindex(self, index):
        """
        获取当前所有舵机角度值

        参数:
            index: Tab页索引(当前未使用)

        返回值:
            list: 11个舵机角度值的字符串列表
        """
        array = []
        for value in self.horizontalSliderServo:
            array.append(str(value.value()))
        return array

    def getIndexData(self, index):
        """
        获取动作组表格中指定行的数据

        参数:
            index: 行索引

        返回值:
            list: 该行的所有数据(从第3列开始,即跳过序号和时间为0)
        """
        data = []
        for j in range(2, self.tableWidget.columnCount()):
            data.append(str(self.tableWidget.item(index, j).text()))
        return data

    def getIndexDataCoord(self, index):
        """
        获取坐标动作组表格中指定行的数据

        参数:
            index: 行索引

        返回值:
            list: 该行的所有坐标数据
        """
        data = []
        for j in range(2, self.tableWidget_Coord.columnCount()):
            data.append(str(self.tableWidget_Coord.item(index, j).text()))
        return data

    # 往tableWidget表格添加一行数据的函数(function to add a row of data to the tableWidget table)
    def add_line(self, item, timer, servoPulse):
        """
        向动作组表格添加一行数据

        参数:
            item: 行索引
            timer: 执行时间(毫秒)
            servoPulse: 11个舵机的脉宽值列表

        表格列布局:
            列0: 运行图标按钮
            列1: 序号(自动编号)
            列2: 时间
            列3-13: 舵机1-11的脉宽值
        """
        self.tableWidget.setItem(item, 1, QtWidgets.QTableWidgetItem(str(item + 1)))
        self.tableWidget.setItem(item, 2, QtWidgets.QTableWidgetItem(timer))
        for i, value in enumerate(servoPulse):
            self.tableWidget.setItem(item, i+3, QtWidgets.QTableWidgetItem(value))

    def add_line_coord(self, item, time, coord):
        """
        向坐标动作组表格添加一行数据

        参数:
            item: 行索引
            time: 执行时间(毫秒)
            coord: 12个坐标值列表
        """
        self.tableWidget_Coord.setItem(item, 1, QtWidgets.QTableWidgetItem(str(item + 1)))
        self.tableWidget_Coord.setItem(item, 2, QtWidgets.QTableWidgetItem(time))
        for i, value in enumerate(coord):
            self.tableWidget_Coord.setItem(item, i+3, QtWidgets.QTableWidgetItem(value))

    def get_coord_array(self):
        """
        获取当前所有12个坐标输入框的值

        返回值:
            list: 12个坐标值的字符串列表
        """
        array = []
        for value in self.doubleSpinBox_legs:
            array.append(str(value.value()))
        return array

    # 在定位行添加运行图标按钮(add a run icon button to the row for positioning)
    def icon_position(self):
        """
        在动作组表格当前行添加运行图标按钮

        功能:
            - 在用户点击的行的第0列插入一个播放图标按钮
            - 移除其他行的图标按钮
            - 绑定图标按钮的点击事件到action_one
        """
        toolButton_run = QtWidgets.QToolButton()
        icon = QtGui.QIcon()
        icon.addPixmap(QtGui.QPixmap(":/images/index.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        toolButton_run.setIcon(icon)
        toolButton_run.setObjectName("toolButton_run")
        item = self.tableWidget.currentRow()
        self.tableWidget.setCellWidget(item, 0, toolButton_run)
        for i in range(self.tableWidget.rowCount()):
            if i != item:
                self.tableWidget.removeCellWidget(i, 0)
        toolButton_run.clicked.connect(self.action_one)

    def action_one(self):
        """
        单步执行动作组表格中当前行的动作

        功能:
            - 读取当前行所有舵机的目标角度
            - 控制所有舵机同时转动到目标位置
            - 同步更新滑块和数值框显示
        """
        self.resetServos_ = True
        item = self.tableWidget.currentRow()
        # alist = []
        try:
            timer = int(self.tableWidget.item(self.tableWidget.currentRow(), 2).text())

            for i in range(0, self.tableWidget.columnCount()-3):
                value = self.tableWidget.item(item, i+3).text()
                setServoPulse(i+1, int(value), timer)
                self.horizontalSliderServo[i].setValue(int(value))
                self.LineEditServo[i].setText(value)


        except BaseException as e:
            print(e)
            self.message_From(language['MessageBox']['action_one'][self.language])
            # if self.chinese:
            #     self.message_From('运行出错!')
            # else:
            #     self.message_From('Running error')
        self.resetServos_ = False

    def icon_position_coord(self):
        """
        在坐标动作组表格当前行添加运行图标按钮

        与icon_position类似,但用于坐标模式的表格
        """
        toolButton_run = QtWidgets.QToolButton()
        icon = QtGui.QIcon()
        icon.addPixmap(QtGui.QPixmap(":/images/index.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        toolButton_run.setIcon(icon)
        toolButton_run.setObjectName("toolButton_run")
        item = self.tableWidget_Coord.currentRow()
        self.tableWidget_Coord.setCellWidget(item, 0, toolButton_run)
        for i in range(self.tableWidget_Coord.rowCount()):
            if i != item:
                self.tableWidget_Coord.removeCellWidget(i, 0)
        toolButton_run.clicked.connect(self.action_one_coord)

    def action_one_coord(self):
        """
        单步执行坐标动作组表格中当前行的坐标动作

        功能:
            - 读取当前行所有坐标值
            - 更新坐标输入框显示
            - 调用逆运动学计算关节角度
            - 执行动作
        """
        self.resetServos_ = True
        item = self.tableWidget_Coord.currentRow()

        try:
            time = int(self.tableWidget_Coord.item(self.tableWidget_Coord.currentRow(), 2).text())
            self.mask_coordValueChange = True
            rotated_foot_locations = np.zeros(12)
            for i in range(0, self.tableWidget_Coord.columnCount()-3):
                value = self.tableWidget_Coord.item(item, i+3).text()
                self.doubleSpinBox_legs[i].setValue(float(value))
                rotated_foot_locations[i] = float(value)
            rotated_foot_locations = rotated_foot_locations.reshape(4,3)
            rotated_foot_locations = rotated_foot_locations.T
            rotated_foot_locations = rotated_foot_locations/100

            joint_angles = puppy.fourLegsRelativeCoordControl(rotated_foot_locations)
            puppy.servo_force_run()
            puppy.sendServoAngle(joint_angles, time)#, force_execute = True


            self.mask_coordValueChange = False
        except BaseException as e:
            print(e)
            self.message_From(language['MessageBox']['action_one_coord'][self.language])
            # if self.chinese:
            #     self.message_From('运行出错')
            # else:
            #     self.message_From('Running error')
        self.resetServos_ = False



    def button_editCoord_clicked(self, name):
        """
        坐标动作组编辑按钮处理函数

        支持的操作:
            - Button_AddCoord: 添加坐标到动作组
            - Button_DelectCoord: 删除当前坐标
            - Button_DelectAllCoord: 删除所有坐标
            - Button_UpdateCoord: 更新当前坐标
            - Button_InsertCoord: 插入新坐标
            - Button_MoveUpCoord: 上移坐标
            - Button_MoveDownCoord: 下移坐标

        参数:
            name: 触发按钮的对象名称
        """
        coordList = self.get_coord_array()
        RowCont = self.tableWidget_Coord.rowCount()
        item = self.tableWidget_Coord.currentRow()
        if name == self.Button_AddCoord.objectName():    # 添加坐标(add coordinates)
            if self.spinBox_run_coord_time.value() < 5:
                self.message_From(language['MessageBox']['Button_AddCoord'][self.language])
                # if self.chinese:
                #     self.message_From('运行时间必须大于5')
                # else:
                #     self.message_From('Run time must greater than 5')
                return
            self.tableWidget_Coord.insertRow(RowCont)    # 增加一行(add one row)
            self.tableWidget_Coord.selectRow(RowCont)    # 定位最后一行为选中行(set the last row as the selected row for positioning)
            self.add_line_coord(RowCont, str(self.spinBox_run_coord_time.value()), coordList)
            self.totalTime_coord += self.spinBox_run_coord_time.value()
            self.label_TotalTime_coord.setText(str((self.totalTime_coord)/1000.0))

        if name == self.Button_DelectCoord.objectName():    # 删除坐标(delete coordinates)
            if RowCont != 0:
                self.totalTime_coord -= int(self.tableWidget_Coord.item(item, 2).text())
                self.tableWidget_Coord.removeRow(item)  # 删除选定行(delete the selected row)
                self.label_TotalTime_coord.setText(str((self.totalTime_coord)/1000.0))
        if name == self.Button_DelectAllCoord.objectName():
            # result = self.message_delect('此操作会删除列表中的所有动作，是否继续？')
            result = self.message_delect(language['MessageBox']['Button_DelectAllCoord'][self.language])
            if result == 0:
                for i in range(RowCont):
                    self.tableWidget_Coord.removeRow(0)
                self.totalTime_coord = 0
                self.label_TotalTime_coord.setText(str(self.totalTime_coord))
            else:
                pass
        if name == self.Button_UpdateCoord.objectName():    # 更新坐标(update coordinates)
            if self.spinBox_run_coord_time.value() < 5:
                self.message_From(language['MessageBox']['Button_UpdateCoord'][self.language])

                # if self.chinese:
                #     self.message_From('运行时间必须大于5')
                # else:
                #     self.message_From('Run time must greater than 5')
                return

            self.add_line_coord(item, str(self.spinBox_run_coord_time.value()), coordList)
            self.totalTime_coord = 0
            for i in range(RowCont):
                self.totalTime_coord += int(self.tableWidget_Coord.item(i,2).text())
            self.label_TotalTime_coord.setText(str((self.totalTime_coord)/1000.0))
        if name == self.Button_InsertCoord.objectName():    # 插入坐标(insert the coordinate)
            if item == -1:
                return
            if self.spinBox_run_coord_time.value() < 5:
                self.message_From(language['MessageBox']['Button_InsertCoord'][self.language])

                # if self.chinese:
                #     self.message_From('运行时间必须大于5')
                # else:
                #     self.message_From('Run time must greater than 5')
                return

            self.tableWidget_Coord.insertRow(item)       # 插入一行(insert one row)
            self.tableWidget_Coord.selectRow(item)
            self.add_line_coord(item, str(self.spinBox_run_coord_time.value()), coordList)
            # self.totalTime += int(self.lineEdit_time.text())
            self.totalTime_coord += self.spinBox_run_coord_time.value()
            self.label_TotalTime_coord.setText(str((self.totalTime_coord)/1000.0))
        if name == self.Button_MoveUpCoord.objectName():
            if item == 0 or item == -1:
                return
            current_data = self.getIndexDataCoord(item)
            uplist_data = self.getIndexDataCoord(item - 1)
            # print(current_data)
            # print(uplist_data)
            self.add_line_coord(item - 1, current_data[0], current_data[1:])
            self.add_line_coord(item, uplist_data[0], uplist_data[1:])
            self.tableWidget_Coord.selectRow(item - 1)

        if name == self.Button_MoveDownCoord.objectName():
            if item == RowCont - 1:
                return
            current_data = self.getIndexDataCoord(item)
            downlist_data = self.getIndexDataCoord(item + 1)
            self.add_line_coord(item + 1, current_data[0], current_data[1:])
            self.add_line_coord(item, downlist_data[0], downlist_data[1:])
            self.tableWidget_Coord.selectRow(item + 1)

        for i in range(self.tableWidget_Coord.rowCount()):    #刷新编号值(refresh the number value)
            self.tableWidget_Coord.item(i , 1).setFlags(self.tableWidget_Coord.item(i , 1).flags() & ~Qt.ItemIsEditable)
            self.tableWidget_Coord.setItem(i,1,QtWidgets.QTableWidgetItem(str(i + 1)))

        self.icon_position_coord()

    # 编辑动作组按钮点击事件(edit action group button click event)
    def button_editaction_clicked(self, name):
        """
        动作组编辑按钮处理函数 - 核心动作创建功能

        支持的操作:
            - servoPowerDown: 舵机掉电
            - angularReadback: 角度回读(读取当前舵机角度添加到动作组)
            - addAction: 添加动作
            - delectAction: 删除动作
            - delectAllAction: 删除所有动作
            - updateAction: 更新动作
            - insertAction: 插入动作
            - moveUpAction: 上移动作
            - moveDownAction: 下移动作

        动作组数据结构:
            - 每个动作包含: 时间 + 11个舵机角度
            - 所有动作存储在tableWidget表格中
            - 动作组保存为.d6a文件(SQLite数据库格式)

        参数:
            name: 操作命令名称
        """
        servoPulseList = self.tabindex(self.tabWidget.currentIndex())
        RowCont = self.tableWidget.rowCount()
        item = self.tableWidget.currentRow()
        if name == 'servoPowerDown':
            for id in range(0, self.tableWidget.columnCount()-3):
                unloadServo(id+1)
            self.message_From(language['MessageBox']['servoPowerDown'][self.language])

            # if self.chinese:
            #     self.message_From('掉电成功')
            # else:
            #     self.message_From('success')
        if name == 'angularReadback':
            """
            角度回读功能:
                读取当前所有舵机的实际角度
                将这些角度值作为新的动作添加到动作组表格
                常用于手动调整姿态后快速创建动作
            """
            self.tableWidget.insertRow(RowCont)    # 增加一行(add one row)
            self.tableWidget.selectRow(RowCont)    # 定位最后一行为选中行(set the last row as the selected row for positioning)
            use_time = int(self.lineEdit_time.text())
            # data = [RowCont, str(use_time)]
            data = []
            for i in range(0, self.tableWidget.columnCount()-3):
                pulse = getServoPulse(i+1)
                if pulse is None:
                    return
                else:
                    data.append(str(pulse))
            if use_time < 5:
                if self.chinese:
                    self.message_From('运行时间必须大于5ms')
                else:
                    self.message_From('Run time must be greater than 5ms')
                return
            self.add_line(RowCont, str(use_time), data)
            self.totalTime += use_time
            self.label_TotalTime.setText(str((self.totalTime)/1000.0))
        if name == 'addAction':    # 添加动作
            if int(self.lineEdit_time.text()) < 5:
                self.message_From(language['MessageBox']['addAction'][self.language])

                # if self.chinese:
                #     self.message_From('运行时间必须大于5')
                # else:
                #     self.message_From('Run time must greater than 5')
                return
            self.tableWidget.insertRow(RowCont)    # 增加一行(add one row)
            self.tableWidget.selectRow(RowCont)    # 定位最后一行为选中行(set the last row as the selected row for positioning)
            self.add_line(RowCont, str(self.lineEdit_time.text()), servoPulseList)
            self.totalTime += int(self.lineEdit_time.text())
            self.label_TotalTime.setText(str((self.totalTime)/1000.0))
        if name == 'delectAction':    # 删除动作(delete action)
            if RowCont != 0:
                self.totalTime -= int(self.tableWidget.item(item, 2).text())
                self.tableWidget.removeRow(item)  # 删除选定行(delete selected row)
                self.label_TotalTime.setText(str((self.totalTime)/1000.0))
        if name == 'delectAllAction':
            # result = self.message_delect('此操作会删除列表中的所有动作，是否继续？')
            result = self.message_delect(language['MessageBox']['delectAllAction'][self.language])
            if result == 0:
                for i in range(RowCont):
                    self.tableWidget.removeRow(0)
                self.totalTime = 0
                self.label_TotalTime.setText(str(self.totalTime))
            else:
                pass
        if name == 'updateAction':    # 更新动作(update action)
            if int(self.lineEdit_time.text()) < 5:
                self.message_From(language['MessageBox']['updateAction'][self.language])

                # if self.chinese:
                #     self.message_From('运行时间必须大于5')
                # else:
                #     self.message_From('Run time must greater than 5')
                return

            self.add_line(item, str(self.lineEdit_time.text()), servoPulseList)
            self.totalTime = 0
            for i in range(RowCont):
                self.totalTime += int(self.tableWidget.item(i,2).text())
            self.label_TotalTime.setText(str((self.totalTime)/1000.0))
        if name == 'insertAction':    # 插入动作(insert action)
            if item == -1:
                return
            if int(self.lineEdit_time.text()) < 5:
                self.message_From(language['MessageBox']['updateAction'][self.language])

                # if self.chinese:
                #     self.message_From('运行时间必须大于5')
                # else:
                #     self.message_From('Run time must greater than 5')
                return

            self.tableWidget.insertRow(item)       # 插入一行(insert one row)
            self.tableWidget.selectRow(item)
            self.add_line(item, str(self.lineEdit_time.text()), servoPulseList)
            self.totalTime += int(self.lineEdit_time.text())
            self.label_TotalTime.setText(str((self.totalTime)/1000.0))
        if name == 'moveUpAction':
            if item == 0 or item == -1:
                return
            current_data = self.getIndexData(item)
            uplist_data = self.getIndexData(item - 1)
            self.add_line(item - 1, current_data[0], current_data[1:])
            self.add_line(item, uplist_data[0], uplist_data[1:])
            self.tableWidget.selectRow(item - 1)


        if name == 'moveDownAction':
            if item == RowCont - 1:
                return
            current_data = self.getIndexData(item)
            downlist_data = self.getIndexData(item + 1)
            self.add_line(item + 1, current_data[0], current_data[1:])
            self.add_line(item, downlist_data[0], downlist_data[1:])
            self.tableWidget.selectRow(item + 1)

        for i in range(self.tableWidget.rowCount()):    #刷新编号值(refresh number value)
            self.tableWidget.item(i , 1).setFlags(self.tableWidget.item(i , 1).flags() & ~Qt.ItemIsEditable)
            self.tableWidget.setItem(i,1,QtWidgets.QTableWidgetItem(str(i + 1)))
        self.icon_position()

    # 在线坐标运行按钮点击事件(online coordinate run button click event)
    def button_run_coord(self, name):
        """
        坐标动作组在线运行按钮处理函数

        功能:
            - 支持循环/单次运行模式
            - 使用QTimer定时器依次执行每个坐标动作
            - 实时更新当前运行到的行(高亮显示)

        循环模式(checkbox勾选):
            - 从当前行一直执行到最后一行
            - 执行完毕后从头开始循环

        单次模式:
            - 只执行一次,执行完毕后停止

        参数:
            name: 按钮对象名称
        """
        if self.tableWidget_Coord.rowCount() == 0:
            self.message_From(language['MessageBox']['Button_Run_Coord_Run'][self.language])

            # if self.chinese:
            #     self.message_From('请先添加动作!')
            # else:
            #     self.message_From('Add action first!')
        else:
            if self.Button_Run_Coord.text() == '运行' or self.Button_Run_Coord.text() == 'Run':
                # self.message_From(language['MessageBox']['Button_Run_Coord_Run'][self.language])

                if self.language == 'Chinese':
                    self.Button_Run_Coord.setText('停止')
                else:
                    self.Button_Run_Coord.setText('Stop')
                self.row = self.tableWidget_Coord.currentRow()
                self.tableWidget_Coord.selectRow(self.row)
                self.icon_position_coord()
                self.timer_coord = QTimer()
                self.timer_coord_time_list = [0]*self.row
                # self.action_online(self.row)
                # print("self.row",self.row)

                # 根据循环checkbox决定使用哪个定时器回调
                if self.checkBox_run_Coord_cycle.isChecked():
                    # 循环模式: 执行到最后一行后从头开始
                    for i in range(self.row, self.tableWidget_Coord.rowCount()):
                        s = self.tableWidget_Coord.item(i,2).text()
                        # self.timer_coord.start(int(s))       # 设置计时间隔并启动(set the timing interval and start)
                        self.timer_coord_time_list.append(int(s))
                    self.timer_coord.timeout.connect(self.operate1_coord)
                else:
                    # 单次模式: 执行到最后一行后停止
                    for i in range(self.row, self.tableWidget_Coord.rowCount()):
                        s = self.tableWidget_Coord.item(i,2).text()
                        # self.timer_coord.start(int(s))       # 设置计时间隔并启动(set the timing interval and start)
                        self.timer_coord_time_list.append(int(s))
                    self.timer_coord.timeout.connect(self.operate2_coord)
                self.action_one_coord()
                self.timer_coord.start(self.timer_coord_time_list[self.row])
            elif self.Button_Run_Coord.text() == '停止' or self.Button_Run_Coord.text() == 'Stop':
                self.timer_coord.stop()
                if self.language == 'Chinese':
                    self.Button_Run_Coord.setText('运行')
                else:
                    self.Button_Run_Coord.setText('Run')
                self.message_From(language['MessageBox']['Button_Run_Coord_Stop'][self.language])

                # if self.chinese:
                #     self.Button_Run_Coord.setText('运行')
                #     self.message_From('运行结束!')
                # else:
                #     self.Button_Run_Coord.setText('Run')
                #     self.message_From('Run over!')

    def operate1_coord(self):
        """
        坐标动作组循环运行定时器回调

        功能:
            - 当定时器超时时被调用
            - 自动选择下一行执行
            - 到达最后一行时返回第一行继续循环
        """
        item = self.tableWidget_Coord.currentRow()
        if item == self.tableWidget_Coord.rowCount() - 1:
            self.tableWidget_Coord.selectRow(self.row)
            # self.action_online(self.row)
            self.action_one_coord()
        else:
            self.tableWidget_Coord.selectRow(item + 1)
            # self.action_online(item + 1)
            self.action_one_coord()
        self.timer_coord.start(self.timer_coord_time_list[self.tableWidget_Coord.currentRow()])
        self.icon_position_coord()

    def operate2_coord(self):
        """
        坐标动作组单次运行定时器回调

        功能:
            - 当定时器超时时被调用
            - 自动选择下一行执行
            - 到达最后一行时停止并更新按钮文字
        """
        item = self.tableWidget_Coord.currentRow()
        if item == self.tableWidget_Coord.rowCount() - 1:
            self.timer_coord.stop()
            if self.language == 'Chinese':
                self.Button_Run_Coord.setText('运行')
            else:
                self.Button_Run_Coord.setText('Run')

            # if self.chinese:
            #     self.Button_Run_Coord.setText('运行')
            #     self.message_From('运行结束!')
            # else:
            #     self.Button_Run_Coord.setText('Run')
            #     self.message_From('Run over!')
            self.message_From(language['MessageBox']['Button_Run_Coord_Stop'][self.language])

        else:
            self.tableWidget_Coord.selectRow(item + 1)
            # self.action_online(item + 1)
            self.action_one_coord()
            self.timer_coord.start(self.timer_coord_time_list[self.tableWidget_Coord.currentRow()])
        self.icon_position_coord()

    # 在线运行按钮点击事件(online coordinate run button click event)
    def button_run(self, name):
        """
        动作组在线运行按钮处理函数

        功能:
            - 支持循环/单次运行模式
            - 使用QTimer定时器依次执行每个动作
            - 实时更新当前运行到的行

        与button_run_coord类似,但用于舵机角度模式的动作组

        参数:
            name: 按钮命令名称
        """
        if self.tableWidget.rowCount() == 0:
            self.message_From(language['MessageBox']['button_run'][self.language])

            # if self.chinese:
            #     self.message_From('请先添加动作!')
            # else:
            #     self.message_From('Add action first!')
        else:
            if name == 'run':
                if self.Button_Run.text() == '运行' or self.Button_Run.text() == 'Run':
                    if self.language == 'Chinese':
                        self.Button_Run.setText('停止')
                    else:
                        self.Button_Run.setText('Stop')
                    self.row = self.tableWidget.currentRow()
                    self.tableWidget.selectRow(self.row)
                    self.icon_position()
                    self.timer = QTimer()
                    self.timer_time_list = [0]*self.row
                    # self.action_online(self.row)
                    if self.checkBox.isChecked():
                        # 循环模式
                        for i in range(self.tableWidget.rowCount() - self.row):
                            s = self.tableWidget.item(i,2).text()
                            self.timer_time_list.append(int(s) )
                        self.timer.timeout.connect(self.operate1)
                        #     self.timer.start(int(s))       # 设置计时间隔并启动(set the timing interval and start)
                        # self.timer.timeout.connect(self.operate1)
                    else:
                        # 单次模式
                        for i in range(self.tableWidget.rowCount() - self.row):
                            s = self.tableWidget.item(i,2).text()
                            self.timer_time_list.append(int(s) )
                        self.timer.timeout.connect(self.operate2)
                    self.action_one()
                    self.timer.start(self.timer_time_list[self.row])
                        #     self.timer.start(int(s))       # 设置计时间隔并启动(set the timing interval and start)
                        # self.timer.timeout.connect(self.operate2)
                elif self.Button_Run.text() == '停止' or self.Button_Run.text() == 'Stop':
                    self.timer.stop()
                    if self.language == 'Chinese':
                        self.Button_Run.setText('运行')
                        # self.message_From('运行结束!')
                    else:
                        self.Button_Run.setText('Run')
                        # self.message_From('Run over!')
                    self.message_From(language['MessageBox']['Button_Run_Stop'][self.language])

    def operate1(self):
        """
        动作组循环运行定时器回调

        功能:
            - 定时器超时时被调用
            - 自动选择下一行执行
            - 到达最后一行时返回第一行继续循环
        """
        item = self.tableWidget.currentRow()
        if item == self.tableWidget.rowCount() - 1:
            self.tableWidget.selectRow(self.row)
            # self.action_online(self.row)
            self.action_one()
        else:
            self.tableWidget.selectRow(item + 1)
            # self.action_online(item + 1)
            self.action_one()
        self.timer.start(self.timer_time_list[self.tableWidget.currentRow()])
        self.icon_position()

    def operate2(self):
        """
        动作组单次运行定时器回调

        功能:
            - 定时器超时时被调用
            - 自动选择下一行执行
            - 到达最后一行时停止并更新按钮文字
        """
        item = self.tableWidget.currentRow()
        if item == self.tableWidget.rowCount() - 1:
            self.timer.stop()
            # if self.chinese:
            if self.language == 'Chinese':
                self.Button_Run.setText('运行')
                # self.message_From('运行结束!')
            else:
                self.Button_Run.setText('Run')
                # self.message_From('Run over!')
            self.message_From(language['MessageBox']['operate2'][self.language])

        else:
            self.tableWidget.selectRow(item + 1)
            # self.action_online(item + 1)
            self.action_one()
            self.timer.start(self.timer_time_list[self.tableWidget.currentRow()])
        self.icon_position()

    def action_online(self, item):
        """
        执行动作组表格中指定行的动作

        参数:
            item: 行索引

        注意:
            此函数目前被注释,实际使用action_one代替
        """
        try:
            time = int(self.tableWidget.item(item, 2).text())
            for j in range(0, self.tableWidget.columnCount()-3):
                # data.extend([j+1, int(self.tableWidget.item(item, j+3).text())])
                setServoPulse(j+1, int(self.tableWidget.item(item, j+3).text()), time)
        except Exception:
            self.timer.stop()
            # if self.chinese:
            if self.language == 'Chinese':
                self.Button_Run.setText('运行')
                # self.message_From('运行出错!')
            else:
                self.Button_Run.setText('Run')
                # self.message_From('Run error!')
            self.message_From(language['MessageBox']['action_online'][self.language])

    # 文件打开及保存按钮点击事件(file open and save button click event)
    def button_flie_operate(self, name):
        """
        文件操作按钮处理函数 - 核心数据持久化功能

        支持的操作:
            - openActionGroup: 打开.d6a动作组文件
            - saveActionGroup: 保存动作组到.d6a文件
            - downloadDeviation: 下载舵机偏差到硬件
            - tandemActionGroup: 串接动作组文件
            - openActionGroup_Coord/.d6ac: 打开坐标动作组
            - saveActionGroup_Coord/.d6ac: 保存坐标动作组
            - tandemActionGroup_Coord/.d6ac: 串接坐标动作组

        文件格式:
            - .d6a: 舵机角度模式的动作组(包含11个舵机脉宽值)
            - .d6ac: 坐标模式的动作组(包含12个坐标值)

        数据存储:
            使用SQLite数据库,表名为ActionGroup
            列: Index(自增主键), Time(执行时间), Servo1-11或C1-C12

        参数:
            name: 操作命令名称
        """
        try:
            if name == 'openActionGroup' or name == self.Button_OpenActionGroup_Coord.objectName():
                dig_o = QFileDialog()
                dig_o.setFileMode(QFileDialog.ExistingFile)
                if name == 'openActionGroup':
                    dig_o.setNameFilter('d6a Flies(*.d6a)')
                    openfile = dig_o.getOpenFileName(self, 'OpenFile', '', 'd6a Flies(*.d6a)')
                elif name == self.Button_OpenActionGroup_Coord.objectName():
                    dig_o.setNameFilter('d6a Flies(*.d6ac)')
                    openfile = dig_o.getOpenFileName(self, 'OpenFile', '', 'd6a Flies(*.d6ac)')
                # 打开单个文件(open single file)
                # 参数一：设置父组件；参数二：QFileDialog的标题(parameter 1: set the parent component; parameter 2: title of QFileDialog)
                # 参数三：默认打开的目录，"."点表示程序运行目录，/表示当前盘符根目录(parameter 3: default directory to open, "." indicates the program's running directory, "/" indicates the root directory of the current drive)
                # 参数四：对话框的文件扩展名过滤器Filter，比如使用 Image files(*.jpg *.gif) 表示只能显示扩展名为.jpg或者.gif文件(parameter 4: Filter for file extension of the dialog box, such as "Image files (*.jpg *.gif)" to only display files with the extension .jpg or .gif)
                # 设置多个文件扩展名过滤，使用双引号隔开；"All Files(*);;PDF Files(*.pdf);;Text Files(*.txt)"(set multiple file extension filters, separated by double quotes)
                path = openfile[0]
                try:
                    if path != '':
                        # 使用SQLite数据库读取动作组
                        rbt = QSqlDatabase.addDatabase("QSQLITE")
                        rbt.setDatabaseName(path)
                        if name == 'openActionGroup':
                            if rbt.open():
                                actgrp = QSqlQuery()
                                if (actgrp.exec("select * from ActionGroup ")):
                                    self.tableWidget.setRowCount(0)
                                    self.tableWidget.clearContents()
                                    self.totalTime = 0
                                    while (actgrp.next()):
                                        count = self.tableWidget.rowCount()
                                        self.tableWidget.setRowCount(count + 1)
                                        for i in range(self.tableWidget.columnCount()-1):
                                            self.tableWidget.setItem(count, i + 1, QtWidgets.QTableWidgetItem(str(actgrp.value(i))))
                                            if i == 1:
                                                self.totalTime += actgrp.value(i)
                                            self.tableWidget.update()
                                            self.tableWidget.selectRow(count)
                                        self.tableWidget.item(count , 1).setFlags(self.tableWidget.item(count , 1).flags() & ~Qt.ItemIsEditable)
                            self.icon_position()
                            rbt.close()
                            self.label_TotalTime.setText(str(self.totalTime/1000.0))
                        elif name == self.Button_OpenActionGroup_Coord.objectName():
                            if rbt.open():
                                actgrp = QSqlQuery()
                                if (actgrp.exec("select * from ActionGroup ")):
                                    self.tableWidget_Coord.setRowCount(0)
                                    self.tableWidget_Coord.clearContents()
                                    self.totalTime_coord = 0
                                    while (actgrp.next()):
                                        count = self.tableWidget_Coord.rowCount()
                                        self.tableWidget_Coord.setRowCount(count + 1)
                                        for i in range(self.tableWidget_Coord.columnCount()-1):

                                            self.tableWidget_Coord.setItem(count, i + 1, QtWidgets.QTableWidgetItem(str(actgrp.value(i))))
                                            if i == 1:
                                                self.totalTime_coord += actgrp.value(i)
                                            self.tableWidget_Coord.update()
                                            self.tableWidget_Coord.selectRow(count)
                                        self.tableWidget_Coord.item(count , 1).setFlags(self.tableWidget_Coord.item(count , 1).flags() & ~Qt.ItemIsEditable)
                            self.icon_position_coord()
                            rbt.close()
                            self.label_TotalTime_coord.setText(str(self.totalTime_coord/1000.0))
                except:
                    self.message_From(language['MessageBox']['button_flie_operate'][self.language])



            if name == 'saveActionGroup' or name == self.Button_SaveActionGroup_Coord.objectName():
                dig_s = QFileDialog()
                if name == 'saveActionGroup':
                    if self.tableWidget.rowCount() == 0:
                        self.message_From(language['MessageBox']['saveActionGroup'][self.language])

                        return
                    savefile = dig_s.getSaveFileName(self, 'Savefile', '', 'd6a Flies(*.d6a)')
                elif name == self.Button_SaveActionGroup_Coord.objectName():
                    if self.tableWidget_Coord.rowCount() == 0:
                        self.message_From(language['MessageBox']['Button_SaveActionGroup_Coord'][self.language])

                        return
                    savefile = dig_s.getSaveFileName(self, 'Savefile', '', 'd6a Flies(*.d6ac)')
                path = savefile[0]
                # 如果文件已存在,先删除
                if os.path.isfile(path):
                    os.system('sudo rm ' + path)

                if path != '':
                    # 根据文件扩展名选择数据库路径
                    if name == 'saveActionGroup':
                        if path[-4:] == '.d6a':conn = sqlite3.connect(path)
                        else:conn = sqlite3.connect(path + '.d6a')
                    elif name == self.Button_SaveActionGroup_Coord.objectName():
                        if path[-5:] == '.d6ac':conn = sqlite3.connect(path)
                        else:conn = sqlite3.connect(path + '.d6ac')

                    c = conn.cursor()
                    # 创建动作组表
                    if name == 'saveActionGroup':
                        execute_str = '''CREATE TABLE ActionGroup([Index] INTEGER PRIMARY KEY AUTOINCREMENT
                        NOT NULL ON CONFLICT FAIL
                        UNIQUE ON CONFLICT ABORT,
                        Time INT'''
                        for idx in range(len(self.horizontalSliderServo)):
                            execute_str = execute_str + ',Servo' + str(idx+1) + ' INT'
                        execute_str += ');'
                        c.execute(execute_str)



                        insert_sql_str_0 = "INSERT INTO ActionGroup(Time"
                        for idx in range(len(self.horizontalSliderServo)):
                            insert_sql_str_0 = insert_sql_str_0 + ' ,Servo' + str(idx+1)
                        insert_sql_str_0 += ') VALUES('
                        for i in range(self.tableWidget.rowCount()):
                            insert_sql_str = insert_sql_str_0
                            for j in range(2, self.tableWidget.columnCount()):
                                if j == self.tableWidget.columnCount() - 1:
                                    insert_sql_str += str(self.tableWidget.item(i, j).text())
                                else:
                                    insert_sql_str += str(self.tableWidget.item(i, j).text()) + ','

                            insert_sql_str += ");"
                            c.execute(insert_sql_str)
                    elif name == self.Button_SaveActionGroup_Coord.objectName():
                        # 创建坐标动作组表
                        c.execute('''CREATE TABLE ActionGroup([Index] INTEGER PRIMARY KEY AUTOINCREMENT
                        NOT NULL ON CONFLICT FAIL
                        UNIQUE ON CONFLICT ABORT,
                        Time INT,
                        C1 FLOAT,
                        C2 FLOAT,
                        C3 FLOAT,
                        C4 FLOAT,
                        C5 FLOAT,
                        C6 FLOAT,
                        C7 FLOAT,
                        C8 FLOAT,
                        C9 FLOAT,
                        C10 FLOAT,
                        C11 FLOAT,
                        C12 FLOAT);''')
                        for i in range(self.tableWidget_Coord.rowCount()):
                            insert_sql = "INSERT INTO ActionGroup(Time, C1, C2, C3, C4, C5, C6, C7, C8, C9, C10, C11, C12) VALUES("
                            for j in range(2, self.tableWidget_Coord.columnCount()):
                                if j == self.tableWidget_Coord.columnCount() - 1:
                                    insert_sql += str(self.tableWidget_Coord.item(i, j).text())
                                else:
                                    insert_sql += str(self.tableWidget_Coord.item(i, j).text()) + ','

                            insert_sql += ");"
                            c.execute(insert_sql)

                    conn.commit()
                    conn.close()
                    self.button_controlaction_clicked('refresh')
                    self.button_control_action_coord_clicked(self.Button_Refresh_Coord.objectName())


            if name == 'downloadDeviation':
                """
                下载偏差功能:
                    将界面上调整的偏差值保存到硬件/配置文件中
                    这样下次启动时自动加载偏差校准值
                """
                saveServoDeviation()
                self.message_From(language['MessageBox']['downloadDeviation'][self.language])

            if name == 'tandemActionGroup':
                """
                串接动作组功能:
                    打开一个动作组文件,将其动作追加到当前动作组表格后面
                    常用于组合多个基础动作创建复杂动作序列
                """
                dig_t = QFileDialog()
                dig_t.setFileMode(QFileDialog.ExistingFile)
                dig_t.setNameFilter('d6a Flies(*.d6a)')
                openfile = dig_t.getOpenFileName(self, 'OpenFile', '', 'd6a Flies(*.d6a)')
                # 打开单个文件(open single file)
                # 参数一：设置父组件；参数二：QFileDialog的标题(parameter 1: set parent component; parameter 2: the title of QFileDialog)
                # 参数三：默认打开的目录，"."点表示程序运行目录，/表示当前盘符根目录(parameter 3: default directory to open, "." indicates the program's running directory, "/" indicates the root directory of the current drive)
                # 参数四：对话框的文件扩展名过滤器Filter，比如使用 Image files(*.jpg *.gif) 表示只能显示扩展名为.jpg或者.gif文件(
                # Parameter 4: Filter for file extension of the dialog box, such as "Image files (*.jpg *.gif)" to only display files with the extension .jpg or .gif)
                # 设置多个文件扩展名过滤，使用双引号隔开；"All Files(*);;PDF Files(*.pdf);;Text Files(*.txt)"(set multiple file extension filters, separated by double quotes)
                path = openfile[0]
                try:
                    if path != '':
                        tbt = QSqlDatabase.addDatabase("QSQLITE")
                        tbt.setDatabaseName(path)
                        if tbt.open():
                            actgrp = QSqlQuery()
                            if (actgrp.exec("select * from ActionGroup ")):
                                while (actgrp.next()):
                                    count = self.tableWidget.rowCount()
                                    self.tableWidget.setRowCount(count + 1)
                                    for i in range(self.tableWidget.columnCount()-1):
                                        if i == 0:
                                            self.tableWidget.setItem(count, i + 1, QtWidgets.QTableWidgetItem(str(count + 1)))
                                        else:
                                            self.tableWidget.setItem(count, i + 1, QtWidgets.QTableWidgetItem(str(actgrp.value(i))))
                                        if i == 1:
                                            self.totalTime += actgrp.value(i)
                                        self.tableWidget.update()
                                        self.tableWidget.selectRow(count)
                                    self.tableWidget.item(count , 1).setFlags(self.tableWidget.item(count , 1).flags() & ~Qt.ItemIsEditable)
                        self.icon_position()
                        tbt.close()
                        self.label_TotalTime.setText(str(self.totalTime/1000.0))
                except:
                    self.message_From(language['MessageBox']['tandemActionGroup'][self.language])

                    # if self.chinese:
                    #     self.message_From('动作组错误')
                    # else:
                    #     self.message_From('Wrong action format')
            if name == self.Button_TandemActionGroup_Coord.objectName():
                dig_t = QFileDialog()
                dig_t.setFileMode(QFileDialog.ExistingFile)
                dig_t.setNameFilter('d6a Flies(*.d6ac)')
                openfile = dig_t.getOpenFileName(self, 'OpenFile', '', 'd6a Flies(*.d6ac)')

                path = openfile[0]
                try:
                    if path != '':
                        tbt = QSqlDatabase.addDatabase("QSQLITE")
                        tbt.setDatabaseName(path)
                        if tbt.open():
                            actgrp = QSqlQuery()
                            if (actgrp.exec("select * from ActionGroup ")):
                                while (actgrp.next()):
                                    count = self.tableWidget_Coord.rowCount()
                                    self.tableWidget_Coord.setRowCount(count + 1)
                                    for i in range(self.tableWidget_Coord.columnCount()-1):
                                        if i == 0:
                                            self.tableWidget_Coord.setItem(count, i + 1, QtWidgets.QTableWidgetItem(str(count + 1)))
                                        else:
                                            self.tableWidget_Coord.setItem(count, i + 1, QtWidgets.QTableWidgetItem(str(actgrp.value(i))))
                                        if i == 1:
                                            self.totalTime_coord += actgrp.value(i)
                                        self.tableWidget_Coord.update()
                                        self.tableWidget_Coord.selectRow(count)
                                    self.tableWidget_Coord.item(count , 1).setFlags(self.tableWidget_Coord.item(count , 1).flags() & ~Qt.ItemIsEditable)
                        self.icon_position_coord()
                        tbt.close()
                        self.label_TotalTime_coord.setText(str(self.totalTime_coord/1000.0))
                except:
                    self.message_From(language['MessageBox']['Button_TandemActionGroup_Coord'][self.language])

                    # if self.chinese:
                    #     self.message_From('动作组错误')
                    # else:
                    #     self.message_From('Wrong action format')
        except BaseException as e:
            print(e)

    def listActions(self, path, format = '.d6a'):
        """
        列出指定目录下所有动作组文件

        参数:
            path: 目录路径
            format: 文件扩展名过滤('.d6a'或'.d6ac')

        返回值:
            list: 动作组文件名列表(不含扩展名)
        """
        if not os.path.exists(path):
            os.mkdir(path)
        pathlist = os.listdir(path)
        actList = []

        for f in pathlist:
            if f[0] == '.':
                pass
            else:
                if format == '.d6a':
                    if f[-4:] == format:
                        f.replace('-', '')
                        if f:
                            actList.append(f[0:-4])
                elif format == '.d6ac':
                    if f[-5:] == format:
                        f.replace('-', '')
                        if f:
                            actList.append(f[0:-5])
        return actList

    def refresh_action(self):
        """
        刷新动作组下拉列表

        功能:
            - 扫描ActionGroups目录
            - 更新comboBox_action下拉框
            - 显示所有可用的.d6a动作组文件
        """
        actList = self.listActions(self.actdir)
        actList.sort()

        if len(actList) != 0:
            self.comboBox_action.clear()
            for i in range(0, len(actList)):
                self.comboBox_action.addItem(actList[i])
        else:
            self.comboBox_action.clear()

    def refresh_action_coord(self):
        """
        刷新坐标动作组下拉列表

        功能:
            - 扫描ActionGroups目录
            - 更新comboBox_action_Coord下拉框
            - 显示所有可用的.d6ac坐标动作组文件
        """
        actList = self.listActions(self.actdir,'.d6ac')
        actList.sort()

        if len(actList) != 0:
            self.comboBox_action_Coord.clear()
            for i in range(0, len(actList)):
                self.comboBox_action_Coord.addItem(actList[i])
        else:
            self.comboBox_action_Coord.clear()


    # 控制动作组按钮点击事件(control action group button click event)
    def button_controlaction_clicked(self, name):
        """
        动作组控制按钮处理函数

        支持的操作:
            - delectSingle: 删除当前选中的动作组文件
            - allDelect: 删除所有动作组文件
            - runAction: 运行选中的动作组
            - stopAction: 停止当前运行的动作组
            - refresh: 刷新动作组列表
            - quit: 退出程序

        参数:
            name: 操作命令名称
        """
        if name == 'delectSingle':
            if str(self.comboBox_action.currentText()) != "":
                os.remove(self.actdir + str(self.comboBox_action.currentText()) + ".d6a")
                self.refresh_action()
        if name == 'allDelect':
            # result = self.message_delect('此操作会删除所有动作组，是否继续？')
            result = self.message_delect(language['MessageBox']['allDelect'][self.language])

            if result == 0:
                actList = self.listActions(self.actdir)
                for d in actList:
                    os.remove(self.actdir + d + '.d6a')
            else:
                pass
            self.refresh_action()
        if name == 'runAction':   # 动作组运行(action group running)
            runActionGroup(self.comboBox_action.currentText() + '.d6a')
        if name == 'stopAction':   # 停止运行(stop running)
            stopActionGroup()
        if name == 'refresh':
            self.refresh_action()
        if name == 'quit':
            self.camera_ui = True
            self.camera_ui_break = True
            try:
                self.cap.release()
            except:
                pass
            sys.exit()

    def button_control_action_coord_clicked(self, name):
        """
        坐标动作组控制按钮处理函数

        与button_controlaction_clicked类似,但用于坐标动作组(.d6ac)

        参数:
            name: 按钮对象名称
        """
        if name == self.Button_DelectSingle_Coord.objectName():
            if str(self.comboBox_action_Coord.currentText()) != "":
                os.remove(self.actdir + str(self.comboBox_action_Coord.currentText()) + ".d6ac")
                self.refresh_action_coord()
        if name == self.Button_AllDelect_Coord.objectName():
            # result = self.message_delect('此操作会删除所有动作组，是否继续？')
            result = self.message_delect(language['MessageBox']['allDelect'][self.language])

            if result == 0:
                actList = self.listActions(self.actdir,format = '.d6ac')
                for d in actList:
                    os.remove(self.actdir + d + '.d6ac')
            else:
                pass
            self.refresh_action_coord()
        if name == self.Button_RunAction_Coord.objectName():   # 动作组运行(action group running)
            runActionGroup(self.comboBox_action_Coord.currentText()+'.d6ac')
        if name == self.Button_StopAction_Coord.objectName():   # 停止运行(stop running)
            stopActionGroup()
        if name == self.Button_Refresh_Coord.objectName():
            self.refresh_action_coord()

    ################################################################################################
    def horizontalSlider_valuechange(self, name):
        """
        舵机调试面板滑块值变化处理函数

        参数:
            name: 滑块名称

        调试面板功能:
            - servoTemp: 设置舵机温度限制(显示℃)
            - servoMin: 设置最小角度限制
            - servoMax: 设置最大角度限制
            - servoMinV: 设置最小电压限制(显示V)
            - servoMaxV: 设置最大电压限制(显示V)
            - servoMove: 实时控制舵机位置
        """
        if name == 'servoTemp':
            self.temp = str(self.horizontalSlider_servoTemp.value())
            self.label_servoTemp.setText(self.temp + '℃')
        if name == 'servoMin':
            self.servoMin = str(self.horizontalSlider_servoMin.value())
            self.label_servoMin.setText(self.servoMin)
        if name == 'servoMax':
            self.servoMax = str(self.horizontalSlider_servoMax.value())
            self.label_servoMax.setText(self.servoMax)
        if name == 'servoMinV':
            self.servoMinV = str(self.horizontalSlider_servoMinV.value()/10)
            self.label_servoMinV.setText(self.servoMinV + 'V')
        if name == 'servoMaxV':
            self.servoMaxV = str(self.horizontalSlider_servoMaxV.value()/10)
            self.label_servoMaxV.setText(self.servoMaxV + 'V')
        if name == 'servoMove':
            self.servoMove = str(self.horizontalSlider_servoMove.value())
            self.label_servoMove.setText(self.servoMove)
            setServoPulse(self.id, int(self.servoMove), 0)

    def button_clicked(self, name):
        """
        舵机调试面板按钮处理函数

        支持的操作:
            - read: 读取当前舵机所有参数
            - set: 设置舵机参数
            - default: 恢复默认参数
            - quit2: 退出程序
            - resetPos: 复位舵机位置到中值

        参数:
            name: 按钮命令名称
        """
        if name == 'read':
            """
            读取功能:
                读取并显示舵机的以下信息:
                - ID、偏差、位置
                - 温度限制
                - 角度限制
                - 电压限制
                - 当前电压、温度
            """
            try:
                self.id = getBusServoID()
                if self.id is None:
                    if self.chinese:
                        self.message_From('读取id失败')
                    else:
                        self.message_From('Failed to read ID')
                    return
                self.readOrNot = True
                self.dev = getBusServoDeviation(self.id)
                if self.dev > 125:
                    self.dev = -(0xff-(self.dev - 1))
                self.servoTemp = getBusServoTempLimit(self.id)
                (self.servoMin, self.servoMax) = getBusServoAngleLimit(self.id)
                (self.servoMinV, self.servoMaxV) = getBusServoVinLimit(self.id)
                self.servoMove = getServoPulse(self.id)

                currentVin = getBusServoVin(self.id)

                currentTemp = getBusServoTemp(self.id)

                self.lineEdit_servoID.setText(str(self.id))
                self.lineEdit_servoDev.setText(str(self.dev))

                self.horizontalSlider_servoTemp.setValue(self.servoTemp)
                self.horizontalSlider_servoMin.setValue(self.servoMin)
                self.horizontalSlider_servoMax.setValue(self.servoMax)
                MinV = self.servoMinV
                MaxV = self.servoMaxV
                self.horizontalSlider_servoMinV.setValue(int(MinV/100))
                self.horizontalSlider_servoMaxV.setValue(int(MaxV/100))

                self.label_servoCurrentP.setText(str(self.servoMove))
                self.label_servoCurrentV.setText(str(round(currentVin/1000.0, 2)) + 'V')
                self.label_servoCurrentTemp.setText(str(currentTemp) + '℃')

                self.horizontalSlider_servoMove.setValue(self.servoMove)
            except:
                if self.chinese:
                    self.message_From('读取超时')
                else:
                    self.message_From('Read timeout')
                return
            if self.chinese:
                self.message_From('读取成功')
            else:
                self.message_From('success')

        if name == 'set':
            """
            设置功能:
                将界面上的参数写入舵机:
                - ID、偏差
                - 温度限制
                - 角度限制
                - 电压限制
                - 位置
            """
            if self.readOrNot is False:
                if self.chinese:
                    self.message_From('请先读取，否则无法获取舵机信息，从而进行设置！')
                else:
                    self.message_From('Read first！')
                return
            id = self.lineEdit_servoID.text()
            if id == '':
                if self.chinese:
                    self.message_From('舵机id参数为空，无法设置')
                else:
                    self.message_From('Please input id')
                return
            dev = self.lineEdit_servoDev.text()
            if dev == '':
                dev = 0
            dev = int(dev)
            if dev > 125 or dev < -125:
                if self.chinese:
                    self.message_From('偏差参数超出可调节范围-125～125，无法设置')
                else:
                    self.message_From('Deviation out of range -125~125')
                return
            temp = self.horizontalSlider_servoTemp.value()
            pos_min = self.horizontalSlider_servoMin.value()
            pos_max = self.horizontalSlider_servoMax.value()
            if pos_min > pos_max:
                if self.chinese:
                    self.message_From('舵机范围参数错误，无法设置')
                else:
                    self.message_From('Wrong angle range')
                return
            vin_min = self.horizontalSlider_servoMinV.value()
            vin_max = self.horizontalSlider_servoMaxV.value()
            if vin_min > vin_max:
                if self.chinese:
                    self.message_From('舵机电压范围参数错误，无法设置')
                else:
                    self.message_From('Wrong voltage range')
                return
            pos = self.horizontalSlider_servoMove.value()

            id = int(id)

            try:
                setBusServoID(self.id, id)
                time.sleep(0.01)
                if getBusServoID() != id:
                    if self.chinese:
                        self.message_From('id设置失败！')
                    else:
                        self.message_From('failed！')
                    return
                setBusServoDeviation(id, dev)
                time.sleep(0.01)
                saveServoDeviation(id)
                time.sleep(0.01)
                d = getBusServoDeviation(id)
                if d > 125:
                    d = -(0xff-(d - 1))
                if d != dev:
                    if self.chinese:
                        self.message_From('偏差设置失败！')
                    else:
                        self.message_From('failed！')
                    return
                setBusServoMaxTemp(id, temp)
                time.sleep(0.01)
                if getBusServoTempLimit(id) != temp:
                    if self.chinese:
                        self.message_From('温度设置失败！')
                    else:
                        self.message_From('failed！')

                    return
                setBusServoAngleLimit(id, pos_min, pos_max)
                time.sleep(0.01)
                if getBusServoAngleLimit(id) != (pos_min, pos_max):
                    if self.chinese:
                        self.message_From('角度范围设置失败！')
                    else:
                        self.message_From('failed！')
                    return
                setBusServoVinLimit(id, vin_min*100, vin_max*100)
                time.sleep(0.01)
                if getBusServoVinLimit(id) != (vin_min*100, vin_max*100):
                    if self.chinese:
                        self.message_From('电压范围设置失败！')
                    else:
                        self.message_From('failed！')
                    return
                setServoPulse(id, pos, 0)
            except:
                if self.chinese:
                    self.message_From('设置超时!')
                else:
                    self.message_From('Timeout!')
                return

            self.message_From('设置成功')

        if name == 'default':
            """
            恢复默认功能:
                将舵机参数恢复为出厂默认值:
                - ID=1
                - 偏差=0
                - 温度限制=85℃
                - 角度限制=0-1000
                - 电压限制=4.5-12V
                - 位置=1500(中值)
            """
            if self.readOrNot is False:
                if self.chinese:
                    self.message_From('请先读取，否则无法获取舵机信息，从而进行设置！')
                else:
                    self.message_From('Read first！')
                return
            try:
                setBusServoID(self.id, 1)
                time.sleep(0.01)
                if getBusServoID() != 1:
                    if self.chinese:
                        self.message_From('id设置失败！')
                    else:
                        self.message_From('failed！')
                    return
                setBusServoDeviation(1, 0)
                time.sleep(0.01)
                saveServoDeviation(1)
                time.sleep(0.01)
                if getBusServoDeviation(1) != 0:
                    if self.chinese:
                        self.message_From('偏差设置失败！')
                    else:
                        self.message_From('failed！')
                    return
                setBusServoMaxTemp(1, 85)
                time.sleep(0.01)
                if getBusServoTempLimit(1) != 85:
                    if self.chinese:
                        self.message_From('温度设置失败！')
                    else:
                        self.message_From('failed！')
                    return
                setBusServoAngleLimit(1, 0, 1000)
                time.sleep(0.01)
                if getBusServoAngleLimit(1) != (0, 1000):
                    if self.chinese:
                        self.message_From('角度范围设置失败！')
                    else:
                        self.message_From('failed！')
                    return
                setBusServoVinLimit(1, 4500, 12000)
                time.sleep(0.01)
                if getBusServoVinLimit(1) != (4500, 12000):
                    if self.chinese:
                        self.message_From('电压范围设置失败！')
                    else:
                        self.message_From('failed！')
                    return
                setServoPulse(1, SERVO_MIDDLE_VALUE, 0)
            except:
                if self.chinese:
                    self.message_From('设置超时!')
                else:
                    self.message_From('Timeout!')
                return
            if self.chinese:
                self.message_From('设置成功')
            else:
                self.message_From('success')
        if name == 'quit2':
            self.camera_ui = True
            self.camera_ui_break = True
            try:
                self.cap.release()
            except:
                pass
            sys.exit()
        if name == 'resetPos':
            """
            复位位置功能:
                将当前舵机位置设置为中值1500
                用于将舵机恢复到中立位置
            """
            self.horizontalSlider_servoMove.setValue(SERVO_MIDDLE_VALUE)
            setServoPulse(self.id, SERVO_MIDDLE_VALUE, 0)

    def PanelLanguage(self, lang):
        """
        界面语言更新函数

        功能:
            根据选择的语言更新界面上所有文本
            文本存储在language字典中

        参数:
            lang: 语言标识('Chinese'或'English')
        """
        _translate = QCoreApplication.translate

        # 更新界面上所有文本
        # 这是一个非常大的字典,包含所有界面元素的文本
        self.arm_en.setText(_translate("Form", language['arm_en'][lang]))
        self.label_action.setText(_translate("Form", language['label_action'][lang]))
        self.Button_DelectSingle.setText(_translate("Form", language['Button_DelectSingle'][lang]))
        self.Button_AllDelect.setText(_translate("Form", language['Button_AllDelect'][lang]))
        self.Button_RunAction.setText(_translate("Form", language['Button_RunAction'][lang]))
        self.Button_StopAction.setText(_translate("Form", language['Button_StopAction'][lang]))
        self.Button_Quit.setText(_translate("Form", language['Button_Quit'][lang]))
        self.Button_Refresh.setText(_translate("Form", language['Button_Refresh'][lang]))
        self.checkBox.setText(_translate("Form", language['checkBox'][lang]))
        self.Button_Run.setText(_translate("Form", language['Button_Run'][lang]))
        self.Button_DownloadDeviation.setText(_translate("Form", language['Button_DownloadDeviation'][lang]))
        self.Button_ReSetServos.setText(_translate("Form", language['Button_ReSetServos'][lang]))
       # self.Button_ServoPowerDown.setText(_translate("Form", language['Button_ServoPowerDown'][lang]))
        self.tableWidget.horizontalHeaderItem(1).setText(_translate("Form", language['tableWidget.horizontalHeaderItem(1)'][lang]))
        self.tableWidget.horizontalHeaderItem(2).setText(_translate("Form", language['tableWidget.horizontalHeaderItem(2)'][lang]))
        self.Button_OpenActionGroup.setText(_translate("Form", language['Button_OpenActionGroup'][lang]))
        self.Button_SaveActionGroup.setText(_translate("Form", language['Button_SaveActionGroup'][lang]))
        self.Button_TandemActionGroup.setText(_translate("Form", language['Button_TandemActionGroup'][lang]))
        self.label_time.setText(_translate("Form", language['label_time'][lang]))
        self.Button_AddAction.setText(_translate("Form", language['Button_AddAction'][lang]))
        self.Button_DelectAction.setText(_translate("Form", language['Button_DelectAction'][lang]))
        self.Button_UpdateAction.setText(_translate("Form", language['Button_UpdateAction'][lang]))
        self.Button_InsertAction.setText(_translate("Form", language['Button_InsertAction'][lang]))
        self.Button_MoveUpAction.setText(_translate("Form", language['Button_MoveUpAction'][lang]))
        self.Button_MoveDownAction.setText(_translate("Form", language['Button_MoveDownAction'][lang]))
        self.label_time_2.setText(_translate("Form", language['label_time_2'][lang]))
        self.Button_DelectAllAction.setText(_translate("Form", language['Button_DelectAllAction'][lang]))
        self.label_servoL_1.setText(_translate("Form", language['label_servoL_1'][lang]))
        self.label_servoR_1.setText(_translate("Form", language['label_servoR_1'][lang]))
        self.label_servoL_5.setText(_translate("Form", language['label_servoL_5'][lang]))
        self.label_servoR_5.setText(_translate("Form", language['label_servoR_5'][lang]))
        self.label_servoR_6.setText(_translate("Form", language['label_servoR_6'][lang]))
        self.label_servoL_6.setText(_translate("Form", language['label_servoL_6'][lang]))
        self.radioButton_zn.setText(_translate("Form", "中文"))
        self.radioButton_en.setText(_translate("Form", "English"))
        self.label_servoL_2.setText(_translate("Form", language['label_servoL_2'][lang]))
        self.label_servoR_2.setText(_translate("Form", language['label_servoR_2'][lang]))

        self.label_servoL_9.setText(_translate("Form", language['label_servoL_9'][lang]))
        self.label_servoR_9.setText(_translate("Form", language['label_servoR_9'][lang]))
        self.label_servoL_10.setText(_translate("Form", language['label_servoL_10'][lang]))
        self.label_servoR_10.setText(_translate("Form", language['label_servoR_10'][lang]))
        self.label_servoL_11.setText(_translate("Form", language['label_servoL_11'][lang]))
        self.label_servoR_11.setText(_translate("Form", language['label_servoR_11'][lang]))
        self.label_servoL_7.setText(_translate("Form", language['label_servoL_7'][lang]))
        self.label_servoR_7.setText(_translate("Form", language['label_servoR_7'][lang]))
        self.label_servoR_3.setText(_translate("Form", language['label_servoR_3'][lang]))
        self.label_servoL_3.setText(_translate("Form", language['label_servoL_3'][lang]))
        self.label_servoR_4.setText(_translate("Form", language['label_servoR_4'][lang]))
        self.label_servoL_4.setText(_translate("Form", language['label_servoL_4'][lang]))
        self.label_servoL_8.setText(_translate("Form", language['label_servoL_8'][lang]))
        self.label_servoR_8.setText(_translate("Form", language['label_servoR_8'][lang]))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_1), _translate("Form", language['tabWidget.setTabText(self.tabWidget.indexOf(self.tab_1)'][lang]))
        item = self.tableWidget_Coord.horizontalHeaderItem(1).setText(_translate("Form", language['tableWidget_Coord.horizontalHeaderItem(1)'][lang]))
        item = self.tableWidget_Coord.horizontalHeaderItem(2).setText(_translate("Form", language['tableWidget_Coord.horizontalHeaderItem(2)'][lang]))
        self.checkBox_run_Coord_cycle.setText(_translate("Form", language['checkBox_run_Coord_cycle'][lang]))
        self.Button_Run_Coord.setText(_translate("Form", language['Button_Run_Coord'][lang]))
        self.Button_Reset_Coord.setText(_translate("Form", language['Button_Reset_Coord'][lang]))
        self.label_time_4.setText(_translate("Form", language['label_time_4'][lang]))
        self.Button_AddCoord.setText(_translate("Form", language['Button_AddCoord'][lang]))
        self.Button_DelectCoord.setText(_translate("Form", language['Button_DelectCoord'][lang]))
        self.Button_UpdateCoord.setText(_translate("Form", language['Button_UpdateCoord'][lang]))
        self.Button_MoveUpCoord.setText(_translate("Form", language['Button_MoveUpCoord'][lang]))
        self.Button_MoveDownCoord.setText(_translate("Form", language['Button_MoveDownCoord'][lang]))
        self.Button_DelectAllCoord.setText(_translate("Form", language['Button_DelectAllCoord'][lang]))
        self.label_time_3.setText(_translate("Form", language['label_time_3'][lang]))
        self.Button_InsertCoord.setText(_translate("Form", language['Button_InsertCoord'][lang]))
        self.Button_OpenActionGroup_Coord.setText(_translate("Form", language['Button_OpenActionGroup_Coord'][lang]))
        self.Button_SaveActionGroup_Coord.setText(_translate("Form", language['Button_SaveActionGroup_Coord'][lang]))
        self.Button_TandemActionGroup_Coord.setText(_translate("Form", language['Button_TandemActionGroup_Coord'][lang]))
        self.label_action_2.setText(_translate("Form", language['label_action_2'][lang]))
        self.Button_DelectSingle_Coord.setText(_translate("Form", language['Button_DelectSingle_Coord'][lang]))
        self.Button_AllDelect_Coord.setText(_translate("Form", language['Button_AllDelect_Coord'][lang]))
        self.Button_RunAction_Coord.setText(_translate("Form", language['Button_RunAction_Coord'][lang]))
        self.Button_StopAction_Coord.setText(_translate("Form", language['Button_StopAction_Coord'][lang]))
        self.Button_Refresh_Coord.setText(_translate("Form", language['Button_Refresh_Coord'][lang]))
        self.pushButton_quit2.setText(_translate("Form", language['pushButton_quit2'][lang]))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab), _translate("Form", language['tabWidget.setTabText(self.tabWidget.indexOf(self.tab)'][lang]))


if __name__ == "__main__":
    """
    程序入口

    功能:
        创建Qt应用程序实例
        初始化并显示主窗口
        启动事件循环
    """
    app = QtWidgets.QApplication(sys.argv)
    myshow = MainWindow()
    myshow.show()
    sys.exit(app.exec_())
