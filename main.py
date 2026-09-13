import sys
import os
from PyQt5.QtWidgets import QApplication, QMessageBox, QDialog
from ui import MainWindow, LoginDialog, SetupWizard, get_manager
from storage import StorageManager
from auth import AuthManager
from settings import SettingsManager

def main():
    # 检查是否为更新后首次启动
    if len(sys.argv) > 1 and sys.argv[1] == '--updated':
        # 可以显示一个提示，但不必须
        pass

    app = QApplication(sys.argv)
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
        wizard = SetupWizard(auth)
        if wizard.exec_() != SetupWizard.Accepted:
            return 0
        auth.settings_dict = auth.settings.load_settings()
        auth._init_auth_data()

    login = LoginDialog(auth, storage)
    if login.exec_() != QDialog.Accepted:
        return 0

    is_recovery_login = login.recovery_accepted if hasattr(login, 'recovery_accepted') else False
    window = MainWindow(storage, auth, is_recovery_login)
    window.show()
    return app.exec_()

if __name__ == '__main__':
    sys.exit(main())
