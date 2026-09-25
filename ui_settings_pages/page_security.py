from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QStackedWidget, QMessageBox, QCheckBox)
from PyQt5.QtCore import Qt
from i18n import tr
from ui_settings_style import (SettingsPage, make_page_title, make_section_title,
                                make_card, make_hline, make_setting_row)


METHOD_LABELS = {
    'password': ('security.password', 'password'),
    'question': ('security.questions', 'question'),
    'totp':     ('security.totp', 'totp'),
    'email':    ('security.email', 'email'),
}


class SecurityPage(SettingsPage):
    def __init__(self, settings_dialog):
        super().__init__()
        self.settings_dialog = settings_dialog
        self.method_rows = {}

        self.stack = QStackedWidget()
        self.layout().addWidget(self.stack)

        # ----- 锁定视图 -----
        locked = QWidget()
        ll = QVBoxLayout(locked)
        ll.addStretch()
        self.locked_hint = QLabel(tr("security.locked_hint"))
        self.locked_hint.setAlignment(Qt.AlignCenter)
        self.locked_hint.setStyleSheet("font-size: 14pt; color: #888;")
        ll.addWidget(self.locked_hint)
        ll.addSpacing(20)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.verify_btn = QPushButton(tr("security.verify_button"))
        self.verify_btn.setFixedWidth(180)
        self.verify_btn.setMinimumHeight(38)
        self.verify_btn.clicked.connect(self.do_verify)
        btn_row.addWidget(self.verify_btn)
        btn_row.addStretch()
        ll.addLayout(btn_row)
        ll.addStretch()
        self.stack.addWidget(locked)

        # ----- 解锁视图 -----
        self.stack.addWidget(self._build_unlocked_view())

        if getattr(settings_dialog, '_unlocked', False):
            self.stack.setCurrentIndex(1)

    def _build_unlocked_view(self):
        unlocked = QWidget()
        ul = QVBoxLayout(unlocked)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.setSpacing(14)

        ul.addWidget(make_page_title(tr("security.title")))

        # ---------- 验证方式 ----------
        ul.addWidget(make_section_title("验证方式"))
        card1, c1 = make_card()
        self.method_rows = {}
        for i, key in enumerate(['password', 'question', 'totp', 'email']):
            row = self._build_method_row(key)
            self.method_rows[key] = row
            c1.addWidget(row)
            c1.addWidget(make_hline())

        recovery_row = QWidget()
        rl = QHBoxLayout(recovery_row)
        rl.setContentsMargins(10, 8, 10, 8)
        rl.addWidget(QLabel(tr("security.recovery")))
        rl.addStretch()
        recovery_btn = QPushButton("生成")
        recovery_btn.setMinimumWidth(80)
        recovery_btn.clicked.connect(self.settings_dialog.generate_recovery)
        rl.addWidget(recovery_btn)
        c1.addWidget(recovery_row)
        ul.addWidget(card1)

        # ---------- 存储位置 ----------
        ul.addWidget(make_section_title("存储位置"))
        ul.addWidget(self._build_storage_card())

        # ---------- 安全防护 ----------
        ul.addWidget(make_section_title("安全防护"))
        card3, c3 = make_card()

        self.screenshot_cb = QCheckBox()
        self.screenshot_cb.setChecked(
            self.settings_dialog.auth.settings_dict.get('screenshot_protection', False))
        self.screenshot_cb.stateChanged.connect(
            self.settings_dialog.toggle_screenshot_protection)
        row_screenshot, _ = make_setting_row(tr("security.screenshot"), self.screenshot_cb)
        c3.addWidget(row_screenshot)
        c3.addWidget(make_hline())

        self.log_cb = QCheckBox()
        self.log_cb.setChecked(
            self.settings_dialog.auth.settings_dict.get('log_enabled', True))
        self.log_cb.stateChanged.connect(self.settings_dialog.toggle_log)
        row_log, _ = make_setting_row(tr("security.log"), self.log_cb)
        c3.addWidget(row_log)
        c3.addWidget(make_hline())

        # 修复 #3：改用语义化变量名，避免和下面保险库备份卡片的 row 变量重名
        self.secure_delete_cb = QCheckBox()
        self.secure_delete_cb.setChecked(
            self.settings_dialog.auth.settings_dict.get('secure_delete', False))
        self.secure_delete_cb.stateChanged.connect(
            self.settings_dialog.toggle_secure_delete)
        row_secure, _ = make_setting_row("安全擦除（删除时覆写数据）", self.secure_delete_cb)
        c3.addWidget(row_secure)
        tip = QLabel("启用后删除文件时会对数据进行多次覆写，速度较慢但难以被恢复工具还原。")
        tip.setStyleSheet("color: #888; font-size: 8pt; padding: 4px 10px;")
        tip.setWordWrap(True)
        c3.addWidget(tip)

        ul.addWidget(card3)

        # ---------- 保险库备份 ----------
        ul.addWidget(make_section_title("保险库备份"))
        card4, c4 = make_card()
        export_btn = QPushButton("导出备份")
        export_btn.setMinimumWidth(100)
        export_btn.clicked.connect(self.settings_dialog.export_vault_backup)
        row_export, _ = make_setting_row("导出保险库", export_btn)
        c4.addWidget(row_export)
        c4.addWidget(make_hline())
        import_btn = QPushButton("导入备份")
        import_btn.setMinimumWidth(100)
        import_btn.clicked.connect(self.settings_dialog.import_vault_backup)
        row_import, _ = make_setting_row("与当前保险库合并", import_btn)
        c4.addWidget(row_import)
        ul.addWidget(card4)

        ul.addStretch()
        return unlocked

    def _build_storage_card(self):
        card, c = make_card()
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 8, 10, 8)
        label = QLabel("加密文件目录")
        label.setObjectName("SettingLabel")
        rl.addWidget(label)
        path_text = self.settings_dialog.storage.SECRET_DIR
        self.secret_dir_label = QLabel(path_text)
        self.secret_dir_label.setStyleSheet("color: #888; font-size: 9pt;")
        self.secret_dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rl.addWidget(self.secret_dir_label, 1)
        btn = QPushButton("修改")
        btn.setMinimumWidth(80)
        btn.clicked.connect(self.settings_dialog.change_secret_dir)
        rl.addWidget(btn)
        c.addWidget(row)
        return card

    def _build_method_row(self, key):
        label_key, method_name = METHOD_LABELS[key]
        auth = self.settings_dialog.auth
        configured = key in auth.get_configured_methods()
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 8, 10, 8)
        rl.setSpacing(10)
        name_label = QLabel(tr(label_key))
        name_label.setObjectName("SettingLabel")
        rl.addWidget(name_label)
        status = QLabel("已配置" if configured else "未配置")
        status.setStyleSheet("color: #888; font-size: 9pt; padding-left: 6px;")
        rl.addWidget(status)
        rl.addStretch()
        enable_cb = QCheckBox("启用")
        enable_cb.setChecked(configured and auth.is_method_enabled(method_name))
        enable_cb.setEnabled(configured)
        enable_cb.stateChanged.connect(
            lambda s, k=method_name: self._on_enable_changed(k, s))
        rl.addWidget(enable_cb)
        action_btn = QPushButton("修改" if configured else "设置")
        action_btn.setMinimumWidth(80)
        if key == 'password':
            action_btn.clicked.connect(self.settings_dialog.change_password)
        elif key == 'question':
            action_btn.clicked.connect(self.settings_dialog.change_questions)
        elif key == 'totp':
            action_btn.clicked.connect(self.settings_dialog.change_totp)
        elif key == 'email':
            action_btn.clicked.connect(self.settings_dialog.change_email)
        rl.addWidget(action_btn)
        return row

    def _on_enable_changed(self, method_name, state):
        enabled = (state == Qt.Checked)
        ok = self.settings_dialog.auth.set_method_enabled(method_name, enabled)
        if not ok:
            self.settings_dialog.auth.set_method_enabled(method_name, True)
            self.refresh_rows()
            QMessageBox.warning(self, "提示", "至少需要保留一种启用的验证方式。")
            return
        state_str = "启用" if enabled else "禁用"
        self.settings_dialog.storage.log(f"验证方式 {method_name}: {state_str}")

    def refresh_rows(self):
        auth = self.settings_dialog.auth
        for key, row in self.method_rows.items():
            for child in row.findChildren(QCheckBox):
                enabled = auth.is_method_enabled(key)
                child.blockSignals(True)
                child.setChecked(enabled)
                child.setEnabled(key in auth.get_configured_methods())
                child.blockSignals(False)

    def on_config_changed(self):
        was_unlocked = (self.stack.currentIndex() == 1)
        if self.stack.count() >= 2:
            old = self.stack.widget(1)
            self.stack.removeWidget(old)
            old.deleteLater()
        self.stack.addWidget(self._build_unlocked_view())
        if was_unlocked or getattr(self.settings_dialog, '_unlocked', False):
            self.stack.setCurrentIndex(1)

    def do_verify(self):
        if self.settings_dialog._verify_identity():
            self.stack.setCurrentIndex(1)

    def retranslate(self):
        self.locked_hint.setText(tr("security.locked_hint"))
        self.verify_btn.setText(tr("security.verify_button"))
