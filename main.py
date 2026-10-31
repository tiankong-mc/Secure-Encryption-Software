import sys, os, ctypes
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

_settings_holder = {'sm': None}
def _get_settings():
    return _settings_holder['sm']

def _show_native_error(title, message):
    try:
        ctypes.windll.user32.MessageBoxW(0, str(message), str(title), 0x10)
    except Exception:
        print(f"[{title}] {message}")

def main():
    install_excepthook(_get_settings)

    if not getattr(sys, 'frozen', False) and sys.version_info >= (3, 14):
        # PyQt5 官方不支持 Python 3.14：实测会 0xC0000005 崩溃。
        # 这里明确提示并“干净退出”（return 0），避免调试器显示 SystemExit: 1 造成误解。
        try:
            if os.environ.get('SECUREVAULT_SKIP_PY_COMPAT_PROMPT') != '1':
                _show_native_error(
                    "SecureVault 需要 Python 3.12 / 3.13",
                    f"检测到当前 Python 版本为 {sys.version_info.major}.{sys.version_info.minor}。\n\n"
                    "PyQt5 官方尚未支持 Python 3.14，实测会直接崩溃（0xC0000005）。\n\n"
                    "请安装 Python 3.12 或 3.13，并在 VS Code 中切换解释器后再运行。")
        except Exception:
            pass
        return 0

    pending_encrypt_path = _parse_encrypt_arg()

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("tiankong.SecureVault")
    except Exception:
        pass

    try:
        app = QApplication(sys.argv)
    except Exception as e:
        _show_native_error("SecureVault 启动失败", f"无法初始化图形界面：{e}")
        return 1

    icon_path = _get_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    payload = f"encrypt:{pending_encrypt_path}" if pending_encrypt_path else "ping"
    if try_send_to_existing_instance(payload):
        if pending_encrypt_path:
            return 0
        _show_native_error("SecureVault 已在运行", "检测到 SecureVault 已经在运行中。\n\n请检查任务栏或系统托盘。")
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

    try:
        settings = SettingsManager()
        _settings_holder['sm'] = settings

        auth = AuthManager(settings)
        master_key = None
        is_recovery_login = False

        # 修复 P0-1：高安全模式必须在 StorageManager 创建之前解锁
        if settings.is_high_security_enabled():
            from ui_login import HighSecurityUnlockDialog
            unlock_dlg = HighSecurityUnlockDialog(settings, auth, None)
            if unlock_dlg.exec_() != QDialog.Accepted:
                return 0
            master_key = unlock_dlg.master_key
            is_recovery_login = unlock_dlg.recovery_accepted

        storage = StorageManager(settings, master_key=master_key)

    except Exception as e:
        QMessageBox.critical(None, "SecureVault 启动失败", str(e))
        return 1

    if storage.index_recovered:
        QMessageBox.warning(None, "索引已恢复", "主索引损坏，已自动恢复上一份有效备份。")

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

        # 修复 P1：迁移目录成功后，配置才会真正写入 _pending_secret_dir，失败则直接退出
        target_dir = auth.settings_dict.get('_pending_secret_dir')
        if target_dir:
            try:
                storage.migrate_dir(target_dir)
                auth.settings_dict.pop('_pending_secret_dir', None)
                auth._save()
            except Exception as e:
                QMessageBox.critical(None, "目录迁移失败",
                    f"无法迁移到新目录: {e}\n为了安全，程序将退出，您的原数据不受影响。")
                return 1

    # 若上次向导迁移因故失败，这里在下次启动时重试（成功后清除）
    pending_dir = auth.settings_dict.get('_pending_secret_dir')
    if pending_dir:
        try:
            storage.migrate_dir(pending_dir)
            auth.settings_dict.pop('_pending_secret_dir', None)
            auth._save()
        except Exception as e:
            QMessageBox.critical(None, "目录迁移失败",
                f"无法迁移到目录: {e}\n为了安全，程序将退出，您的原数据不受影响。")
            return 1

    if not settings.is_high_security_enabled():
        login = LoginDialog(auth, storage)
        if login.exec_() != QDialog.Accepted:
            return 0
        is_recovery_login = getattr(login, 'recovery_accepted', False)

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
    # 正常退出时不再 sys.exit(0)，避免 VS Code 调试器把 SystemExit: 0 显示成“异常”
    exit_code = 0
    try:
        exit_code = main()
    except Exception as e:
        _show_native_error("SecureVault 致命错误", f"程序遇到未捕获的异常：\n{e}")
        exit_code = 1
    if exit_code:
        sys.exit(exit_code)