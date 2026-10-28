# DPI 感知必须最先声明（在 pywin32 / pynput 之前），坐标与截图才是物理像素。
import screen_scale
screen_scale.enable_dpi_awareness()

from time import sleep
from FSM_action import system_exit, AutoHS_automata
import keyboard
from print_info import print_info_init
from FSM_action import init

import constants.constants


if __name__ == "__main__":
    print("建议当前系统分辨率为：1920×1080（非必须，不一致只会提示坐标可能偏移）")
    print("建议当前系统缩放为：100%（非必须，不一致只会提示截图/点击可能偏移）")
    print("请设置确认炉石传说设置为：全屏")
    print("请保持炉石传说与炉石盒子可见，程序将自动读取左侧 AI 打法并执行")
    print("按 Ctrl+Q 可随时停止自动化并退出程序")
    
    MY_NAME = constants.constants.YOUR_NAME
    print("你好"+MY_NAME)
    sleep(2)
    print_info_init()
    init()
    keyboard.add_hotkey("ctrl+q", system_exit)
    try:
        AutoHS_automata()
    except KeyboardInterrupt:
        # Ctrl+Q interrupts the main thread even while it is blocked in input().
        pass

