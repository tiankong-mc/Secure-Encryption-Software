import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QComboBox, QStackedWidget, QDialogButtonBox,
                              QMessageBox, QWidget, QCheckBox, QGroupBox, QFileDialog,
                              QApplication)


class AuthDialog(QDialog):
    """二次验证（高级文件）"""
    def __init__(self, parent, auth_manager, allowed_methods, entry_id, storage):
        super().__init__(parent)
        self.auth = auth_manager
        enabled = set(auth_manager.get_enabled_methods())
        self.allowed_methods = [m for m in allowed_methods if m in enabled]
        self.entry_id = entry_id
        self.storage = storage
        self.setWindowTitle("二次验证")
        self.setModal(True)
        self.resize(400, 300)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("请通过以下任意一种方式验证："))
        self.stack = QStackedWidget()
        self.widgets = {}
        for m in self.allowed_methods:
            if m == 'password':
                w = self.create_password_widget(); self.stack.addWidget(w); self.widgets['password'] = w
            elif m == 'question':
                w = self.create_question_widget(); self.stack.addWidget(w); self.widgets['question'] = w
            elif m == 'totp':
                w = self.create_totp_widget(); self.stack.addWidget(w); self.widgets['totp'] = w
            elif m == 'email':
                w = self.create_email_widget(); self.stack.addWidget(w); self.widgets['email'] = w
        layout.addWidget(self.stack)
        self.method_combo = QComboBox()
        self.method_combo.addItems(self.widgets.keys())
        self.method_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        layout.addWidget(self.method_combo)
        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_box.accepted.connect(self.accept)
        self.btn_box.rejected.connect(self.reject)
        layout.addWidget(self.btn_box)
        self.setLayout(layout)

    def create_password_widget(self):
        w = QWidget(); l = QVBoxLayout()
        l.addWidget(QLabel("输入密码："))
        self.pw_input = QLineEdit(); self.pw_input.setEchoMode(QLineEdit.Password)
        l.addWidget(self.pw_input); w.setLayout(l); return w

    def create_question_widget(self):
        w = QWidget(); l = QVBoxLayout()
        l.addWidget(QLabel("选择安全问题："))
        self.question_combo = QComboBox()
        self.question_combo.addItems(self.auth.get_questions())
        l.addWidget(self.question_combo)
        l.addWidget(QLabel("输入答案："))
        self.answer_input = QLineEdit(); self.answer_input.setEchoMode(QLineEdit.Password)
        l.addWidget(self.answer_input); w.setLayout(l); return w

    def create_totp_widget(self):
        w = QWidget(); l = QVBoxLayout()
        l.addWidget(QLabel("输入 Authenticator 动态码："))
        self.totp_input = QLineEdit(); l.addWidget(self.totp_input)
        w.setLayout(l); return w

    def create_email_widget(self):
        w = QWidget(); l = QVBoxLayout()
        l.addWidget(QLabel("输入邮箱验证码："))
        self.email_code_input = QLineEdit(); l.addWidget(self.email_code_input)
        self.send_btn = QPushButton("发送验证码")
        self.send_btn.clicked.connect(self.send_email_code)
        l.addWidget(self.send_btn)
        self.email_code = None
        w.setLayout(l); return w

    def send_email_code(self):
        self.email_code = self.auth.send_verification_code()
        if self.email_code:
            QMessageBox.information(self, "提示", "验证码已发送至您的邮箱")
        else:
            QMessageBox.warning(self, "错误", "邮件发送失败，请检查配置")

    # ---------- 验证逻辑 ----------
    def accept(self):
        method = self.method_combo.currentText()
        ok = False
        if method == 'password':
            ok = self.auth.verify_password(self.pw_input.text())
        elif method == 'question':
            ok = self.auth.verify_question(self.question_combo.currentText(), self.answer_input.text())
        elif method == 'totp':
            ok = self.auth.verify_totp(self.totp_input.text())
        elif method == 'email':
            ok = (self.email_code_input.text() == self.email_code)
        if ok:
            self.auth.reset_fail_count()
            self.storage.log(f"二次验证成功 (文件ID: {self.entry_id})")
            super().accept()
            return

        count = self.auth.increment_fail_count()
        self.storage.log(f"二次验证失败 (文件ID: {self.entry_id})")

        if count >= 5:
            self.storage.log(
                f"二次验证错误次数过多，触发紧急处理 (文件ID: {self.entry_id})")
            QMessageBox.warning(
                self, "验证失败",
                f"失败 {count} 次。\n\n"
                "错误次数已达上限，即将执行紧急处理：\n"
                "  · 将该文件发送到绑定邮箱\n"
                "  · 删除该文件的本地加密副本\n"
                "  · 退出程序")
            self._trigger_emergency_action()
            return

        QMessageBox.warning(self, "验证失败", f"失败 {count} 次")

    # ---------- 紧急处理 ----------
    def _has_usable_email(self):
        """判断邮箱验证方式是否已配置且处于启用状态。"""
        cfg = self.auth.email_config or {}
        required = ('smtp_server', 'port', 'sender_email', 'password', 'receiver_email')
        if not all(cfg.get(k) for k in required):
            return False
        try:
            if 'email' not in self.auth.get_enabled_methods():
                return False
        except Exception:
            return False
        return True

    def _trigger_emergency_action(self):
        """
        针对当前 entry_id 的紧急处理：
          · 邮箱可用：把该文件发到邮箱 → 删除该文件的本地加密副本 → 退出程序
          · 邮箱不可用：直接退出程序，保留本地文件
        """
        storage = self.storage
        entry = storage.get_entry_by_id(self.entry_id)
        if not entry:
            storage.log("紧急处理：找不到目标记录，程序将退出")
            QApplication.quit()
            return

        # 情况一：未配置或未启用邮箱 → 直接退出，不删除任何文件
        if not self._has_usable_email():
            storage.log("紧急处理：未配置或未启用邮箱验证方式，程序退出，本地文件保留")
            QMessageBox.critical(
                self, "安全退出",
                "错误次数过多，且未配置或未启用邮箱验证方式。\n\n"
                "为避免误删数据，本地加密文件将保留，程序将退出。")
            QApplication.quit()
            return

        email_cfg = self.auth.email_config
        to_email = email_cfg.get('receiver_email')

        # 找到该文件当前实际存在的路径（优先 secret_path，其次 user_path）
        vault_path = entry.get('secret_path')
        user_path = entry.get('user_path')
        if not (vault_path and os.path.exists(vault_path)):
            if user_path and os.path.exists(user_path):
                vault_path = user_path
            else:
                storage.log(f"紧急处理：文件已不存在 ({entry['id']})，程序将退出")
                QMessageBox.critical(
                    self, "文件丢失",
                    "错误次数过多，但目标加密文件已不存在。\n程序将退出。")
                QApplication.quit()
                return

        display_name = entry.get('original_name', 'file') + '.vault'
        files = [(vault_path, display_name)]

        # 情况二：先把该文件发到邮箱
        from backup import BackupManager
        try:
            storage.log(f"紧急处理：正在发送文件 {entry.get('original_name')} 到 {to_email}")
            BackupManager.send_multiple_vault_files(files, to_email, email_cfg)
            storage.log("紧急处理：邮件发送成功")
        except Exception as e:
            storage.log(f"紧急处理：邮件发送失败 {e}")
            QMessageBox.critical(
                self, "发送失败",
                f"将该文件发送到邮箱失败：\n{e}\n\n"
                "为避免误删数据，本地加密文件将保留，程序将退出。")
            QApplication.quit()
            return

        # 情况三：邮件发送成功后再删除该文件的本地副本
        storage.log(f"紧急处理：删除本地文件 {entry.get('original_name')}")
        try:
            storage.remove_entry(self.entry_id, destroy=True)
            QMessageBox.information(
                self, "紧急处理完成",
                f"文件已发送到：{to_email}\n"
                f"本地加密副本已删除。\n\n程序将退出。")
        except Exception as e:
            storage.log(f"紧急处理：删除失败 {e}")
            QMessageBox.warning(
                self, "删除失败",
                f"文件已发送到：{to_email}\n\n"
                f"但本地文件删除失败：\n{e}\n\n"
                f"请手动清理后退出程序。")

        QApplication.quit()


class DeleteAuthDialog(QDialog):
    """身份验证（删除/修改敏感操作）"""
    def __init__(self, parent, auth_manager, allowed_methods):
        super().__init__(parent)
        self.auth = auth_manager
        self.allowed_methods = allowed_methods
        self.setWindowTitle("身份验证")
        self.setModal(True)
        self.resize(400, 300)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("请验证身份以继续操作："))
        self.stack = QStackedWidget()
        self.widgets = {}
        for m in allowed_methods:
            if m == 'password':
                w = self.create_password_widget(); self.stack.addWidget(w); self.widgets['password'] = w
            elif m == 'question':
                w = self.create_question_widget(); self.stack.addWidget(w); self.widgets['question'] = w
            elif m == 'totp':
                w = self.create_totp_widget(); self.stack.addWidget(w); self.widgets['totp'] = w
            elif m == 'email':
                w = self.create_email_widget(); self.stack.addWidget(w); self.widgets['email'] = w
        layout.addWidget(self.stack)
        self.method_combo = QComboBox()
        self.method_combo.addItems(self.widgets.keys())
        self.method_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        layout.addWidget(self.method_combo)
        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_box.accepted.connect(self.accept)
        self.btn_box.rejected.connect(self.reject)
        layout.addWidget(self.btn_box)
        self.setLayout(layout)

    def create_password_widget(self):
        w = QWidget(); l = QVBoxLayout()
        l.addWidget(QLabel("输入密码："))
        self.pw_input = QLineEdit(); self.pw_input.setEchoMode(QLineEdit.Password)
        l.addWidget(self.pw_input); w.setLayout(l); return w

    def create_question_widget(self):
        w = QWidget(); l = QVBoxLayout()
        l.addWidget(QLabel("选择安全问题："))
        self.question_combo = QComboBox()
        self.question_combo.addItems(self.auth.get_questions())
        l.addWidget(self.question_combo)
        l.addWidget(QLabel("输入答案："))
        self.answer_input = QLineEdit(); self.answer_input.setEchoMode(QLineEdit.Password)
        l.addWidget(self.answer_input); w.setLayout(l); return w

    def create_totp_widget(self):
        w = QWidget(); l = QVBoxLayout()
        l.addWidget(QLabel("输入 Authenticator 动态码："))
        self.totp_input = QLineEdit(); l.addWidget(self.totp_input)
        w.setLayout(l); return w

    def create_email_widget(self):
        w = QWidget(); l = QVBoxLayout()
        l.addWidget(QLabel("输入邮箱验证码："))
        self.email_code_input = QLineEdit(); l.addWidget(self.email_code_input)
        self.send_btn = QPushButton("发送验证码")
        self.send_btn.clicked.connect(self.send_email_code)
        l.addWidget(self.send_btn)
        self.email_code = None
        w.setLayout(l); return w

    def send_email_code(self):
        self.email_code = self.auth.send_verification_code()
        if self.email_code:
            QMessageBox.information(self, "提示", "验证码已发送至您的邮箱")
        else:
            QMessageBox.warning(self, "错误", "邮件发送失败，请检查配置")

    def accept(self):
        method = self.method_combo.currentText()
        ok = False
        if method == 'password':
            ok = self.auth.verify_password(self.pw_input.text())
        elif method == 'question':
            ok = self.auth.verify_question(self.question_combo.currentText(), self.answer_input.text())
        elif method == 'totp':
            ok = self.auth.verify_totp(self.totp_input.text())
        elif method == 'email':
            ok = (self.email_code_input.text() == self.email_code)
        if ok:
            super().accept()
        else:
            QMessageBox.warning(self, "验证失败", "身份验证未通过，请重试或取消")


class UploadDialog(QDialog):
    """上传文件选项"""
    def __init__(self, parent, file_path):
        super().__init__(parent)
        self.file_path = file_path
        self.user_dest = None
        self.is_advanced = False
        self.second_methods = []
        self.delete_source = False
        self.setWindowTitle("上传加密选项")
        self.setModal(True)
        self.resize(420, 380)
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"文件：{os.path.basename(file_path)}"))
        self.dest_btn = QPushButton("选择用户存储位置（可选）")
        self.dest_btn.clicked.connect(self.select_dest)
        self.dest_label = QLabel("未选择")
        layout.addWidget(self.dest_btn)
        layout.addWidget(self.dest_label)
        self.advanced_cb = QCheckBox("标记为高级文件（需二次验证）")
        self.advanced_cb.toggled.connect(self.toggle_advanced)
        layout.addWidget(self.advanced_cb)
        # 加密成功后删除原文件
        self.delete_source_cb = QCheckBox("加密成功后删除原文件")
        layout.addWidget(self.delete_source_cb)
        self.method_group = QGroupBox("二次验证方式（高级文件时可用）")
        self.method_group.setEnabled(False)
        ml = QVBoxLayout()
        self.totp_cb = QCheckBox("TOTP (Authenticator)")
        self.email_cb = QCheckBox("邮箱验证码")
        self.question_cb = QCheckBox("安全问题")
        self.password_cb = QCheckBox("密码")
        enabled = set(parent.auth.get_enabled_methods()) if hasattr(parent, 'auth') else set()
        for method, checkbox in (
                ('totp', self.totp_cb), ('email', self.email_cb),
                ('question', self.question_cb), ('password', self.password_cb)):
            checkbox.setEnabled(method in enabled)
            if method not in enabled:
                checkbox.setToolTip("此验证方式尚未配置或未启用")
        ml.addWidget(self.totp_cb); ml.addWidget(self.email_cb)
        ml.addWidget(self.question_cb); ml.addWidget(self.password_cb)
        self.method_group.setLayout(ml)
        layout.addWidget(self.method_group)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        self.setLayout(layout)

    def select_dest(self):
        d = QFileDialog.getExistingDirectory(self, "选择存储文件夹")
        if d:
            self.user_dest = d
            self.dest_label.setText(d)

    def toggle_advanced(self, checked):
        self.method_group.setEnabled(checked)

    def accept(self):
        self.is_advanced = self.advanced_cb.isChecked()
        self.delete_source = self.delete_source_cb.isChecked()
        if self.is_advanced:
            self.second_methods = []
            if self.totp_cb.isChecked(): self.second_methods.append('totp')
            if self.email_cb.isChecked(): self.second_methods.append('email')
            if self.question_cb.isChecked(): self.second_methods.append('question')
            if self.password_cb.isChecked(): self.second_methods.append('password')
            if not self.second_methods:
                QMessageBox.warning(self, "提示", "高级文件至少选择一种二次验证方式")
                return
        super().accept()
