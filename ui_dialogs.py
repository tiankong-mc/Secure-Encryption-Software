import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QComboBox, QStackedWidget, QDialogButtonBox,
                              QMessageBox, QWidget, QCheckBox, QGroupBox, QFileDialog)
from backup import BackupManager


class AuthDialog(QDialog):
    """二次验证（高级文件）"""
    def __init__(self, parent, auth_manager, allowed_methods, entry_id, storage):
        super().__init__(parent)
        self.auth = auth_manager
        self.allowed_methods = allowed_methods
        self.entry_id = entry_id
        self.storage = storage
        self.setWindowTitle("二次验证")
        self.setModal(True)
        self.resize(400, 300)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("请通过以下任意一种方式验证："))
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
            self.auth.reset_fail_count()
            self.storage.log(f"二次验证成功 (文件ID: {self.entry_id})")
            super().accept()
        else:
            count = self.auth.increment_fail_count()
            self.storage.log(f"二次验证失败 (文件ID: {self.entry_id})")
            QMessageBox.warning(self, "验证失败", f"失败 {count} 次")
            if count >= 5:
                self.storage.log(f"二次验证错误次数过多，已拒绝 (文件ID: {self.entry_id})")
                QMessageBox.critical(self, "验证失败", "错误次数过多，程序将退出。")
                super().reject()


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
        self.setWindowTitle("上传加密选项")
        self.setModal(True)
        self.resize(400, 300)
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
        self.method_group = QGroupBox("二次验证方式（高级文件时可用）")
        self.method_group.setEnabled(False)
        ml = QVBoxLayout()
        self.totp_cb = QCheckBox("TOTP (Authenticator)")
        self.email_cb = QCheckBox("邮箱验证码")
        self.question_cb = QCheckBox("安全问题")
        self.password_cb = QCheckBox("密码")
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
