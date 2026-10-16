import sys
import os
import ctypes
from PyQt5.QtWidgets import QApplication, QMessageBox, QDialog
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QTimer
from ui import MainWindow, LoginDialog, SetupWizard, get_manager
from storage import StorageManager
from auth import AuthManager
from settings import SettingsManager
from single_instance import SingleInstanceServer, try_send_to_existing_instance
from crash_reporter import install_excepthook


def _get_icon_path():
    if getattr(sys, 'frozen', False):
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, 'myicon_1.ico')


def _parse_encrypt_arg():
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == '--encrypt' and i + 1 < len(args):
            return args[i + 1]
    return None


# 全局 settings 引用，供崩溃处理器延迟读取
_settings_holder = {'sm': None}


def _get_settings():
    return _settings_holder['sm']


def _show_native_error(title, message):
    """不依赖 Qt 的原生弹窗，用于在 QApplication 创建前报错。"""
    try:
        ctypes.windll.user32.MessageBoxW(0, str(message), str(title), 0x10)  # 0x10 = MB_ICONERROR
    except Exception:
        print(f"[{title}] {message}")


def main():
    # 尽早安装崩溃处理器（在 QApplication 之前）
    install_excepthook(_get_settings)

    # 检查 Python 版本兼容性（仅源码运行时提示；打包成 exe 后内部已绑定解释器，无需检查）
    if not getattr(sys, 'frozen', False) and sys.version_info >= (3, 14):
        _show_native_error(
            "SecureVault 启动失败",
            f"检测到当前 Python 版本为 {sys.version_info.major}.{sys.version_info.minor}。\n\n"
            "PyQt5 官方尚未支持 Python 3.14，可能导致程序无法启动或闪退。\n\n"
            "请安装 Python 3.12 或 3.11 后重试。"
        )
        # 这里不直接 return，继续尝试运行，万一以后 PyQt5 支持了呢。
        # 但如果是因为 PyQt5 导入失败导致的，会在最外层捕获。

    pending_encrypt_path = _parse_encrypt_arg()

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("tiankong.SecureVault")
    except Exception:
        pass

    try:
        app = QApplication(sys.argv)
    except Exception as e:
        _show_native_error("SecureVault 启动失败", f"无法初始化图形界面：{e}\n\n"
                            "请确认已正确安装 PyQt5（pip install PyQt5），\n"
                            "且 Python 版本为 3.12 或 3.11。")
        return 1

    icon_path = _get_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    payload = f"encrypt:{pending_encrypt_path}" if pending_encrypt_path else "ping"
    if try_send_to_existing_instance(payload):
        # 修复 BUG：不再静默退出，而是明确提示用户
        _show_native_error(
            "SecureVault 已在运行",
            "检测到 SecureVault 已经在运行中。\n\n"
            "请检查任务栏或系统托盘，或者先关闭后台残留的进程后再试。"
        )
        return 0

    instance_server = SingleInstanceServer()

    main_window_ref = [None]
    pending_queue = []

    def on_encrypt_requested(path):
        if not os.path.isfile(path):
            return
        if main_window_ref[0] is not None:
            main_window_ref[0]._do_upload(path)
        else:
            pending_queue.append(path)

    instance_server.encrypt_requested.connect(on_encrypt_requested)

    if pending_encrypt_path and os.path.isfile(pending_encrypt_path):
        pending_queue.append(pending_encrypt_path)

    # ---------- 初始化 ----------
    try:
        settings = SettingsManager()
        _settings_holder['sm'] = settings
        auth = AuthManager(settings)
        storage = StorageManager(settings)
    except Exception as e:
        QMessageBox.critical(None, "SecureVault 启动失败", str(e))
        return 1
    if storage.index_recovered:
        QMessageBox.warning(
            None, "索引已恢复",
            "主索引损坏，已自动恢复上一份有效备份。最近一次文件列表更改可能未保留。")

    language = auth.settings_dict.get('language', 'zh_CN')
    manager = get_manager()
    if manager and not manager.load(language):
        manager.load('zh_CN')

    if not auth.settings_dict.get('initialized'):
        wizard = SetupWizard(auth, storage)
        if wizard.exec_() != SetupWizard.Accepted:
            return 0
        auth.settings_dict = auth.settings.load_settings()
        auth._init_auth_data()

    login = LoginDialog(auth, storage)
    if login.exec_() != QDialog.Accepted:
        return 0

    is_recovery_login = login.recovery_accepted if hasattr(login, 'recovery_accepted') else False
    window = MainWindow(storage, auth, is_recovery_login)
    main_window_ref[0] = window
    window.show()

    def process_pending():
        while pending_queue:
            path = pending_queue.pop(0)
            if os.path.isfile(path):
                window._do_upload(path)

    QTimer.singleShot(300, process_pending)

    return app.exec_()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        # 捕获最外层的未处理异常，防止静默退出
        _show_native_error("SecureVault 致命错误", f"程序遇到未捕获的异常：\n{e}")
        sys.exit(1)
