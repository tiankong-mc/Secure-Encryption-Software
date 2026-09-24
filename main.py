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


def _get_icon_path():
    """获取图标路径，兼容源码运行与 PyInstaller 打包后的路径"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，资源会被解压到 sys._MEIPASS
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        # 源码运行
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, 'myicon_1.ico')


def _parse_encrypt_arg():
    """解析 --encrypt <path> 参数。返回文件路径或 None。"""
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == '--encrypt' and i + 1 < len(args):
            return args[i + 1]
    return None


def main():
    pending_encrypt_path = _parse_encrypt_arg()

    # Windows 任务栏图标分组：告诉系统这是一个独立应用，否则任务栏可能显示 Python 图标
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("tiankong.SecureVault")
    except Exception:
        pass

    app = QApplication(sys.argv)

    # 设置全局应用图标（影响窗口左上角、任务栏、Alt+Tab 等）
    icon_path = _get_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # 如果本进程由右键菜单启动（带 --encrypt），
    # 且已有主实例在运行，则把请求转发给主实例后本进程直接退出，
    # 避免重复弹出登录窗口。
    if pending_encrypt_path:
        if try_send_to_existing_instance(f"encrypt:{pending_encrypt_path}"):
            return 0

    # 本进程将作为主实例：启动本地服务器接收后续加密请求
    instance_server = SingleInstanceServer()

    # 主窗口引用（延迟绑定）与登录前收到的加密请求队列
    main_window_ref = [None]
    pending_queue = []

    def on_encrypt_requested(path):
        if not os.path.isfile(path):
            return
        if main_window_ref[0] is not None:
            # 主窗口已就绪，直接弹出上传对话框
            main_window_ref[0]._do_upload(path)
        else:
            # 主窗口尚未创建（用户还在登录界面），先缓存
            pending_queue.append(path)

    instance_server.encrypt_requested.connect(on_encrypt_requested)

    # 本进程自身带进来的加密请求也加入队列
    if pending_encrypt_path and os.path.isfile(pending_encrypt_path):
        pending_queue.append(pending_encrypt_path)

    # ---------- 初始化 ----------
    try:
        settings = SettingsManager()
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
        # 首次运行：传入 storage 以支持从备份导入
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

    # 处理登录前收到的加密请求
    def process_pending():
        while pending_queue:
            path = pending_queue.pop(0)
            if os.path.isfile(path):
                window._do_upload(path)

    QTimer.singleShot(300, process_pending)

    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
