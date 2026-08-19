#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_materials.py - 软件著作权申报材料生成脚本

生成以下材料到 软著申报材料/ 目录：
  1. 源程序材料.pdf   源代码鉴别材料（前30页+后30页，每页50行，
                      页眉含软件名称及版本号，页脚含页码）
  2. 用户操作手册.pdf  文档鉴别材料（含界面截图，页眉含软件名称及版本号）

基于 PySide6 QPdfWriter 生成 PDF，无需额外依赖。

用法:
  QT_QPA_PLATFORM=offscreen python3 tools/generate_materials.py
"""

import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (QColor, QFont, QPageLayout, QPageSize, QPainter,
                           QPdfWriter, QPen, QTextDocument)

from app.version import APP_NAME, APP_VERSION

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, "软著申报材料")
SHOT_DIR = os.path.join(BASE_DIR, "screenshots")

SOFTWARE_TITLE = f"{APP_NAME}{APP_VERSION}"

# 源代码文件清单（按逻辑阅读顺序：入口 → 配置 → 核心 → 网络 → 界面）
SOURCE_FILES = [
    "main.py",
    "app/version.py",
    "app/config.py",
    "app/core/models.py",
    "app/core/workers.py",
    "app/core/session.py",
    "app/core/simulator.py",
    "app/net/api_client.py",
    "app/net/mjpeg_client.py",
    "app/ui/theme.py",
    "app/ui/widgets.py",
    "app/ui/video_widget.py",
    "app/ui/settings_dialog.py",
    "app/ui/main_window.py",
    "app/ui/pages/overview_page.py",
    "app/ui/pages/video_page.py",
    "app/ui/pages/motion_page.py",
    "app/ui/pages/chat_page.py",
    "app/ui/pages/avoid_page.py",
    "app/ui/pages/log_page.py",
    "app/ui/pages/system_page.py",
]

LINES_PER_PAGE = 50        # 每页源代码行数（软著规范要求每页不少于50行）
FRONT_PAGES = 30           # 提交前30页
BACK_PAGES = 30            # 提交后30页
CODE_MAX_WIDTH = 100       # 源代码显示行最大宽度（半角字符数，全角按2计）


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------
def display_width(text: str) -> int:
    """计算字符串显示宽度（全角字符按 2 计）"""
    width = 0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
    return width


def wrap_code_line(text: str, max_width: int = CODE_MAX_WIDTH) -> list:
    """把一行源代码按显示宽度折行为多个显示行（长行折行，
    折行部分同样计入每页行数，符合软著材料规范）"""
    if not text:
        return [""]
    result = []
    current = ""
    current_width = 0
    for ch in text:
        ch_width = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
        if current_width + ch_width > max_width:
            result.append(current)
            current = ch
            current_width = ch_width
        else:
            current += ch
            current_width += ch_width
    if current:
        result.append(current)
    return result


def collect_source_lines() -> list:
    """按文件顺序读取全部源代码为显示行列表"""
    display_lines = []
    for rel_path in SOURCE_FILES:
        file_path = os.path.join(BASE_DIR, rel_path)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 文件分隔注释行（在材料中标识模块边界）
        display_lines.append(f"# {'=' * 44}")
        display_lines.append(f"# 模块文件: {rel_path}")
        display_lines.append(f"# {'=' * 44}")
        for raw_line in content.splitlines():
            display_lines.extend(wrap_code_line(raw_line))
    return display_lines


# ----------------------------------------------------------------------
# 源程序材料 PDF
# ----------------------------------------------------------------------
def generate_source_pdf(out_path: str):
    """生成源程序鉴别材料 PDF"""
    display_lines = collect_source_lines()
    total_code_lines = len(display_lines)
    total_pages = (total_code_lines + LINES_PER_PAGE - 1) // LINES_PER_PAGE

    # 前30页 + 后30页；不足60页时全部提交
    if total_pages <= FRONT_PAGES + BACK_PAGES:
        page_slices = list(range(1, total_pages + 1))
        submitted_pages = total_pages
    else:
        front = list(range(1, FRONT_PAGES + 1))
        back = list(range(total_pages - BACK_PAGES + 1, total_pages + 1))
        page_slices = front + back
        submitted_pages = len(page_slices)

    writer = QPdfWriter(out_path)
    writer.setPageLayout(QPageLayout(
        QPageSize(QPageSize.A4), QPageLayout.Portrait,
        QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter))
    writer.setResolution(150)
    writer.setTitle(f"{SOFTWARE_TITLE} 源程序")
    writer.setCreator(SOFTWARE_TITLE)

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.TextAntialiasing)

    # 页面几何（设备像素）
    page_rect = writer.pageLayout().paintRectPixels(writer.resolution())
    header_h = int(page_rect.height() * 0.045)
    footer_h = int(page_rect.height() * 0.035)
    content_rect = QRectF(
        page_rect.x() + 10, page_rect.y() + header_h + 14,
        page_rect.width() - 20,
        page_rect.height() - header_h - footer_h - 24)

    # 字体
    font_header = QFont("Noto Sans CJK SC", 10, QFont.Bold)
    font_code = QFont("Noto Sans Mono CJK SC", 8)
    font_code.setLetterSpacing(QFont.PercentageSpacing, 100)
    font_footer = QFont("Noto Sans CJK SC", 8)
    font_linenumber = QFont("Noto Sans Mono CJK SC", 7)
    font_linenumber.setItalic(True)

    line_height = content_rect.height() / LINES_PER_PAGE

    for page_index, code_page in enumerate(page_slices):
        # ---- 页眉: 软件名称及版本号 ----
        painter.setFont(font_header)
        painter.setPen(QPen(QColor(30, 30, 30)))
        header_rect = QRectF(page_rect.x() + 10, page_rect.y() + 8,
                             page_rect.width() - 20, header_h)
        painter.drawText(header_rect, Qt.AlignLeft | Qt.AlignVCenter,
                         SOFTWARE_TITLE)
        painter.drawText(header_rect, Qt.AlignRight | Qt.AlignVCenter,
                         "源程序")
        pen = QPen(QColor(120, 120, 120), 1)
        painter.setPen(pen)
        y_line = page_rect.y() + header_h + 8
        painter.drawLine(QPointF(page_rect.x() + 10, y_line),
                         QPointF(page_rect.x() + page_rect.width() - 10, y_line))

        # ---- 源代码行 ----
        start = (code_page - 1) * LINES_PER_PAGE
        end = min(start + LINES_PER_PAGE, total_code_lines)
        painter.setFont(font_code)
        for i in range(start, end):
            row = i - start
            baseline_y = content_rect.y() + row * line_height + line_height * 0.78
            # 行号
            painter.setFont(font_linenumber)
            painter.setPen(QPen(QColor(150, 150, 150)))
            painter.drawText(QPointF(content_rect.x(), baseline_y),
                             f"{i + 1:>5}")
            # 代码内容
            painter.setFont(font_code)
            painter.setPen(QPen(QColor(20, 20, 20)))
            painter.drawText(QPointF(content_rect.x() + 46, baseline_y),
                             display_lines[i])

        # ---- 页脚: 页码 ----
        painter.setFont(font_footer)
        painter.setPen(QPen(QColor(30, 30, 30)))
        footer_rect = QRectF(page_rect.x() + 10,
                             page_rect.y() + page_rect.height() - footer_h,
                             page_rect.width() - 20, footer_h)
        painter.drawText(footer_rect, Qt.AlignHCenter | Qt.AlignVCenter,
                         f"第 {page_index + 1} 页  共 {submitted_pages} 页")

        if page_index < len(page_slices) - 1:
            writer.newPage()

    painter.end()
    print(f"已生成: {out_path}")
    print(f"  源代码总行数: {total_code_lines} 行（含折行）, "
          f"共 {total_pages} 页, 提交 {submitted_pages} 页")
    return total_code_lines, total_pages


# ----------------------------------------------------------------------
# 用户操作手册 PDF
# ----------------------------------------------------------------------
def build_manual_html() -> str:
    """构建用户操作手册 HTML 内容"""

    def shot(filename):
        """插入截图的 HTML"""
        path = os.path.join(SHOT_DIR, filename)
        return (f'<img src="{path}" width="640">')

    chapters = []
    add = chapters.append

    # ---- 封面信息 ----
    add(f"""
    <h1 style="text-align:center;">{SOFTWARE_TITLE}</h1>
    <h2 style="text-align:center;">用户操作手册</h2>
    <p style="text-align:center;">&nbsp;</p>
    <p style="text-align:center;">著作权人：&lt;待填写&gt;</p>
    <p style="text-align:center;">开发完成日期：2026 年 8 月</p>
    <p style="text-align:center;">文档版本：V1.0</p>
    <p style="page-break-after:always;">&nbsp;</p>
    """)

    # ---- 目录 ----
    add("""
    <h2>目 录</h2>
    <p>第一章 软件概述</p>
    <p>第二章 运行环境</p>
    <p>第三章 软件安装与启动</p>
    <p>第四章 软件界面布局</p>
    <p>第五章 系统总览操作说明</p>
    <p>第六章 视频监控操作说明</p>
    <p>第七章 运动控制操作说明</p>
    <p>第八章 对话控制操作说明</p>
    <p>第九章 避障监测操作说明</p>
    <p>第十章 日志中心操作说明</p>
    <p>第十一章 系统管理操作说明</p>
    <p>第十二章 连接设置说明</p>
    <p>第十三章 常见问题与故障处理</p>
    <p>第十四章 附录</p>
    <p style="page-break-after:always;">&nbsp;</p>
    """)

    # ---- 第一章 软件概述 ----
    add(f"""
    <h2>第一章 软件概述</h2>
    <h3>1.1 软件简介</h3>
    <p>{APP_NAME}{APP_VERSION}（以下简称"本软件"）是面向四足机器狗的
    PC 端远程监控与控制软件。本软件通过网络连接机器狗板端控制系统，
    将板端各组件的运行状态、多路摄像头画面、避障决策信息汇聚到统一的
    图形界面中，并提供运动控制、自然语言对话控制、日志诊断与系统
    运维等操作能力，是机器狗系统的远程人机交互中心。</p>
    <h3>1.2 主要功能</h3>
    <p>本软件共包含七个功能模块：</p>
    <table width="100%" cellspacing="0" cellpadding="4" border="0.5">
      <tr bgcolor="#e8eef7">
        <td width="18%"><b>功能模块</b></td><td><b>功能说明</b></td>
      </tr>
      <tr><td>系统总览</td>
        <td>集中展示板端全部组件的运行状态灯、UDP 端口监听状态、
        视频流在线状态，并提供系统启停与避障模式切换的快捷操作入口。</td></tr>
      <tr><td>视频监控</td>
        <td>同时展示右眼、左眼、深度伪彩图、YOLO 目标检测、手势识别
        五路实时视频画面，支持双击放大单路画面。</td></tr>
      <tr><td>运动控制</td>
        <td>提供前进、后退、左转、右转、行走、坐下、站立、停止八个
        离散动作按钮，方向类按钮支持长按持续运动；提供连续遥控速度
        滑杆与键盘控制（W/S/A/D）。</td></tr>
      <tr><td>对话控制</td>
        <td>输入自然语言指令（如"先坐下再站起来"），板端大模型解析为
        动作序列并自动执行；视觉类问题自动调用实时摄像头画面回答。</td></tr>
      <tr><td>避障监测</td>
        <td>展示双目避障子系统的实时决策状态，包括避障阶段、三区
        距离、近像素占比、方位判定与 USB 语义检测结果，并可切换
        自动巡航/纯监测模式。</td></tr>
      <tr><td>日志中心</td>
        <td>在线查看板端运动仲裁器、运动中枢、双目深度、避障、
        手势、语音助手等七类组件日志的末尾内容。</td></tr>
      <tr><td>系统管理</td>
        <td>板端组件的启动、停止、重启，以及双目深度链路与运动
        中枢的单独重启，操作输出实时显示。</td></tr>
    </table>
    <h3>1.3 技术特点</h3>
    <p>（1）本软件基于 Qt 6 图形框架（PySide6）开发，界面采用暗色
    科技风设计，全部界面元素统一定制样式；</p>
    <p>（2）网络通信层完全基于 Python 标准库实现，无第三方网络依赖，
    包括 HTTP REST API 客户端与 MJPEG 视频流解析器两部分；</p>
    <p>（3）状态轮询、视频拉流、指令发送全部在后台线程执行，
    界面操作永不卡顿；</p>
    <p>（4）内置演示模式，以合成视频画面与模拟状态数据完整模拟
    板端系统，便于教学演示与功能验证；</p>
    <p>（5）长按运动控制采用心跳机制保持仲裁通道活跃，松开立即
    停车，保证运动安全。</p>
    """)

    # ---- 第二章 运行环境 ----
    add("""
    <h2>第二章 运行环境</h2>
    <h3>2.1 硬件环境</h3>
    <p>（1）CPU：Intel/AMD x86_64 处理器，主频 1.6 GHz 及以上；</p>
    <p>（2）内存：4 GB 及以上；</p>
    <p>（3）显示：分辨率 1280×800 及以上；</p>
    <p>（4）网络：以太网或 Wi-Fi（连接真实板端时需要与板端处于
    同一局域网）。</p>
    <h3>2.2 软件环境</h3>
    <p>（1）操作系统：Windows 10/11、Ubuntu 20.04 及以上或其他
    支持 Qt 6 的桌面操作系统；</p>
    <p>（2）Python：3.10 及以上（使用打包版可执行程序时无需安装）；</p>
    <p>（3）依赖库：PySide6 6.6 及以上（唯一第三方依赖）。</p>
    <h3>2.3 板端环境（连接真实机器狗时）</h3>
    <p>（1）机器狗板端控制系统已启动，HTTP 监控服务（dashboard.py）
    运行在默认端口 8081；</p>
    <p>（2）板端各视频流服务（8071/8072/8073/8093/8094 端口）按需运行。</p>
    """)

    # ---- 第三章 安装与启动 ----
    add("""
    <h2>第三章 软件安装与启动</h2>
    <h3>3.1 安装依赖</h3>
    <p>在软件根目录执行以下命令安装依赖：</p>
    <p><font face="Consolas" size="2" color="#205080">pip install -r requirements.txt</font></p>
    <h3>3.2 演示模式启动</h3>
    <p>演示模式使用内置模拟数据源，无需连接真实机器狗，适合首次
    使用时熟悉软件功能：</p>
    <p><font face="Consolas" size="2" color="#205080">python main.py --demo</font></p>
    <h3>3.3 连接真实板端启动</h3>
    <p>（1）确保 PC 与机器狗板端处于同一局域网；</p>
    <p>（2）执行以下命令启动（将 IP 替换为板端实际地址）：</p>
    <p><font face="Consolas" size="2" color="#205080">python main.py --host 192.168.1.10</font></p>
    <p>（3）也可以不带参数启动后，通过"连接设置"对话框修改板端
    地址。</p>
    <h3>3.4 Windows 一键启动</h3>
    <p>Windows 用户可双击软件根目录下的"启动软件.bat"，脚本会自动
    创建虚拟环境、安装依赖并启动软件。</p>
    """)

    # ---- 第四章 界面布局 ----
    add(f"""
    <h2>第四章 软件界面布局</h2>
    <p>软件主窗口分为四个区域：顶部标题栏、左侧导航栏、中央功能区
    与底部状态栏。</p>
    <p>（1）顶部标题栏：显示软件名称、版本号、当前板端地址与运行
    模式（在线模式/演示模式），右侧提供"连接设置"与"关于"按钮；</p>
    <p>（2）左侧导航栏：七个功能模块入口，点击切换中央功能区页面；</p>
    <p>（3）中央功能区：当前选中模块的操作界面；</p>
    <p>（4）底部状态栏：实时显示板端连接状态（绿色/红色指示灯）、
    数据源类型与最后更新时间。</p>
    <p>{shot("01_overview.png")}</p>
    <p style="text-align:center; color:#606060;">图 4-1 软件主界面（系统总览页）</p>
    """)

    # ---- 第五章 系统总览 ----
    add(f"""
    <h2>第五章 系统总览操作说明</h2>
    <h3>5.1 功能说明</h3>
    <p>系统总览页集中展示板端整体运行状态，是日常巡检的主要页面。</p>
    <h3>5.2 界面组成</h3>
    <p>（1）组件运行状态卡：以状态灯形式列出板端九个组件（运动
    仲裁器、双目深度+AI、运动中枢、IMU 节点、WebSocket 桥、ROS/UDP
    桥、双目避障、手势控制、语音助手）的运行状态，绿色"运行中"/
    红色"未运行"；</p>
    <p>（2）板端连接信息卡：板端 IP、状态时间戳、组件在线数、
    视频在线数汇总；</p>
    <p>（3）UDP 端口卡：仲裁器（5005）与运动中枢（5006）端口的
    监听状态；</p>
    <p>（4）视频流在线状态卡：五路视频服务的在线/离线状态；</p>
    <p>（5）快捷操作卡：启动全部、停止全部、重启全部、开启避障
    巡航、关闭避障按钮。</p>
    <h3>5.3 操作步骤</h3>
    <p>（1）状态数据随轮询周期（默认 3 秒）自动刷新；</p>
    <p>（2）点击"启动全部"下发板端全组件启动命令，操作结果显示在
    快捷操作卡下方的提示条中；</p>
    <p>（3）"停止全部"与"重启全部"命令会弹出二次确认对话框，
    确认后执行。</p>
    <p>{shot("01_overview.png")}</p>
    <p style="text-align:center; color:#606060;">图 5-1 系统总览页</p>
    """)

    # ---- 第六章 视频监控 ----
    add(f"""
    <h2>第六章 视频监控操作说明</h2>
    <h3>6.1 功能说明</h3>
    <p>视频监控页以网格形式同时展示五路实时视频画面：右眼原始
    画面、左眼原始画面、深度伪彩图、YOLO 目标检测画面与手势识别
    画面。每路画面标题栏显示连接状态与实时帧率。</p>
    <h3>6.2 操作步骤</h3>
    <p>（1）在左侧导航栏点击"视频监控"进入页面，视频流自动开始
    接收；</p>
    <p>（2）双击任一路画面可将其放大为单路大画面，再次双击恢复
    网格布局；</p>
    <p>（3）切换到其他页面时视频流自动停止，以节省网络带宽，
    返回本页时自动恢复。</p>
    <h3>6.3 画面说明</h3>
    <p>（1）右眼/左眼原始画面：双目摄像头的原始成像，两画面间
    存在视差，供观察双目匹配质量；</p>
    <p>（2）深度伪彩图：以伪彩色呈现场景深度（近红远蓝），叠加
    左/中/右三分区参考线；</p>
    <p>（3）YOLO 目标检测：实时目标检测框与类别置信度标注；</p>
    <p>（4）手势识别：手部 21 关键点骨架与手势判定结果标注。</p>
    <p>{shot("02_video.png")}</p>
    <p style="text-align:center; color:#606060;">图 6-1 视频监控页（演示模式画面）</p>
    """)

    # ---- 第七章 运动控制 ----
    add(f"""
    <h2>第七章 运动控制操作说明</h2>
    <h3>7.1 功能说明</h3>
    <p>运动控制页提供两类控制方式：离散动作控制与连续遥控模式。</p>
    <h3>7.2 离散动作控制</h3>
    <p>（1）页面提供前进、后退、左转、右转、行走、坐下、站立、
    停止八个动作按钮；</p>
    <p>（2）方向类按钮（前进/后退/左转/右转/行走）支持长按：按住
    期间持续运动（内部以 200 毫秒心跳保持指令通道活跃），松开立即
    停止；</p>
    <p>（3）坐下、站立、停止为单次触发按钮；</p>
    <p>（4）键盘操作：W 前进、S 后退、A 左转、D 右转、空格急停，
    按住生效、松开停止。</p>
    <h3>7.3 连续遥控模式</h3>
    <p>（1）通过"前进/后退"纵向滑杆与"左转/右转"横向滑杆设定
    速度（-1.00 至 +1.00）；</p>
    <p>（2）点击"开始遥控"后，软件以固定频率（默认 8Hz）持续下发
    速度指令；</p>
    <p>（3）点击"停止遥控"或"速度归零"后机器狗停止；</p>
    <p>（4）遥控指令走最低优先级通道，板端避障系统检测到障碍时
    自动接管。</p>
    <h3>7.4 安全说明</h3>
    <p>（1）长按状态在页面失去焦点时自动解除并发送停止指令，防止
    切换窗口导致运动失控；</p>
    <p>（2）运动控制优先级：避障（最高）&gt; 语音 &gt; 手势/遥控。</p>
    <p>{shot("03_motion.png")}</p>
    <p style="text-align:center; color:#606060;">图 7-1 运动控制页</p>
    """)

    # ---- 第八章 对话控制 ----
    add(f"""
    <h2>第八章 对话控制操作说明</h2>
    <h3>8.1 功能说明</h3>
    <p>对话控制页提供自然语言交互界面。输入的文字指令由板端大
    模型解析为回复与动作序列，动作序列自动执行；视觉类问题自动
    路由至视觉问答模块，基于实时摄像头画面回答。</p>
    <h3>8.2 操作步骤</h3>
    <p>（1）在底部输入框输入指令（如"先坐下再站起来"），按回车
    或点击"发送"；</p>
    <p>（2）等待期间显示"思考中..."占位气泡；</p>
    <p>（3）回复到达后显示为对话气泡，若包含动作序列，气泡下方
    以绿色标签展示（如"坐下 2s → 站立 1.5s"）；</p>
    <p>（4）视觉类回复带 [视觉] 标记；</p>
    <p>（5）勾选"喇叭同步播报回答"后，回复文本经板端语音助手
    喇叭同步播出；</p>
    <p>（6）点击"清空会话"重新开始。</p>
    <h3>8.3 支持的指令示例</h3>
    <p>（1）复合动作："先坐下再站起来""前进两秒然后左转"；</p>
    <p>（2）视觉问句："你能看到什么""前面有什么东西"；</p>
    <p>（3）普通聊天：任意自然语言对话。</p>
    <p>{shot("04_chat.png")}</p>
    <p style="text-align:center; color:#606060;">图 8-1 对话控制页（含指令交互示例）</p>
    """)

    # ---- 第九章 避障监测 ----
    add(f"""
    <h2>第九章 避障监测操作说明</h2>
    <h3>9.1 功能说明</h3>
    <p>避障监测页展示双目避障子系统的实时决策状态，并提供模式
    切换。自动巡航模式下机器狗持续前进并自主避障；纯监测模式下
    仅显示判断结果，不控制运动。</p>
    <h3>9.2 界面组成</h3>
    <p>（1）避障模式控制卡：开启自动巡航/关闭避障按钮与当前
    模式显示；</p>
    <p>（2）实时避障状态卡：节点状态、避障阶段、方位判定、三区
    距离、近像素占比、USB 检测六项信息。</p>
    <h3>9.3 状态项说明</h3>
    <p>（1）避障阶段：巡航/监测、停车、后退、左转躲右障、右转
    躲左障；</p>
    <p>（2）方位判定：无障碍（绿色）、左/右/正前方障碍（红色）、
    深度数据异常（黄色）；</p>
    <p>（3）三区距离：左/中/右判定区的最近障碍距离（米）；</p>
    <p>（4）近像素占比：三区内近距像素占比，反映障碍物面积
    程度；</p>
    <p>（5）USB 检测：USB 摄像头语义检测融合结果，用于补充双目
    深度对透明/无纹理物体的盲区。</p>
    <h3>9.4 操作步骤</h3>
    <p>（1）点击"开启自动巡航"进入避障控车模式；</p>
    <p>（2）点击"关闭避障（纯监测）"后机器狗停止自主运动，页面
    继续显示监测结果；</p>
    <p>（3）各项状态数据随轮询周期自动刷新。</p>
    <p>{shot("05_avoid.png")}</p>
    <p style="text-align:center; color:#606060;">图 9-1 避障监测页</p>
    """)

    # ---- 第十章 日志中心 ----
    add(f"""
    <h2>第十章 日志中心操作说明</h2>
    <h3>10.1 功能说明</h3>
    <p>日志中心页提供板端七个组件日志的在线查看能力，用于运行
    诊断与故障排查。</p>
    <h3>10.2 操作步骤</h3>
    <p>（1）在左侧日志源列表中选择要查看的组件（运动仲裁器/
    运动中枢/双目深度/避障/机器人/手势/语音助手）；</p>
    <p>（2）右侧区域显示该日志源的末尾 80 行内容，自动滚动到底部；</p>
    <p>（3）点击"刷新"按钮手动拉取最新日志；</p>
    <p>（4）勾选"自动刷新"后，日志内容随状态轮询周期自动更新；</p>
    <p>（5）日志内容支持选中后 Ctrl+C 复制。</p>
    <p>{shot("06_log.png")}</p>
    <p style="text-align:center; color:#606060;">图 10-1 日志中心页</p>
    """)

    # ---- 第十一章 系统管理 ----
    add(f"""
    <h2>第十一章 系统管理操作说明</h2>
    <h3>11.1 功能说明</h3>
    <p>系统管理页提供板端组件的启停与恢复操作，分为全局组件
    管理与单独重启两类。</p>
    <h3>11.2 全局组件管理</h3>
    <p>（1）启动全部组件：下发板端全组件启动命令；</p>
    <p>（2）停止全部组件：停止板端全部组件（二次确认）；</p>
    <p>（3）重启全部组件：重启板端全部组件（二次确认），链路
    耗时约 1 分钟，命令在板端后台执行。</p>
    <h3>11.3 单独重启</h3>
    <p>（1）重启双目深度链路：深度图异常（黑屏/花屏）时使用，
    不影响运动中枢与语音助手；</p>
    <p>（2）重启运动中枢：机器狗无响应时使用（二次确认）。</p>
    <h3>11.4 操作输出</h3>
    <p>全部命令的执行输出实时显示在页面下方的"操作输出"区域，
    以等宽字体呈现，自动滚动到底部。</p>
    <p>{shot("07_system.png")}</p>
    <p style="text-align:center; color:#606060;">图 11-1 系统管理页</p>
    """)

    # ---- 第十二章 连接设置 ----
    add(f"""
    <h2>第十二章 连接设置说明</h2>
    <h3>12.1 打开方式</h3>
    <p>点击主窗口右上角"连接设置"按钮打开设置对话框。</p>
    <h3>12.2 可配置项</h3>
    <table width="100%" cellspacing="0" cellpadding="4" border="0.5">
      <tr bgcolor="#e8eef7">
        <td width="30%"><b>配置项</b></td><td><b>说明与默认值</b></td>
      </tr>
      <tr><td>板端 IP 地址</td><td>板端监控服务所在主机地址，默认 192.168.1.10</td></tr>
      <tr><td>板端 API 端口</td><td>板端 HTTP 服务端口，默认 8081</td></tr>
      <tr><td>状态轮询间隔</td><td>状态数据刷新周期，默认 3 秒</td></tr>
      <tr><td>长按心跳间隔</td><td>长按运动指令重复下发间隔，默认 200 毫秒</td></tr>
      <tr><td>遥控发送频率</td><td>连续遥控指令发送频率，默认 8 Hz</td></tr>
      <tr><td>请求超时</td><td>HTTP 请求超时时间，默认 4 秒</td></tr>
      <tr><td>演示模式</td><td>启用后使用内置模拟数据源，无需连接板端</td></tr>
    </table>
    <h3>12.3 配置持久化</h3>
    <p>点击"确定"后配置立即生效并保存到用户主目录的
    .puppy_console.json 文件，下次启动自动加载。</p>
    """)

    # ---- 第十三章 常见问题 ----
    add("""
    <h2>第十三章 常见问题与故障处理</h2>
    <h3>13.1 连接板端失败（状态栏显示红色）</h3>
    <p>（1）检查 PC 与板端是否处于同一局域网；</p>
    <p>（2）核对"连接设置"中的板端 IP 与端口；</p>
    <p>（3）确认板端监控服务（dashboard.py）已启动；</p>
    <p>（4）在终端执行 ping 命令测试网络连通性。</p>
    <h3>13.2 视频画面显示"重连中..."</h3>
    <p>（1）对应视频流服务未启动，可在"系统总览"页查看视频流
    在线状态；</p>
    <p>（2）双目链路异常时，进入"系统管理"页单独重启双目深度
    链路。</p>
    <h3>13.3 运动指令无响应</h3>
    <p>（1）在"系统总览"页确认运动仲裁器与运动中枢组件处于
    运行状态；</p>
    <p>（2）避障自动巡航开启时，遥控指令会被避障系统覆盖，属
    正常现象；</p>
    <p>（3）在"系统管理"页重启运动中枢。</p>
    <h3>13.4 对话发送后长时间"思考中"</h3>
    <p>（1）板端大模型服务依赖网络，请确认板端可访问外部
    API；</p>
    <p>（2）视觉问句需要取帧分析，耗时 5~10 秒属正常范围。</p>
    <h3>13.5 软件启动报缺少 PySide6</h3>
    <p>执行 pip install -r requirements.txt 安装依赖，或使用
    打包版可执行程序。</p>
    """)

    # ---- 第十四章 附录 ----
    add("""
    <h2>第十四章 附录</h2>
    <h3>附录 A 键盘快捷键表</h3>
    <table width="100%" cellspacing="0" cellpadding="4" border="0.5">
      <tr bgcolor="#e8eef7">
        <td width="30%"><b>按键</b></td><td><b>功能</b></td>
      </tr>
      <tr><td>W</td><td>前进（按住持续，松开停止）</td></tr>
      <tr><td>S</td><td>后退（按住持续，松开停止）</td></tr>
      <tr><td>A</td><td>左转（按住持续，松开停止）</td></tr>
      <tr><td>D</td><td>右转（按住持续，松开停止）</td></tr>
      <tr><td>空格</td><td>急停</td></tr>
      <tr><td>回车</td><td>发送对话输入框内容</td></tr>
    </table>
    <h3>附录 B 术语表</h3>
    <table width="100%" cellspacing="0" cellpadding="4" border="0.5">
      <tr bgcolor="#e8eef7">
        <td width="30%"><b>术语</b></td><td><b>说明</b></td>
      </tr>
      <tr><td>板端</td><td>运行在机器狗主控板上的控制系统</td></tr>
      <tr><td>运动仲裁器</td><td>按优先级裁决避障/语音/遥控等多路运动指令的板端组件</td></tr>
      <tr><td>follow_control</td><td>连续运动控制协议，以固定频率下发速度指令</td></tr>
      <tr><td>深度伪彩图</td><td>将场景深度按距离映射为颜色的可视化图像</td></tr>
      <tr><td>近像素占比</td><td>判定区内近距离像素所占比例，反映障碍物面积</td></tr>
      <tr><td>演示模式</td><td>使用内置模拟数据源运行的软件模式</td></tr>
    </table>
    <h3>附录 C 软件版权信息</h3>
    <p>软件名称：机器狗远程监控与运动控制上位机软件</p>
    <p>版本号：V1.0</p>
    <p>著作权人：&lt;待填写&gt;</p>
    <p>Copyright (c) 2026 &lt;著作权人&gt; 保留所有权利。</p>
    """)

    return "".join(chapters)


def generate_manual_pdf(out_path: str):
    """生成用户操作手册 PDF（自动分页，每页页眉含软件名称及版本号）"""
    writer = QPdfWriter(out_path)
    writer.setPageLayout(QPageLayout(
        QPageSize(QPageSize.A4), QPageLayout.Portrait,
        QMarginsF(15, 18, 15, 15), QPageLayout.Millimeter))
    writer.setResolution(150)
    writer.setTitle(f"{SOFTWARE_TITLE} 用户操作手册")
    writer.setCreator(SOFTWARE_TITLE)

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    page_rect = writer.pageLayout().paintRectPixels(writer.resolution())
    header_h = int(page_rect.height() * 0.045)
    footer_h = int(page_rect.height() * 0.035)
    # 内容区（页眉页脚之间的区域）
    content_width = page_rect.width() - 20
    content_height = page_rect.height() - header_h - footer_h - 30

    # 手册正文文档
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Noto Sans CJK SC", 10))
    doc.setDocumentMargin(0)
    doc.setHtml(build_manual_html())
    doc.setPageSize(QSizeF(content_width, content_height))

    page_count = doc.pageCount()
    font_header = QFont("Noto Sans CJK SC", 8, QFont.Bold)
    font_footer = QFont("Noto Sans CJK SC", 8)
    pen_text = QPen(QColor(30, 30, 30))
    pen_line = QPen(QColor(140, 140, 140), 1)

    for page_index in range(page_count):
        # ---- 页眉 ----
        painter.setFont(font_header)
        painter.setPen(pen_text)
        header_rect = QRectF(page_rect.x() + 10, page_rect.y() + 6,
                             page_rect.width() - 20, header_h)
        painter.drawText(header_rect, Qt.AlignLeft | Qt.AlignVCenter,
                         SOFTWARE_TITLE)
        painter.drawText(header_rect, Qt.AlignRight | Qt.AlignVCenter,
                         "用户操作手册")
        painter.setPen(pen_line)
        y_line = page_rect.y() + header_h + 6
        painter.drawLine(QPointF(page_rect.x() + 10, y_line),
                         QPointF(page_rect.x() + page_rect.width() - 10, y_line))

        # ---- 正文（裁剪到本页内容区后整体平移绘制）----
        painter.save()
        content_top = page_rect.y() + header_h + 12
        painter.setClipRect(QRectF(page_rect.x() + 10, content_top,
                                   content_width, content_height))
        painter.translate(page_rect.x() + 10 - 0,
                          content_top - page_index * content_height)
        doc.drawContents(painter)
        painter.restore()

        # ---- 页脚 ----
        painter.setFont(font_footer)
        painter.setPen(pen_text)
        footer_rect = QRectF(page_rect.x() + 10,
                             page_rect.y() + page_rect.height() - footer_h - 4,
                             page_rect.width() - 20, footer_h)
        painter.drawText(footer_rect, Qt.AlignHCenter | Qt.AlignVCenter,
                         f"第 {page_index + 1} 页  共 {page_count} 页")

        if page_index < page_count - 1:
            writer.newPage()

    painter.end()
    print(f"已生成: {out_path}")
    print(f"  手册共 {page_count} 页（含封面与目录）")
    return page_count


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # QPdfWriter 的字体渲染需要 QGuiApplication 实例
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication(sys.argv[:1])

    print(f"软件名称: {SOFTWARE_TITLE}")
    print(f"输出目录: {OUT_DIR}")
    print("-" * 50)

    generate_source_pdf(os.path.join(OUT_DIR, "源程序材料.pdf"))
    print("-" * 50)
    generate_manual_pdf(os.path.join(OUT_DIR, "用户操作手册.pdf"))
    print("-" * 50)
    print("全部材料生成完成")


if __name__ == "__main__":
    main()
