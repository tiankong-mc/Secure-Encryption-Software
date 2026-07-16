import sys
import os
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QLabel, QTextEdit, QLineEdit, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QMessageBox, QFileDialog, QInputDialog, QWizard, QWizardPage, QGroupBox
from PyQt5.QtCore import Qt
from io import BytesIO
from PIL import Image, ImageQt
from backup import BackupManager

# ---------- 内置文件查看器（修正图片显示） ----------
class FileViewer(QDialog):
    def __init__(self, parent, data, ftype, original_name):
        super().__init__(parent)
        self.setWindowTitle(f"查看: {original_name}")
        self.setModal(True)
        self.resize(600, 500)
        layout = QVBoxLayout()
        if ftype == 'text':
            text_edit = QTextEdit()
            text_edit.setPlainText(data.decode('utf-8', errors='replace'))
            text_edit.setReadOnly(True)
            layout.addWidget(text_edit)
        elif ftype == 'image':
            # 方法1：使用 QPixmap 直接加载数据（推荐）
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                label = QLabel()
                label.setPixmap(pixmap.scaled(500, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                layout.addWidget(label)
            else:
                # 方法2：如果 QPixmap 失败，尝试使用 PIL
                try:
                    img = Image.open(BytesIO(data))
                    qimg = ImageQt.ImageQt(img)
                    pixmap = QPixmap.fromImage(qimg)
                    label = QLabel()
                    label.setPixmap(pixmap.scaled(500, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    layout.addWidget(label)
                except Exception as e:
                    layout.addWidget(QLabel("无法显示该图片（格式不支持或数据损坏）"))
        else:
            layout.addWidget(QLabel("不支持预览此文件类型，仅加密存储。"))
        self.setLayout(layout)

# ---------- 二次验证对话框（失败5次发送当前文件的 .vault） ----------
class AuthDialog(QDialog):
    def __init__(self, parent, auth_manager, allowed_methods, entry_id):
        super().__init__(parent)
        self.auth = auth_manager
        self.allowed_methods = allowed_methods
        self.entry_id = entry_id
        self.result = False
        self.setWindowTitle("二次验证")
        self.setModal(True)
        self.resize(400, 300)
        layout = QVBoxLayout()
        self.label = QLabel("请通过以下任意一种方式验证：")
        layout.addWidget(self.label)
        self.stack = QStackedWidget()
        self.widgets = {}
        if 'password' in allowed_methods:
            w = self.create_password_widget()
            self.stack.addWidget(w)
            self.widgets['password'] = w
        if 'question' in allowed_methods:
            w = self.create_question_widget()
            self.stack.addWidget(w)
            self.widgets['question'] = w
        if 'totp' in allowed_methods:
            w = self.create_totp_widget()
            self.stack.addWidget(w)
            self.widgets['totp'] = w
        if 'email' in allowed_methods:
            w = self.create_email_widget()
            self.stack.addWidget(w)
            self.widgets['email'] = w
        if 'windows_hello' in allowed_methods:
            w = self.create_hello_widget()
            self.stack.addWidget(w)
            self.widgets['windows_hello'] = w
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
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("输入密码："))
        self.pw_input = QLineEdit()
        self.pw_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.pw_input)
        w.setLayout(layout)
        return w

    def create_question_widget(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("选择安全问题："))
        self.question_combo = QComboBox()
        self.question_combo.addItems(self.auth.get_questions())
        layout.addWidget(self.question_combo)
        layout.addWidget(QLabel("输入答案："))
        self.answer_input = QLineEdit()
        self.answer_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.answer_input)
        w.setLayout(layout)
        return w

    def create_totp_widget(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("输入 Authenticator 动态码："))
        self.totp_input = QLineEdit()
        layout.addWidget(self.totp_input)
        w.setLayout(layout)
        return w

    def create_email_widget(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("输入邮箱验证码："))
        self.email_code_input = QLineEdit()
        layout.addWidget(self.email_code_input)
        self.send_btn = QPushButton("发送验证码")
        self.send_btn.clicked.connect(self.send_email_code)
        layout.addWidget(self.send_btn)
        self.email_code = None
        w.setLayout(layout)
        return w

    def send_email_code(self):
        self.email_code = self.auth.send_verification_code()
        if self.email_code:
            QMessageBox.information(self, "提示", "验证码已发送至您的邮箱")
        else:
            QMessageBox.warning(self, "错误", "邮件发送失败，请检查配置")

    def create_hello_widget(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("点击下方按钮进行 Windows Hello 验证："))
        self.hello_btn = QPushButton("开始验证")
        self.hello_btn.clicked.connect(self.do_hello)
        layout.addWidget(self.hello_btn)
        self.hello_result = False
        w.setLayout(layout)
        return w

    def do_hello(self):
        self.hello_result = self.auth.verify_windows_hello()
        if self.hello_result:
            QMessageBox.information(self, "成功", "验证通过")
        else:
            QMessageBox.warning(self, "失败", "验证未通过")

    def accept(self):
        method = self.method_combo.currentText()
        ok = False
        if method == 'password':
            pw = self.pw_input.text()
            ok = self.auth.verify_password(pw)
        elif method == 'question':
            q = self.question_combo.currentText()
            ans = self.answer_input.text()
            ok = self.auth.verify_question(q, ans)
        elif method == 'totp':
            code = self.totp_input.text()
            ok = self.auth.verify_totp(code)
        elif method == 'email':
            code = self.email_code_input.text()
            ok = (code == self.email_code)
        elif method == 'windows_hello':
            ok = self.hello_result
        if ok:
            self.auth.reset_fail_count()
            super().accept()
        else:
            count = self.auth.increment_fail_count()
            QMessageBox.warning(self, "验证失败", f"失败 {count} 次")
            if count >= 5:
                self.trigger_emergency_backup()
                super().reject()
            else:
                pass

    def trigger_emergency_backup(self):
        """发送当前文件的 .vault 加密文件到邮箱（使用原始文件名），然后销毁原文件"""
        from PyQt5.QtWidgets import QApplication
        main_window = None
        for widget in QApplication.topLevelWidgets():
            if widget.__class__.__name__ == 'MainWindow':
                main_window = widget
                break
        if main_window is None:
            QMessageBox.critical(self, "错误", "无法找到主窗口，备份失败")
            return
        storage = main_window.storage
        auth = main_window.auth
        smtp_config = auth.email_config
        if not smtp_config:
            QMessageBox.critical(self, "错误", "未配置邮箱，无法发送备份")
            return
        to_email = smtp_config.get('receiver_email')
        if not to_email:
            QMessageBox.critical(self, "错误", "未设置收件邮箱")
            return
        # 找到该文件条目
        entry = storage.get_entry_by_id(self.entry_id)
        if entry is None:
            QMessageBox.critical(self, "错误", "未找到该文件记录")
            return
        vault_path = entry['secret_path']
        if not os.path.exists(vault_path) and entry['user_path'] and os.path.exists(entry['user_path']):
            vault_path = entry['user_path']
        if not os.path.exists(vault_path):
            QMessageBox.critical(self, "错误", "加密文件不存在")
            return
        # 显示名称为 original_name + '.vault'
        display_name = entry['original_name'] + '.vault'
        try:
            BackupManager.send_vault_file(vault_path, to_email, smtp_config, display_name)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"邮件发送失败: {e}")
            return
        # 销毁原始文件
        storage.remove_entry(self.entry_id, destroy=True)
        auth.reset_fail_count()
        QMessageBox.critical(self, "紧急备份", f"加密文件已发送至您的邮箱，原始文件已被销毁。程序将退出。")
        QApplication.quit()

# ---------- 删除文件/操作验证对话框（验证失败不累计错误） ----------
class DeleteAuthDialog(QDialog):
    def __init__(self, parent, auth_manager, allowed_methods):
        super().__init__(parent)
        self.auth = auth_manager
        self.allowed_methods = allowed_methods
        self.setWindowTitle("身份验证")
        self.setModal(True)
        self.resize(400, 300)
        layout = QVBoxLayout()
        self.label = QLabel("请验证身份以继续操作：")
        layout.addWidget(self.label)
        self.stack = QStackedWidget()
        self.widgets = {}
        if 'password' in allowed_methods:
            w = self.create_password_widget()
            self.stack.addWidget(w)
            self.widgets['password'] = w
        if 'question' in allowed_methods:
            w = self.create_question_widget()
            self.stack.addWidget(w)
            self.widgets['question'] = w
        if 'totp' in allowed_methods:
            w = self.create_totp_widget()
            self.stack.addWidget(w)
            self.widgets['totp'] = w
        if 'email' in allowed_methods:
            w = self.create_email_widget()
            self.stack.addWidget(w)
            self.widgets['email'] = w
        if 'windows_hello' in allowed_methods:
            w = self.create_hello_widget()
            self.stack.addWidget(w)
            self.widgets['windows_hello'] = w
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
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("输入密码："))
        self.pw_input = QLineEdit()
        self.pw_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.pw_input)
        w.setLayout(layout)
        return w

    def create_question_widget(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("选择安全问题："))
        self.question_combo = QComboBox()
        self.question_combo.addItems(self.auth.get_questions())
        layout.addWidget(self.question_combo)
        layout.addWidget(QLabel("输入答案："))
        self.answer_input = QLineEdit()
        self.answer_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.answer_input)
        w.setLayout(layout)
        return w

    def create_totp_widget(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("输入 Authenticator 动态码："))
        self.totp_input = QLineEdit()
        layout.addWidget(self.totp_input)
        w.setLayout(layout)
        return w

    def create_email_widget(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("输入邮箱验证码："))
        self.email_code_input = QLineEdit()
        layout.addWidget(self.email_code_input)
        self.send_btn = QPushButton("发送验证码")
        self.send_btn.clicked.connect(self.send_email_code)
        layout.addWidget(self.send_btn)
        self.email_code = None
        w.setLayout(layout)
        return w

    def send_email_code(self):
        self.email_code = self.auth.send_verification_code()
        if self.email_code:
            QMessageBox.information(self, "提示", "验证码已发送至您的邮箱")
        else:
            QMessageBox.warning(self, "错误", "邮件发送失败，请检查配置")

    def create_hello_widget(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("点击按钮进行 Windows Hello 验证："))
        self.hello_btn = QPushButton("开始验证")
        self.hello_btn.clicked.connect(self.do_hello)
        layout.addWidget(self.hello_btn)
        self.hello_result = False
        w.setLayout(layout)
        return w

    def do_hello(self):
        self.hello_result = self.auth.verify_windows_hello()
        if self.hello_result:
            QMessageBox.information(self, "成功", "验证通过")
        else:
            QMessageBox.warning(self, "失败", "验证未通过")

    def accept(self):
        method = self.method_combo.currentText()
        ok = False
        if method == 'password':
            pw = self.pw_input.text()
            ok = self.auth.verify_password(pw)
        elif method == 'question':
            q = self.question_combo.currentText()
            ans = self.answer_input.text()
            ok = self.auth.verify_question(q, ans)
        elif method == 'totp':
            code = self.totp_input.text()
            ok = self.auth.verify_totp(code)
        elif method == 'email':
            code = self.email_code_input.text()
            ok = (code == self.email_code)
        elif method == 'windows_hello':
            ok = self.hello_result
        if ok:
            super().accept()
        else:
            QMessageBox.warning(self, "验证失败", "身份验证未通过，请重试或取消")

# ---------- 上传文件对话框 ----------
class UploadDialog(QDialog):
    """上传文件时的选项"""
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
        # 用户存储位置
        self.dest_btn = QPushButton("选择用户存储位置（可选）")
        self.dest_btn.clicked.connect(self.select_dest)
        self.dest_label = QLabel("未选择")
        layout.addWidget(self.dest_btn)
        layout.addWidget(self.dest_label)
        # 高级文件
        self.advanced_cb = QCheckBox("标记为高级文件（需二次验证）")
        self.advanced_cb.toggled.connect(self.toggle_advanced)
        layout.addWidget(self.advanced_cb)
        # 二次验证方式（多选）
        self.method_group = QGroupBox("二次验证方式（高级文件时可用）")
        self.method_group.setEnabled(False)
        methods_layout = QVBoxLayout()
        self.totp_cb = QCheckBox("TOTP (Authenticator)")
        self.email_cb = QCheckBox("邮箱验证码")
        self.question_cb = QCheckBox("安全问题")
        self.password_cb = QCheckBox("密码")
        self.hello_cb = QCheckBox("Windows Hello")
        methods_layout.addWidget(self.totp_cb)
        methods_layout.addWidget(self.email_cb)
        methods_layout.addWidget(self.question_cb)
        methods_layout.addWidget(self.password_cb)
        methods_layout.addWidget(self.hello_cb)
        self.method_group.setLayout(methods_layout)
        layout.addWidget(self.method_group)
        # 按钮
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        self.setLayout(layout)

    def select_dest(self):
        dir_ = QFileDialog.getExistingDirectory(self, "选择存储文件夹")
        if dir_:
            self.user_dest = dir_
            self.dest_label.setText(dir_)

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
            if self.hello_cb.isChecked(): self.second_methods.append('windows_hello')
            if not self.second_methods:
                QMessageBox.warning(self, "提示", "高级文件至少选择一种二次验证方式")
                return
        super().accept()

# ---------- 首次运行设置向导 ----------
class SetupWizard(QWizard):
    """首次运行设置向导"""
    def __init__(self, auth_manager):
        super().__init__()
        self.auth = auth_manager
        self.setWindowTitle("SecureVault 首次设置")
        self.setWizardStyle(QWizard.ModernStyle)
        # 页面1：欢迎
        page1 = QWizardPage()
        page1.setTitle("欢迎")
        page1.setSubTitle("配置安全设置以保护您的文件")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("请依次设置以下安全选项，至少需要配置一种验证方式。"))
        page1.setLayout(layout)
        self.addPage(page1)
        # 页面2：密码（可选）
        page2 = QWizardPage()
        page2.setTitle("密码验证")
        page2.setSubTitle("（可选）设置登录密码")
        layout = QVBoxLayout()
        self.pw_enable = QCheckBox("启用密码验证")
        layout.addWidget(self.pw_enable)
        self.pw_input = QLineEdit()
        self.pw_input.setEchoMode(QLineEdit.Password)
        self.pw_input.setPlaceholderText("输入密码（至少8位）")
        layout.addWidget(self.pw_input)
        self.pw_confirm = QLineEdit()
        self.pw_confirm.setEchoMode(QLineEdit.Password)
        self.pw_confirm.setPlaceholderText("确认密码")
        layout.addWidget(self.pw_confirm)
        page2.setLayout(layout)
        self.addPage(page2)
        # 页面3：安全问题
        page3 = QWizardPage()
        page3.setTitle("安全问题")
        page3.setSubTitle("设置三个安全问题和答案")
        layout = QVBoxLayout()
        self.q1 = QLineEdit(); self.q1.setPlaceholderText("问题1")
        self.a1 = QLineEdit(); self.a1.setEchoMode(QLineEdit.Password); self.a1.setPlaceholderText("答案1")
        self.q2 = QLineEdit(); self.q2.setPlaceholderText("问题2")
        self.a2 = QLineEdit(); self.a2.setEchoMode(QLineEdit.Password); self.a2.setPlaceholderText("答案2")
        self.q3 = QLineEdit(); self.q3.setPlaceholderText("问题3")
        self.a3 = QLineEdit(); self.a3.setEchoMode(QLineEdit.Password); self.a3.setPlaceholderText("答案3")
        layout.addWidget(QLabel("问题1"))
        layout.addWidget(self.q1)
        layout.addWidget(self.a1)
        layout.addWidget(QLabel("问题2"))
        layout.addWidget(self.q2)
        layout.addWidget(self.a2)
        layout.addWidget(QLabel("问题3"))
        layout.addWidget(self.q3)
        layout.addWidget(self.a3)
        page3.setLayout(layout)
        self.addPage(page3)
        # 页面4：TOTP
        page4 = QWizardPage()
        page4.setTitle("TOTP 验证")
        page4.setSubTitle("使用 Microsoft Authenticator 等应用扫描二维码")
        layout = QVBoxLayout()
        self.totp_enable = QCheckBox("启用 TOTP")
        layout.addWidget(self.totp_enable)
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.qr_label)
        self.totp_code = QLineEdit()
        self.totp_code.setPlaceholderText("输入当前动态码以验证")
        layout.addWidget(self.totp_code)
        self.totp_secret_label = QLabel()
        layout.addWidget(self.totp_secret_label)
        page4.setLayout(layout)
        self.totp_secret = None
        self.totp_setup_done = False
        self.addPage(page4)
        # 页面5：邮箱
        page5 = QWizardPage()
        page5.setTitle("邮箱验证")
        page5.setSubTitle("配置SMTP发送验证码")
        layout = QVBoxLayout()
        self.email_enable = QCheckBox("启用邮箱验证")
        layout.addWidget(self.email_enable)
        self.smtp_server = QLineEdit(); self.smtp_server.setPlaceholderText("SMTP服务器 (如 smtp.qq.com)")
        self.smtp_port = QLineEdit(); self.smtp_port.setPlaceholderText("端口 (如 587)")
        self.sender_email = QLineEdit(); self.sender_email.setPlaceholderText("发件邮箱")
        self.sender_password = QLineEdit(); self.sender_password.setEchoMode(QLineEdit.Password); self.sender_password.setPlaceholderText("授权码或密码")
        self.receiver_email = QLineEdit(); self.receiver_email.setPlaceholderText("收件邮箱（用于接收验证码）")
        layout.addWidget(self.smtp_server)
        layout.addWidget(self.smtp_port)
        layout.addWidget(self.sender_email)
        layout.addWidget(self.sender_password)
        layout.addWidget(self.receiver_email)
        page5.setLayout(layout)
        self.addPage(page5)
        # 页面6：Windows Hello
        page6 = QWizardPage()
        page6.setTitle("Windows Hello")
        page6.setSubTitle("使用人脸、指纹或PIN验证")
        layout = QVBoxLayout()
        self.hello_enable = QCheckBox("启用 Windows Hello")
        layout.addWidget(self.hello_enable)
        self.hello_test_btn = QPushButton("测试 Windows Hello")
        self.hello_test_btn.clicked.connect(self.test_hello)
        layout.addWidget(self.hello_test_btn)
        self.hello_status = QLabel("未测试")
        layout.addWidget(self.hello_status)
        page6.setLayout(layout)
        self.addPage(page6)
        # 页面7：完成
        page7 = QWizardPage()
        page7.setTitle("完成")
        page7.setSubTitle("设置已保存，点击完成启动程序")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("所有设置将加密存储，请牢记您的安全信息。"))
        page7.setLayout(layout)
        self.addPage(page7)

    def test_hello(self):
        if self.auth.verify_windows_hello():
            self.hello_status.setText("✓ 验证通过")
        else:
            self.hello_status.setText("✗ 验证失败或不可用")

    def initializePage(self, id):
        if id == 3:  # TOTP页面
            if not self.totp_setup_done:
                self.totp_secret = self.auth.setup_totp()
                qr_data = self.auth.setup_totp()
                pixmap = QPixmap()
                pixmap.loadFromData(qr_data)
                self.qr_label.setPixmap(pixmap.scaled(200, 200, Qt.KeepAspectRatio))
                self.totp_secret_label.setText(f"密钥：{self.auth.totp_secret}")
                self.totp_setup_done = True

    def accept(self):
        # 密码
        if self.pw_enable.isChecked():
            pw = self.pw_input.text()
            if len(pw) < 8:
                QMessageBox.warning(self, "错误", "密码长度至少8位")
                return
            if pw != self.pw_confirm.text():
                QMessageBox.warning(self, "错误", "两次密码输入不一致")
                return
            self.auth.set_password(pw)
        # 安全问题（必填）
        qa_list = []
        for q, a in [(self.q1.text(), self.a1.text()), (self.q2.text(), self.a2.text()), (self.q3.text(), self.a3.text())]:
            if not q or not a:
                QMessageBox.warning(self, "错误", "请完整填写所有安全问题和答案")
                return
            qa_list.append((q, a))
        self.auth.set_questions(qa_list)
        # TOTP
        if self.totp_enable.isChecked():
            code = self.totp_code.text()
            if not self.auth.verify_totp(code):
                QMessageBox.warning(self, "错误", "TOTP验证码不正确，请重新输入")
                return
        else:
            self.auth.settings_dict.pop('totp_secret', None)
        # 邮箱
        if self.email_enable.isChecked():
            server = self.smtp_server.text()
            port = int(self.smtp_port.text())
            sender = self.sender_email.text()
            pw = self.sender_password.text()
            receiver = self.receiver_email.text()
            if not all([server, port, sender, pw, receiver]):
                QMessageBox.warning(self, "错误", "请完整填写邮箱配置")
                return
            self.auth.set_email_config(server, port, sender, pw, receiver)
            code = self.auth.send_verification_code(receiver)
            if not code:
                QMessageBox.warning(self, "错误", "邮箱配置测试失败，请检查设置")
                return
            verify_code, ok = QInputDialog.getText(self, "验证邮箱", f"输入发送到 {receiver} 的验证码")
            if not ok or verify_code != code:
                QMessageBox.warning(self, "错误", "验证码错误")
                return
        else:
            self.auth.email_config = {}
        # Windows Hello
        if self.hello_enable.isChecked():
            if not self.auth.enable_windows_hello(True):
                QMessageBox.warning(self, "错误", "Windows Hello 不可用")
                return
        else:
            self.auth.enable_windows_hello(False)
        self.auth.settings_dict['initialized'] = True
        self.auth._save()
        super().accept()

# ---------- 登录对话框（失败5次发送所有 .vault 文件） ----------
class LoginDialog(QDialog):
    def __init__(self, auth_manager):
        super().__init__()
        self.auth = auth_manager
        self.setWindowTitle("SecureVault 登录")
        self.setModal(True)
        self.resize(400, 300)
        layout = QVBoxLayout()
        self.label = QLabel("请通过以下任一方式验证身份")
        layout.addWidget(self.label)
        self.stack = QStackedWidget()
        self.methods = []
        if self.auth.password_hash:
            w = self.create_password_widget()
            self.stack.addWidget(w)
            self.methods.append('password')
        if self.auth.qa:
            w = self.create_question_widget()
            self.stack.addWidget(w)
            self.methods.append('question')
        if self.auth.totp_secret:
            w = self.create_totp_widget()
            self.stack.addWidget(w)
            self.methods.append('totp')
        if self.auth.email_config:
            w = self.create_email_widget()
            self.stack.addWidget(w)
            self.methods.append('email')
        if self.auth.windows_hello_enabled:
            w = self.create_hello_widget()
            self.stack.addWidget(w)
            self.methods.append('windows_hello')
        layout.addWidget(self.stack)
        self.method_combo = QComboBox()
        self.method_combo.addItems(self.methods)
        self.method_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        layout.addWidget(self.method_combo)
        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_box.accepted.connect(self.accept)
        self.btn_box.rejected.connect(self.reject)
        layout.addWidget(self.btn_box)
        self.setLayout(layout)

    def create_password_widget(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("输入密码："))
        self.pw_input = QLineEdit()
        self.pw_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.pw_input)
        w.setLayout(layout)
        return w

    def create_question_widget(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("选择安全问题："))
        self.question_combo = QComboBox()
        self.question_combo.addItems(self.auth.get_questions())
        layout.addWidget(self.question_combo)
        layout.addWidget(QLabel("输入答案："))
        self.answer_input = QLineEdit()
        self.answer_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.answer_input)
        w.setLayout(layout)
        return w

    def create_totp_widget(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("输入 Authenticator 动态码："))
        self.totp_input = QLineEdit()
        layout.addWidget(self.totp_input)
        w.setLayout(layout)
        return w

    def create_email_widget(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("输入邮箱验证码："))
        self.email_code_input = QLineEdit()
        layout.addWidget(self.email_code_input)
        self.send_btn = QPushButton("发送验证码")
        self.send_btn.clicked.connect(self.send_email_code)
        layout.addWidget(self.send_btn)
        self.email_code = None
        w.setLayout(layout)
        return w

    def send_email_code(self):
        self.email_code = self.auth.send_verification_code()
        if self.email_code:
            QMessageBox.information(self, "提示", "验证码已发送")
        else:
            QMessageBox.warning(self, "错误", "发送失败")

    def create_hello_widget(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("点击按钮进行 Windows Hello 验证："))
        self.hello_btn = QPushButton("开始验证")
        self.hello_btn.clicked.connect(self.do_hello)
        layout.addWidget(self.hello_btn)
        self.hello_result = False
        w.setLayout(layout)
        return w

    def do_hello(self):
        self.hello_result = self.auth.verify_windows_hello()
        if self.hello_result:
            QMessageBox.information(self, "成功", "验证通过")
        else:
            QMessageBox.warning(self, "失败", "验证未通过")

    def accept(self):
        method = self.method_combo.currentText()
        ok = False
        if method == 'password':
            ok = self.auth.verify_password(self.pw_input.text())
        elif method == 'question':
            q = self.question_combo.currentText()
            ans = self.answer_input.text()
            ok = self.auth.verify_question(q, ans)
        elif method == 'totp':
            ok = self.auth.verify_totp(self.totp_input.text())
        elif method == 'email':
            ok = (self.email_code_input.text() == self.email_code)
        elif method == 'windows_hello':
            ok = self.hello_result
        if ok:
            self.auth.reset_fail_count()
            super().accept()
        else:
            count = self.auth.increment_fail_count()
            QMessageBox.warning(self, "验证失败", f"失败 {count} 次")
            if count >= 5:
                self.trigger_emergency_backup()
                super().reject()
            else:
                pass

    def trigger_emergency_backup(self):
        """发送所有 .vault 文件到邮箱（使用原始文件名），然后销毁所有原文件"""
        from PyQt5.QtWidgets import QApplication
        main_window = None
        for widget in QApplication.topLevelWidgets():
            if widget.__class__.__name__ == 'MainWindow':
                main_window = widget
                break
        if main_window is None:
            QMessageBox.critical(self, "错误", "无法找到主窗口，备份失败")
            return
        storage = main_window.storage
        auth = main_window.auth
        smtp_config = auth.email_config
        if not smtp_config:
            QMessageBox.critical(self, "错误", "未配置邮箱，无法发送备份")
            return
        to_email = smtp_config.get('receiver_email')
        if not to_email:
            QMessageBox.critical(self, "错误", "未设置收件邮箱")
            return
        # 获取所有文件路径和显示名
        file_info_list = storage.get_all_vault_paths_with_names()
        if not file_info_list:
            QMessageBox.critical(self, "错误", "没有可备份的文件")
            return
        # 发送所有文件
        try:
            BackupManager.send_multiple_vault_files(file_info_list, to_email, smtp_config)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"邮件发送失败: {e}")
            return
        # 销毁所有原始文件
        for entry in storage.get_all_entries():
            storage.remove_entry(entry['id'], destroy=True)
        storage.index = []
        storage._save_index()
        auth.reset_fail_count()
        QMessageBox.critical(self, "紧急备份", "所有加密文件已发送至您的邮箱，原始文件已被销毁。程序将退出。")
        QApplication.quit()

# ---------- 主窗口 ----------
class MainWindow(QMainWindow):
    def __init__(self, storage, auth):
        super().__init__()
        self.storage = storage
        self.auth = auth
        self.setWindowTitle("SecureVault")
        self.setGeometry(100, 100, 800, 600)
        self.initUI()
        self.load_files()
        self.auto_backup_enabled = self.auth.settings_dict.get('auto_backup', True)
        self.send_email_on_backup = self.auth.settings_dict.get('send_email_on_backup', False)

    def initUI(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout()
        # 工具栏
        top_bar = QHBoxLayout()
        self.upload_btn = QPushButton("上传加密")
        self.import_btn = QPushButton("导入加密文件")
        self.export_btn = QPushButton("导出解密文件")
        self.refresh_btn = QPushButton("刷新")
        self.settings_btn = QPushButton("设置")
        self.delete_btn = QPushButton("删除")
        top_bar.addWidget(self.upload_btn)
        top_bar.addWidget(self.import_btn)
        top_bar.addWidget(self.export_btn)
        top_bar.addWidget(self.refresh_btn)
        top_bar.addWidget(self.settings_btn)
        top_bar.addWidget(self.delete_btn)
        layout.addLayout(top_bar)
        # 文件列表
        self.file_list = QListWidget()
        self.file_list.itemDoubleClicked.connect(self.open_file)
        layout.addWidget(self.file_list)
        central.setLayout(layout)
        # 信号连接
        self.upload_btn.clicked.connect(self.upload_file)
        self.import_btn.clicked.connect(self.import_vault_file)
        self.export_btn.clicked.connect(self.export_decrypted_file)
        self.refresh_btn.clicked.connect(self.load_files)
        self.settings_btn.clicked.connect(self.open_settings)
        self.delete_btn.clicked.connect(self.delete_file)

    def load_files(self):
        self.file_list.clear()
        for entry in self.storage.get_all_entries():
            item_text = f"{entry['original_name']}  {'[高级]' if entry['is_advanced'] else ''}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, entry['id'])
            self.file_list.addItem(item)

    def upload_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择要加密的文件")
        if not file_path:
            return
        dialog = UploadDialog(self, file_path)
        if dialog.exec_():
            try:
                uid = self.storage.add_file(file_path, dialog.user_dest, dialog.is_advanced, dialog.second_methods)
                QMessageBox.information(self, "成功", f"文件已加密保存，ID: {uid}")
                self.load_files()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"加密失败: {e}")

    def import_vault_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择要导入的 .vault 加密文件", "", "Vault Files (*.vault)")
        if not file_path:
            return
        is_advanced = QMessageBox.question(self, "高级文件", "是否将此文件标记为高级文件（需二次验证）？", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes
        second_methods = []
        if is_advanced:
            dialog = QDialog(self)
            dialog.setWindowTitle("选择二次验证方式")
            layout = QVBoxLayout()
            cb_totp = QCheckBox("TOTP")
            cb_email = QCheckBox("邮箱验证码")
            cb_question = QCheckBox("安全问题")
            cb_password = QCheckBox("密码")
            cb_hello = QCheckBox("Windows Hello")
            layout.addWidget(cb_totp)
            layout.addWidget(cb_email)
            layout.addWidget(cb_question)
            layout.addWidget(cb_password)
            layout.addWidget(cb_hello)
            btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btn_box.accepted.connect(dialog.accept)
            btn_box.rejected.connect(dialog.reject)
            layout.addWidget(btn_box)
            dialog.setLayout(layout)
            if dialog.exec_() == QDialog.Accepted:
                if cb_totp.isChecked(): second_methods.append('totp')
                if cb_email.isChecked(): second_methods.append('email')
                if cb_question.isChecked(): second_methods.append('question')
                if cb_password.isChecked(): second_methods.append('password')
                if cb_hello.isChecked(): second_methods.append('windows_hello')
                if not second_methods:
                    QMessageBox.warning(self, "提示", "至少选择一种二次验证方式")
                    return
        try:
            uid = self.storage.import_vault_file(file_path, is_advanced=is_advanced, second_auth_methods=second_methods)
            QMessageBox.information(self, "成功", f"文件已导入，ID: {uid}")
            self.load_files()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败: {e}")

    def export_decrypted_file(self):
        current_item = self.file_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先选择一个文件")
            return
        entry_id = current_item.data(Qt.UserRole)
        entry = self.storage.get_entry_by_id(entry_id)
        if entry is None:
            QMessageBox.warning(self, "错误", "未找到该文件记录")
            return
        # 验证身份
        available_methods = self._get_available_auth_methods()
        if not available_methods:
            QMessageBox.warning(self, "提示", "没有可用的验证方式，请先设置安全选项。")
            return
        auth_dialog = DeleteAuthDialog(self, self.auth, available_methods)
        if auth_dialog.exec_() != QDialog.Accepted:
            return
        # 选择保存位置
        save_path, _ = QFileDialog.getSaveFileName(self, "导出解密文件", entry['original_name'], "All Files (*.*)")
        if not save_path:
            return
        try:
            data = self.storage.get_file_data(entry_id)
            with open(save_path, 'wb') as f:
                f.write(data)
            QMessageBox.information(self, "成功", f"文件已解密并导出到：{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {e}")

    def open_file(self, item):
        entry_id = item.data(Qt.UserRole)
        entry = self.storage.get_entry_by_id(entry_id)
        if not entry:
            return
        if entry['is_advanced']:
            methods = entry['second_auth_methods']
            if not methods:
                QMessageBox.warning(self, "提示", "该文件未设置二次验证方式，无法打开")
                return
            auth_dialog = AuthDialog(self, self.auth, methods, entry_id)
            if auth_dialog.exec_() != QDialog.Accepted:
                return
        try:
            data = self.storage.get_file_data(entry_id)
            viewer = FileViewer(self, data, entry['type'], entry['original_name'])
            viewer.exec_()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开文件失败: {e}")

    def open_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("设置")
        layout = QVBoxLayout()
        self.auto_backup_cb = QCheckBox("启用错误5次自动备份（默认开启）")
        self.auto_backup_cb.setChecked(self.auto_backup_enabled)
        layout.addWidget(self.auto_backup_cb)
        self.send_email_cb = QCheckBox("备份时发送邮件到指定邮箱")
        self.send_email_cb.setChecked(self.send_email_on_backup)
        layout.addWidget(self.send_email_cb)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)
        dialog.setLayout(layout)
        if dialog.exec_():
            self.auto_backup_enabled = self.auto_backup_cb.isChecked()
            self.send_email_on_backup = self.send_email_cb.isChecked()
            self.auth.settings_dict['auto_backup'] = self.auto_backup_enabled
            self.auth.settings_dict['send_email_on_backup'] = self.send_email_on_backup
            self.auth._save()

    def delete_file(self):
        current_item = self.file_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先选择一个文件")
            return
        entry_id = current_item.data(Qt.UserRole)
        available_methods = self._get_available_auth_methods()
        if not available_methods:
            QMessageBox.warning(self, "提示", "没有可用的验证方式，请先设置安全选项。")
            return
        auth_dialog = DeleteAuthDialog(self, self.auth, available_methods)
        if auth_dialog.exec_() != QDialog.Accepted:
            return
        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定要永久删除该加密文件吗？\n（文件将被永久删除，无法恢复）",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.storage.remove_entry(entry_id, destroy=False)
                self.load_files()
                QMessageBox.information(self, "成功", "文件已删除")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败: {e}")

    def _get_available_auth_methods(self):
        methods = []
        if self.auth.password_hash:
            methods.append('password')
        if self.auth.qa:
            methods.append('question')
        if self.auth.totp_secret:
            methods.append('totp')
        if self.auth.email_config:
            methods.append('email')
        if self.auth.windows_hello_enabled:
            methods.append('windows_hello')
        return methods
