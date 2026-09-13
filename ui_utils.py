import ctypes
from PyQt5.QtWidgets import QApplication

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def set_window_display_affinity(hwnd, enable=True):
    """对指定 HWND 应用/取消截屏保护。"""
    try:
        ctypes.windll.user32.SetWindowDisplayAffinity(
            hwnd, WDA_EXCLUDEFROMCAPTURE if enable else WDA_NONE
        )
        return True
    except Exception:
        return False


def protect_window(window, enable):
    """对给定 QWidget 应用/取消截屏保护（需窗口已显示）。"""
    if window is None:
        return
    try:
        hwnd = int(window.winId())
        if hwnd:
            set_window_display_affinity(hwnd, enable)
    except Exception:
        pass


def apply_protection_to_all_windows(enable):
    """对当前所有可见的顶层窗口应用/取消截屏保护。"""
    try:
        for w in QApplication.topLevelWidgets():
            if w.isVisible():
                protect_window(w, enable)
    except Exception:
        pass
