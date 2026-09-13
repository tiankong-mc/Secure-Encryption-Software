# ui.py —— 入口模块
from constants import VERSION, WEB_PORT, LANG_DIR, ISSUES_URL, ABOUT_TEXT
from i18n import init_i18n, tr, get_manager

# 在导入 UI 类之前初始化 i18n
init_i18n(LANG_DIR)

from ui_styles import DARK_STYLE, LIGHT_STYLE
from ui_utils import set_window_display_affinity, protect_window
from ui_web import start_web_server, stop_web_server, is_web_running, flask_app
from ui_viewer import FileViewer
from ui_log import LogDialog
from ui_dialogs import AuthDialog, DeleteAuthDialog, UploadDialog
from ui_settings import SettingsDialog
from ui_login import LoginDialog, SetupWizard
from ui_main import MainWindow

__all__ = [
    'VERSION', 'WEB_PORT', 'LANG_DIR', 'ISSUES_URL', 'ABOUT_TEXT',
    'init_i18n', 'tr', 'get_manager',
    'DARK_STYLE', 'LIGHT_STYLE',
    'set_window_display_affinity', 'protect_window',
    'start_web_server', 'stop_web_server', 'is_web_running', 'flask_app',
    'FileViewer', 'LogDialog',
    'AuthDialog', 'DeleteAuthDialog', 'UploadDialog',
    'SettingsDialog',
    'LoginDialog', 'SetupWizard',
    'MainWindow',
]
