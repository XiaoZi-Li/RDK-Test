#!/usr/bin/env python3

import dora
from dora import Node
import time

def main():
    print("[Timer] 启动定时器节点 (25ms间隔)")
    
    node = Node("timer")
    
    try:
        while True:
            # 发送tick信号
            node.send_output("tick", b"")
            
            # 25ms间隔 (40Hz)
            time.sleep(0.025)
            
    except KeyboardInterrupt:
        print("[Timer] 用户中断")

if __name__ == "__main__":
    main()