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

    # 首次运行引导
    if not auth.settings_dict.get('initialized'):
        wizard = SetupWizard(auth)
        if wizard.exec_() != SetupWizard.Accepted:
            sys.exit(0)
        auth.settings_dict = auth.settings.load_settings()
        auth._init_auth_data()

    # 登录验证（若失败5次会触发备份并退出）
    login = LoginDialog(auth)
    if login.exec_() != QDialog.Accepted:
        sys.exit(0)

    # 启动主窗口
    window = MainWindow(storage, auth)
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
