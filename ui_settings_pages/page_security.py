from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QStackedWidget, QMessageBox, QCheckBox, QGroupBox)
from PyQt5.QtCore import Qt
from i18n import tr


class SecurityPage(QWidget):
    """安全页：初始锁定，验证身份后显示所有安全选项。"""

    def __init__(self, settings_dialog):
        super().__init__()
        self.settings_dialog = settings_dialog
        self.stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        # 锁定视图
        self.locked_view = QWidget()
        lv = QVBoxLayout(self.locked_view)
        lv.addStretch()
        self.locked_hint = QLabel(tr("security.locked_hint"))
        self.locked_hint.setAlignment(Qt.AlignCenter)
        self.locked_hint.setStyleSheet("font-size: 14pt; color: #888;")
        lv.addWidget(self.locked_hint)
        self.verify_btn = QPushButton(tr("security.verify_button"))
        self.verify_btn.setFixedWidth(160)
        self.verify_btn.clicked.connect(self.do_verify)
        wrap = QHBoxLayout(); wrap.addStretch(); wrap.addWidget(self.verify_btn); wrap.addStretch()
        lv.addLayout(wrap)
        lv.addStretch()

        # 解锁视图
        self.unlocked_view = QWidget()
        uv = QVBoxLayout(self.unlocked_view)
        title = QLabel(tr("security.title"))
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        uv.addWidget(title)

        self.btn_pw = QPushButton(tr("security.password")); self.btn_pw.clicked.connect(self.settings_dialog.change_password); uv.addWidget(self.btn_pw)
        self.btn_q = QPushButton(tr("security.questions")); self.btn_q.clicked.connect(self.settings_dialog.change_questions); uv.addWidget(self.btn_q)
        self.btn_totp = QPushButton(tr("security.totp")); self.btn_totp.clicked.connect(self.settings_dialog.change_totp); uv.addWidget(self.btn_totp)
        self.btn_email = QPushButton(tr("security.email")); self.btn_email.clicked.connect(self.settings_dialog.change_email); uv.addWidget(self.btn_email)
        self.btn_recovery = QPushButton(tr("security.recovery")); self.btn_recovery.clicked.connect(self.settings_dialog.generate_recovery); uv.addWidget(self.btn_recovery)

        group = QGroupBox()
        gl = QVBoxLayout()
        self.screenshot_cb = QCheckBox(tr("security.screenshot"))
        self.screenshot_cb.setChecked(self.settings_dialog.auth.settings_dict.get('screenshot_protection', False))
        self.screenshot_cb.stateChanged.connect(self.settings_dialog.toggle_screenshot_protection)
        gl.addWidget(self.screenshot_cb)
        self.log_cb = QCheckBox(tr("security.log"))
        self.log_cb.setChecked(self.settings_dialog.auth.settings_dict.get('log_enabled', True))
        self.log_cb.stateChanged.connect(self.settings_dialog.toggle_log)
        gl.addWidget(self.log_cb)
        group.setLayout(gl)
        uv.addWidget(group)
        uv.addStretch()

        self.stack.addWidget(self.locked_view)
        self.stack.addWidget(self.unlocked_view)

        # 恢复登录时直接解锁
        if getattr(settings_dialog, 'is_recovery_login', False):
            self.stack.setCurrentWidget(self.unlocked_view)

    def do_verify(self):
        if self.settings_dialog._verify_identity():
            self.stack.setCurrentWidget(self.unlocked_view)

    def retranslate(self):
        self.locked_hint.setText(tr("security.locked_hint"))
        self.verify_btn.setText(tr("security.verify_button"))
        self.btn_pw.setText(tr("security.password"))
        self.btn_q.setText(tr("security.questions"))
        self.btn_totp.setText(tr("security.totp"))
        self.btn_email.setText(tr("security.email"))
        self.btn_recovery.setText(tr("security.recovery"))
        self.screenshot_cb.setText(tr("security.screenshot"))
        self.log_cb.setText(tr("security.log"))
