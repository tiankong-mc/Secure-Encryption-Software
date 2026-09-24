"""Windows 资源管理器右键菜单的注册 / 注销。

菜单项：加密该文件（SecureVault）
位置：HKCU\\Software\\Classes\\*\\shell\\SecureVault
      对所有文件生效，命令格式为 "程序" --encrypt %1
      （%1 由 Explorer 自动替换为带引号的完整文件路径）
"""

import os
import sys
import winreg

MENU_KEY = "SecureVault"
MENU_LABEL = "加密该文件（SecureVault）"
SHELL_KEY = r"Software\Classes\*\shell"


def _get_executable_command():
    """
    返回注册表里 command 的模板。
    打包后：'exe路径' --encrypt %1
    源码运行：'pythonw.exe' 'main.py' --encrypt %1
    """
    if getattr(sys, 'frozen', False):
        exe = sys.executable
        return f'"{exe}" --encrypt %1'
    else:
        pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main.py')
        return f'"{pythonw}" "{main_py}" --encrypt %1'


def _get_icon_path():
    if getattr(sys, 'frozen', False):
        return sys.executable
    icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'myicon_1.ico')
    return icon if os.path.exists(icon) else ''


def is_context_menu_enabled():
    """检查当前用户是否已注册右键菜单"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SHELL_KEY + "\\" + MENU_KEY):
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def register_context_menu():
    """注册右键菜单。返回 (成功?, 消息)"""
    try:
        command = _get_executable_command()
        icon = _get_icon_path()
        menu_path = SHELL_KEY + "\\" + MENU_KEY
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, menu_path) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, MENU_LABEL)
            if icon:
                winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon)
        cmd_path = menu_path + "\\command"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_path) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, command)
        return True, "右键菜单已启用"
    except Exception as e:
        return False, f"注册失败：{e}"


def _delete_key_recursive(root, path):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    subkey = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_key_recursive(root, path + "\\" + subkey)
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass


def unregister_context_menu():
    """注销右键菜单。返回 (成功?, 消息)"""
    try:
        menu_path = SHELL_KEY + "\\" + MENU_KEY
        _delete_key_recursive(winreg.HKEY_CURRENT_USER, menu_path)
        return True, "右键菜单已禁用"
    except Exception as e:
        return False, f"注销失败：{e}"
