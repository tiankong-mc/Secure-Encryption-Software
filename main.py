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


def main():
    # 尽早安装崩溃处理器（在 QApplication 之前）
    install_excepthook(_get_settings)

    pending_encrypt_path = _parse_encrypt_arg()

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("tiankong.SecureVault")
    except Exception:
        pass

    app = QApplication(sys.argv)

    icon_path = _get_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    payload = f"encrypt:{pending_encrypt_path}" if pending_encrypt_path else "ping"
    if try_send_to_existing_instance(payload):
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
    sys.exit(main())
