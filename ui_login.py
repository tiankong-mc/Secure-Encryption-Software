import base64
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QComboBox, QStackedWidget, QDialogButtonBox,
                              QMessageBox, QWidget, QCheckBox, QInputDialog,
                              QWizard, QWizardPage)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap


class LoginDialog(QDialog):
    """主登录对话框（已移除5次自毁功能）"""
    def __init__(self, auth_manager, storage):
        super().__init__()
        self.auth = auth_manager
        self.storage = storage
        self.recovery_accepted = False
        self.setWindowTitle("SecureVault 登录")
        self.setModal(True)
        self.resize(400, 350)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("请通过以下任一方式验证身份"))
        self.stack = QStackedWidget()
        self.methods = []
        if self.auth.password_hash:
            w = self.create_password_widget(); self.stack.addWidget(w); self.methods.append('password')
        if self.auth.qa:
            w = self.create_question_widget(); self.stack.addWidget(w); self.methods.append('question')
        if self.auth.totp_secret:
            w = self.create_totp_widget(); self.stack.addWidget(w); self.methods.append('totp')
        if self.auth.email_config:
            w = self.create_email_widget(); self.stack.addWidget(w); self.methods.append('email')
        layout.addWidget(self.stack)
        self.method_combo = QComboBox()
        self.method_combo.addItems(self.methods)
        self.method_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        layout.addWidget(self.method_combo)
        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_box.accepted.connect(self.accept)
        self.btn_box.rejected.connect(self.reject)
        layout.addWidget(self.btn_box)
        self.recovery_btn = QPushButton("使用紧急恢复代码")
        self.recovery_btn.clicked.connect(self.recovery_login)
        layout.addWidget(self.recovery_btn)
        self.setLayout(layout)

    def recovery_login(self):
        code, ok = QInputDialog.getText(self, "紧急恢复", "请输入紧急恢复代码（格式：XXXX-XXXX-XXXX-XXXX-XXXX）:")
        if not ok or not code:
            return
        if self.auth.verify_recovery_code(code):
            self.recovery_accepted = True
            self.accept()
        else:
            QMessageBox.warning(self, "错误", "恢复代码无效或已使用")

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
            QMessageBox.information(self, "提示", "验证码已发送")
        else:
            QMessageBox.warning(self, "错误", "发送失败")

    def accept(self):
        if self.recovery_accepted:
            self.storage.log("登录成功 (恢复代码)")
            super().accept()
            return
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
            self.storage.log("登录成功")
            super().accept()
        else:
            count = self.auth.increment_fail_count()
            self.storage.log(f"登录失败 (尝试 {count})")
            QMessageBox.warning(self, "验证失败", f"失败 {count} 次")
            if count >= 5:
                self.storage.log("登录错误次数过多，程序退出")
                QMessageBox.critical(self, "验证失败", "错误次数过多，程序将退出。")
                super().reject()


class SetupWizard(QWizard):
    """首次运行设置向导"""
    def __init__(self, auth_manager):
        super().__init__()
        self.auth = auth_manager
        self.setWindowTitle("SecureVault 首次设置")
        self.setWizardStyle(QWizard.ModernStyle)
        self._build_pages()

    def _build_pages(self):
        p1 = QWizardPage(); p1.setTitle("欢迎"); p1.setSubTitle("配置安全设置以保护您的文件")
        l = QVBoxLayout(); l.addWidget(QLabel("请依次设置以下安全选项，至少需要配置一种验证方式。")); p1.setLayout(l); self.addPage(p1)
        p2 = QWizardPage(); p2.setTitle("密码验证"); p2.setSubTitle("（可选）设置登录密码")
        l = QVBoxLayout()
        self.pw_enable = QCheckBox("启用密码验证"); l.addWidget(self.pw_enable)
        self.pw_input = QLineEdit(); self.pw_input.setEchoMode(QLineEdit.Password)
        self.pw_input.setPlaceholderText("输入密码（至少8位）"); l.addWidget(self.pw_input)
        self.pw_confirm = QLineEdit(); self.pw_confirm.setEchoMode(QLineEdit.Password)
        self.pw_confirm.setPlaceholderText("确认密码"); l.addWidget(self.pw_confirm)
        p2.setLayout(l); self.addPage(p2)
        p3 = QWizardPage(); p3.setTitle("安全问题"); p3.setSubTitle("设置三个安全问题和答案")
        l = QVBoxLayout()
        self.q1 = QLineEdit(); self.q1.setPlaceholderText("问题1")
        self.a1 = QLineEdit(); self.a1.setEchoMode(QLineEdit.Password); self.a1.setPlaceholderText("答案1")
        self.q2 = QLineEdit(); self.q2.setPlaceholderText("问题2")
        self.a2 = QLineEdit(); self.a2.setEchoMode(QLineEdit.Password); self.a2.setPlaceholderText("答案2")
        self.q3 = QLineEdit(); self.q3.setPlaceholderText("问题3")
        self.a3 = QLineEdit(); self.a3.setEchoMode(QLineEdit.Password); self.a3.setPlaceholderText("答案3")
        l.addWidget(QLabel("问题1")); l.addWidget(self.q1); l.addWidget(self.a1)
        l.addWidget(QLabel("问题2")); l.addWidget(self.q2); l.addWidget(self.a2)
        l.addWidget(QLabel("问题3")); l.addWidget(self.q3); l.addWidget(self.a3)
        p3.setLayout(l); self.addPage(p3)
        p4 = QWizardPage(); p4.setTitle("TOTP 验证"); p4.setSubTitle("使用 Microsoft Authenticator 等应用扫描二维码")
        l = QVBoxLayout()
        self.totp_enable = QCheckBox("启用 TOTP"); l.addWidget(self.totp_enable)
        self.qr_label = QLabel(); self.qr_label.setAlignment(Qt.AlignCenter); l.addWidget(self.qr_label)
        self.totp_code = QLineEdit(); self.totp_code.setPlaceholderText("输入当前动态码以验证"); l.addWidget(self.totp_code)
        self.totp_secret_label = QLabel(); l.addWidget(self.totp_secret_label)
        p4.setLayout(l); self.totp_secret = None; self.totp_setup_done = False; self.addPage(p4)
        p5 = QWizardPage(); p5.setTitle("邮箱验证"); p5.setSubTitle("配置SMTP发送验证码")
        l = QVBoxLayout()
        self.email_enable = QCheckBox("启用邮箱验证"); l.addWidget(self.email_enable)
        self.smtp_server = QLineEdit(); self.smtp_server.setPlaceholderText("SMTP服务器 (如 smtp.qq.com)"); l.addWidget(self.smtp_server)
        self.smtp_port = QLineEdit(); self.smtp_port.setPlaceholderText("端口 (如 587)"); l.addWidget(self.smtp_port)
        self.sender_email = QLineEdit(); self.sender_email.setPlaceholderText("发件邮箱"); l.addWidget(self.sender_email)
        self.sender_password = QLineEdit(); self.sender_password.setEchoMode(QLineEdit.Password)
        self.sender_password.setPlaceholderText("授权码或密码"); l.addWidget(self.sender_password)
        self.receiver_email = QLineEdit(); self.receiver_email.setPlaceholderText("收件邮箱（用于接收验证码）"); l.addWidget(self.receiver_email)
        p5.setLayout(l); self.addPage(p5)
        p6 = QWizardPage(); p6.setTitle("完成"); p6.setSubTitle("设置已保存，点击完成启动程序")
        l = QVBoxLayout(); l.addWidget(QLabel("所有设置将加密存储，请牢记您的安全信息。")); p6.setLayout(l); self.addPage(p6)

    def initializePage(self, id):
        if id == 3:
            if not self.totp_setup_done:
                self.totp_secret = self.auth.setup_totp()
                qr_data = self.auth.setup_totp()
                pixmap = QPixmap(); pixmap.loadFromData(qr_data)
                self.qr_label.setPixmap(pixmap.scaled(200, 200, Qt.KeepAspectRatio))
                self.totp_secret_label.setText(f"密钥：{self.auth.totp_secret}")
                self.totp_setup_done = True

    def accept(self):
        if self.pw_enable.isChecked():
            pw = self.pw_input.text()
            if len(pw) < 8:
                QMessageBox.warning(self, "错误", "密码长度至少8位"); return
            if pw != self.pw_confirm.text():
                QMessageBox.warning(self, "错误", "两次密码输入不一致"); return
            self.auth.set_password(pw)
        qa_list = []
        for q, a in [(self.q1.text(), self.a1.text()), (self.q2.text(), self.a2.text()), (self.q3.text(), self.a3.text())]:
            if not q or not a:
                QMessageBox.warning(self, "错误", "请完整填写所有安全问题和答案"); return
            qa_list.append((q, a))
        self.auth.set_questions(qa_list)
        if self.totp_enable.isChecked():
            code = self.totp_code.text()
            if not self.auth.verify_totp(code):
                QMessageBox.warning(self, "错误", "TOTP验证码不正确，请重新输入"); return
        else:
            self.auth.settings_dict.pop('totp_secret', None)
        if self.email_enable.isChecked():
            server = self.smtp_server.text()
            try:
                port = int(self.smtp_port.text())
            except:
                QMessageBox.warning(self, "错误", "端口必须为数字"); return
            sender = self.sender_email.text()
            pw = self.sender_password.text()
            receiver = self.receiver_email.text()
            if not all([server, port, sender, pw, receiver]):
                QMessageBox.warning(self, "错误", "请完整填写邮箱配置"); return
            self.auth.set_email_config(server, port, sender, pw, receiver)
            code = self.auth.send_verification_code(receiver)
            if not code:
                QMessageBox.warning(self, "错误", "邮箱配置测试失败，请检查设置"); return
            verify_code, ok = QInputDialog.getText(self, "验证邮箱", f"输入发送到 {receiver} 的验证码")
            if not ok or verify_code != code:
                QMessageBox.warning(self, "错误", "验证码错误"); return
        else:
            self.auth.email_config = {}
        self.auth.settings_dict['initialized'] = True
        self.auth._save()
        super().accept()
