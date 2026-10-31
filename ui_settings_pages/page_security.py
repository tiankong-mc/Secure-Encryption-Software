import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QMessageBox, QCheckBox, QSizePolicy, QInputDialog, QLineEdit)
from PyQt5.QtCore import Qt
from i18n import tr
from ui_settings_style import (SettingsPage, make_page_title, make_section_title,
                                make_card, make_hline, make_setting_row)


METHOD_LABELS = {
    'password': ('security.method_password', '密码', 'password'),
    'question': ('security.method_question', '安全问题', 'question'),
    'totp':     ('security.method_totp', 'TOTP', 'totp'),
    'email':    ('security.method_email', '邮箱', 'email'),
}


class TipLabel(QLabel):
    """
    自适应高度的多行提示 label。
    """
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setStyleSheet("color: #888; font-size: 8pt; padding: 4px 10px 8px 10px;")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)

    def _recalc_height(self):
        w = self.width()
        if w <= 0:
            return
        inner_width = max(80, w - 24)
        fm = self.fontMetrics()
        rect = fm.boundingRect(
            0, 0, inner_width, 100000,
            Qt.TextWordWrap | Qt.TextExpandTabs,
            self.text())
        needed = rect.height() + 16
        self.setMinimumHeight(needed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recalc_height()

    def showEvent(self, event):
        super().showEvent(event)
        self._recalc_height()

    def setText(self, text):
        super().setText(text)
        self._recalc_height()


class SecurityPage(SettingsPage):
    def __init__(self, settings_dialog):
        super().__init__()
        self.settings_dialog = settings_dialog
        self.method_rows = {}
        self.layout().addWidget(self._build_unlocked_view())

    def _build_unlocked_view(self):
        unlocked = QWidget()
        ul = QVBoxLayout(unlocked)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.setSpacing(14)

        ul.addWidget(make_page_title(tr("security.title")))

        # ---------- 验证方式 ----------
        ul.addWidget(make_section_title(tr("security.section_methods")))
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
        recovery_btn = QPushButton(tr("security.recovery_generate"))
        recovery_btn.setMinimumWidth(80)
        recovery_btn.clicked.connect(self.settings_dialog.generate_recovery)
        rl.addWidget(recovery_btn)
        c1.addWidget(recovery_row)
        ul.addWidget(card1)

        # ---------- 存储位置 ----------
        ul.addWidget(make_section_title(tr("security.section_storage")))
        ul.addWidget(self._build_storage_card())

        # ---------- 安全防护 ----------
        ul.addWidget(make_section_title(tr("security.section_protection")))
        card3, c3 = make_card()

        self.high_sec_cb = QCheckBox()
        self.high_sec_cb.blockSignals(True)
        self.high_sec_cb.setChecked(self.settings_dialog.auth.settings.is_high_security_enabled())
        self.high_sec_cb.blockSignals(False)
        self.high_sec_cb.clicked.connect(self._on_high_sec_clicked)
        row_hsec, _ = make_setting_row(
            tr("security.high_sec", "高安全模式（防范后台恶意程序）"), self.high_sec_cb)
        c3.addWidget(row_hsec)
        self.hsec_tip = TipLabel(
            "开启后，每次启动必须输入独立的主密码。主密码直接参与底层主密钥的保护，可有效防御已获取 Windows 权限的恶意软件。\n"
            "注意：主密码一旦忘记将无法找回（除非使用紧急恢复代码）。")
        c3.addWidget(self.hsec_tip)
        c3.addWidget(make_hline())

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

        self.secure_delete_cb = QCheckBox()
        self.secure_delete_cb.setChecked(
            self.settings_dialog.auth.settings_dict.get('secure_delete', False))
        self.secure_delete_cb.stateChanged.connect(
            self.settings_dialog.toggle_secure_delete)
        row_secure, _ = make_setting_row(tr("security.secure_delete"), self.secure_delete_cb)
        c3.addWidget(row_secure)
        self.secure_delete_tip = TipLabel(tr("security.secure_delete_tip"))
        c3.addWidget(self.secure_delete_tip)
        c3.addWidget(make_hline())

        self.crash_report_cb = QCheckBox()
        self.crash_report_cb.setChecked(
            self.settings_dialog.auth.settings_dict.get('crash_report_enabled', False))
        self.crash_report_cb.stateChanged.connect(
            self.settings_dialog.toggle_crash_report)
        row_crash, _ = make_setting_row(tr("security.crash_report"), self.crash_report_cb)
        c3.addWidget(row_crash)
        self.crash_report_tip = TipLabel(tr("security.crash_report_tip"))
        c3.addWidget(self.crash_report_tip)

        crash_view_btn = QPushButton(tr("security.crash_view"))
        crash_view_btn.setMinimumWidth(160)
        crash_view_btn.clicked.connect(self.open_crash_folder)
        row_crash_view, _ = make_setting_row("", crash_view_btn)
        c3.addWidget(row_crash_view)

        ul.addWidget(card3)

        # ---------- 保险库备份 ----------
        ul.addWidget(make_section_title(tr("security.section_backup")))
        card4, c4 = make_card()
        export_btn = QPushButton(tr("security.backup_export"))
        export_btn.setMinimumWidth(100)
        export_btn.clicked.connect(self.settings_dialog.export_vault_backup)
        row_export, _ = make_setting_row(tr("security.backup_export_row"), export_btn)
        c4.addWidget(row_export)
        c4.addWidget(make_hline())
        import_btn = QPushButton(tr("security.backup_import"))
        import_btn.setMinimumWidth(100)
        import_btn.clicked.connect(self.settings_dialog.import_vault_backup)
        row_import, _ = make_setting_row(tr("security.backup_import_row"), import_btn)
        c4.addWidget(row_import)
        ul.addWidget(card4)

        ul.addStretch()
        return unlocked

    def open_crash_folder(self):
        try:
            from crash_reporter import get_crash_dir
            folder = get_crash_dir()
            if not os.path.isdir(folder):
                QMessageBox.information(
                    self, tr("common.info"),
                    "暂无崩溃报告记录，或目录尚未创建。")
                return
            if os.name == 'nt':
                os.startfile(folder)
            else:
                import webbrowser
                webbrowser.open('file://' + folder)
        except Exception as e:
            QMessageBox.warning(self, tr("common.error"), str(e))

    def _on_high_sec_clicked(self, checked):
        auth = self.settings_dialog.auth
        settings = auth.settings

        if checked:
            if not auth.password_hash:
                QMessageBox.warning(self, "提示", "必须先在上方启用并设置密码，才能开启高安全模式。")
                self.high_sec_cb.setChecked(False)
                return
            pw, ok = QInputDialog.getText(
                self, "确认主密码",
                "请输入您当前的登录密码，它将被作为主密码用于保护底层密钥：",
                QLineEdit.Password)
            if not ok or not pw:
                self.high_sec_cb.setChecked(False)
                return
            if not auth.verify_password(pw):
                QMessageBox.warning(self, "错误", "密码验证失败。")
                self.high_sec_cb.setChecked(False)
                return
            try:
                new_code = auth.generate_recovery_code(send_email=False)
                settings.enable_high_security(pw, new_code)
                auth.clear_recovery_code()
                email_sent = auth.send_high_security_enabled_email()
                msg = (f"高安全模式已开启。下次启动需要输入该密码。\n\n"
                       f"您的新紧急恢复代码是：\n{new_code}\n\n"
                       "请务必截图或保存在安全的地方！忘记主密码时将无法找回。")
                if email_sent:
                    msg += "\n\n（一封无敏感信息的提示邮件已发送至您的邮箱。）"
                QMessageBox.information(self, "开启成功 - 请保存恢复代码", msg)
                self.settings_dialog.storage.log("开启高安全模式")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"开启失败：{e}")
                self.high_sec_cb.setChecked(False)
        else:
            pw, ok = QInputDialog.getText(
                self, "关闭高安全模式", "请输入主密码以关闭此模式：", QLineEdit.Password)
            if not ok or not pw:
                self.high_sec_cb.setChecked(True)
                return
            try:
                master_key = settings.unlock_master_key(password=pw)
                settings.disable_high_security(master_key)
                QMessageBox.information(self, "成功", "高安全模式已关闭。")
                self.settings_dialog.storage.log("关闭高安全模式")
            except Exception as e:
                QMessageBox.warning(self, "错误", str(e))
                self.high_sec_cb.setChecked(True)

    def _build_storage_card(self):
        card, c = make_card()
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 8, 10, 8)
        label = QLabel(tr("security.storage_dir"))
        label.setObjectName("SettingLabel")
        rl.addWidget(label)
        path_text = self.settings_dialog.storage.SECRET_DIR
        self.secret_dir_label = QLabel(path_text)
        self.secret_dir_label.setStyleSheet("color: #888; font-size: 9pt;")
        self.secret_dir_label.setWordWrap(True)
        self.secret_dir_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.secret_dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rl.addWidget(self.secret_dir_label, 1)
        btn = QPushButton(tr("security.storage_change"))
        btn.setMinimumWidth(80)
        btn.clicked.connect(self.settings_dialog.change_secret_dir)
        rl.addWidget(btn)
        c.addWidget(row)
        return card

    def _build_method_row(self, key):
        label_key, fallback_name, method_name = METHOD_LABELS[key]
        auth = self.settings_dialog.auth
        configured = key in auth.get_configured_methods()
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 8, 10, 8)
        rl.setSpacing(10)
        name_label = QLabel(tr(label_key, fallback_name))
        name_label.setObjectName("SettingLabel")
        rl.addWidget(name_label)
        status = QLabel(tr("security.configured") if configured
                        else tr("security.not_configured"))
        status.setStyleSheet("color: #888; font-size: 9pt; padding-left: 6px;")
        rl.addWidget(status)
        rl.addStretch()
        enable_cb = QCheckBox(tr("security.enable"))
        enable_cb.setChecked(configured and auth.is_method_enabled(method_name))
        enable_cb.setEnabled(configured)
        enable_cb.stateChanged.connect(
            lambda s, k=method_name: self._on_enable_changed(k, s))
        rl.addWidget(enable_cb)
        action_btn = QPushButton(tr("security.action_modify") if configured
                                 else tr("security.action_setup"))
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
            QMessageBox.warning(self, tr("common.warning"),
                                tr("security.need_at_least_one"))
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
        # 重建布局
        while self.layout().count():
            item = self.layout().takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.layout().addWidget(self._build_unlocked_view())

    def retranslate(self):
        self.on_config_changed()
