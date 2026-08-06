#!/usr/bin/env python3
# encoding: utf-8
"""
将 servo_tuner.html 导出的 JSON 动作帧转换为 .d6a 动作组文件。

用法:
    python3 convert_json_to_d6a.py action.json [--output action.d6a]

说明:
    .d6a 文件是 SQLite 数据库，表结构为 ActionGroup(Index, Time, Servo1..Servo11)。
    本脚本把 JSON 中的 8 路四足舵机值写入 Servo1..Servo8，Servo9..Servo11 填中位 1500。
"""

import argparse
import json
import os
import sqlite3
import sys


def convert(json_path: str, d6a_path: str):
    if not os.path.isfile(json_path):
        print(f"错误: 找不到文件 {json_path}")
        sys.exit(1)

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    frames = data.get('frames', [])
    if not frames:
        print("错误: JSON 中没有 frames")
        sys.exit(1)

    if os.path.isfile(d6a_path):
        os.remove(d6a_path)

    conn = sqlite3.connect(d6a_path)
    c = conn.cursor()

    # 创建表: Index, Time, Servo1..Servo11
    cols = ['[Index] INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL ON CONFLICT FAIL UNIQUE ON CONFLICT ABORT', 'Time INT']
    for i in range(1, 12):
        cols.append(f'Servo{i} INT')
    c.execute(f"CREATE TABLE ActionGroup({', '.join(cols)});")

    for idx, frame in enumerate(frames):
        time_ms = int(frame.get('time', 300))
        values = frame.get('values', [])
        # 补齐 11 路舵机，未提供的填 1500
        full_values = list(values) + [1500] * (11 - len(values))
        full_values = full_values[:11]

        placeholders = ', '.join(['?'] * (1 + 11))
        c.execute(
            f'INSERT INTO ActionGroup(Time, Servo1, Servo2, Servo3, Servo4, Servo5, Servo6, Servo7, Servo8, Servo9, Servo10, Servo11) VALUES({placeholders})',
            [time_ms] + full_values
        )
        print(f"  写入帧 #{idx+1}: time={time_ms}ms, values={values}")

    conn.commit()
    conn.close()
    print(f"\n转换完成: {d6a_path}")
    print(f"总帧数: {len(frames)}")


def main():
    parser = argparse.ArgumentParser(description='Convert servo_tuner JSON to .d6a action group')
    parser.add_argument('json', help='输入 JSON 文件路径')
    parser.add_argument('--output', '-o', help='输出 .d6a 文件路径，默认与输入同名')
    args = parser.parse_args()

    json_path = args.json
    if args.output:
        d6a_path = args.output
    else:
        base, _ = os.path.splitext(json_path)
        d6a_path = base + '.d6a'

    convert(json_path, d6a_path)


if __name__ == '__main__':
    main()
