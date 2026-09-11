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

        if getattr(settings_dialog, 'is_recovery_login', False):
            self.stack.setCurrentIndex(1)

    # ============================================================
    #  解锁视图构建（可被 on_config_changed 重新调用）
    # ============================================================
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
        ordered = ['password', 'question', 'totp', 'email']
        for i, key in enumerate(ordered):
            row = self._build_method_row(key)
            self.method_rows[key] = row
            c1.addWidget(row)
            c1.addWidget(make_hline())

        # 紧急恢复代码（独立行，不参与启用开关）
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

        # ---------- 防护与日志 ----------
        ul.addWidget(make_section_title("安全防护"))
        card2, c2 = make_card()

        self.screenshot_cb = QCheckBox()
        self.screenshot_cb.setChecked(
            self.settings_dialog.auth.settings_dict.get('screenshot_protection', False))
        self.screenshot_cb.stateChanged.connect(
            self.settings_dialog.toggle_screenshot_protection)
        row1, _ = make_setting_row(tr("security.screenshot"), self.screenshot_cb)
        c2.addWidget(row1)
        c2.addWidget(make_hline())

        self.log_cb = QCheckBox()
        self.log_cb.setChecked(
            self.settings_dialog.auth.settings_dict.get('log_enabled', True))
        self.log_cb.stateChanged.connect(self.settings_dialog.toggle_log)
        row2, _ = make_setting_row(tr("security.log"), self.log_cb)
        c2.addWidget(row2)

        ul.addWidget(card2)
        ul.addStretch()
        return unlocked

    # ============================================================
    #  单行验证方式
    # ============================================================
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
        enable_cb.setChecked(auth.is_method_enabled(method_name))
        enable_cb.setEnabled(configured)
        enable_cb.stateChanged.connect(
            lambda s, k=method_name: self._on_enable_changed(k, s))
        rl.addWidget(enable_cb)

        action_btn = QPushButton("修改")
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

    # ============================================================
    #  启用开关
    # ============================================================
    def _on_enable_changed(self, method_name, state):
        enabled = (state == Qt.Checked)
        ok = self.settings_dialog.auth.set_method_enabled(method_name, enabled)
        if not ok:
            # 被拒绝（最后一个启用的方法不能禁用），把复选框恢复
            self.settings_dialog.auth.set_method_enabled(method_name, True)
            self.refresh_rows()
            QMessageBox.warning(self, "提示", "至少需要保留一种启用的验证方式。")
            return
        state_str = "启用" if enabled else "禁用"
        self.settings_dialog.storage.log(f"验证方式 {method_name}: {state_str}")

    def refresh_rows(self):
        """更新每行的复选框状态（不重建视图）。"""
        auth = self.settings_dialog.auth
        for key, row in self.method_rows.items():
            for child in row.findChildren(QCheckBox):
                enabled = auth.is_method_enabled(key)
                child.blockSignals(True)
                child.setChecked(enabled)
                child.setEnabled(key in auth.get_configured_methods())
                child.blockSignals(False)

    # ============================================================
    #  外部调用：当某个验证方式被修改后刷新整页
    # ============================================================
    def on_config_changed(self):
        """当密码/问题/TOTP/邮箱被修改后，重建解锁视图以刷新状态。"""
        # 保存当前显示状态
        was_unlocked = (self.stack.currentIndex() == 1)

        # 移除旧的解锁视图
        if self.stack.count() >= 2:
            old = self.stack.widget(1)
            self.stack.removeWidget(old)
            old.deleteLater()

        # 构建新的解锁视图
        self.stack.addWidget(self._build_unlocked_view())

        if was_unlocked or getattr(self.settings_dialog, 'is_recovery_login', False):
            self.stack.setCurrentIndex(1)

    # ============================================================
    #  验证入口
    # ============================================================
    def do_verify(self):
        if self.settings_dialog._verify_identity():
            self.stack.setCurrentIndex(1)

    # ============================================================
    #  语言切换
    # ============================================================
    def retranslate(self):
        self.locked_hint.setText(tr("security.locked_hint"))
        self.verify_btn.setText(tr("security.verify_button"))
