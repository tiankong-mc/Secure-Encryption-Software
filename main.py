import sys
import os
from PyQt5.QtWidgets import QApplication, QMessageBox, QWizard, QDialog
from ui import MainWindow, LoginDialog, SetupWizard
from storage import StorageManager
from auth import AuthManager
from settings import SettingsManager
from backup import BackupManager

VERSION = "v2.4.5"

def main():
    # 检查是否为更新后首次启动
    if len(sys.argv) > 1 and sys.argv[1] == '--updated':
        # 可以显示一个提示，但不必须
        pass

    app = QApplication(sys.argv)
    settings = SettingsManager()
    auth = AuthManager(settings)
    storage = StorageManager()

    if not auth.settings_dict.get('initialized'):
        wizard = SetupWizard(auth)
        if wizard.exec_() != SetupWizard.Accepted:
            sys.exit(0)
        auth.settings_dict = auth.settings.load_settings()
        auth._init_auth_data()

    login = LoginDialog(auth, storage)
    if login.exec_() != QDialog.Accepted:
        sys.exit(0)

    is_recovery_login = login.recovery_accepted if hasattr(login, 'recovery_accepted') else False
    window = MainWindow(storage, auth, is_recovery_login)
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
