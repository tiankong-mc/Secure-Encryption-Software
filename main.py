import sys
from PyQt5.QtWidgets import QApplication, QMessageBox, QWizard, QDialog
from ui import MainWindow, LoginDialog, SetupWizard
from storage import StorageManager
from auth import AuthManager
from settings import SettingsManager
from backup import BackupManager

def main():
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

    login = LoginDialog(auth)
    if login.exec_() != QDialog.Accepted:
        sys.exit(0)

    # 检查是否通过恢复代码登录
    is_recovery_login = login.recovery_accepted if hasattr(login, 'recovery_accepted') else False

    window = MainWindow(storage, auth, is_recovery_login)
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
