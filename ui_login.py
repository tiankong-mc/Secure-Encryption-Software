from io import BytesIO
import os
import pyotp, qrcode
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QComboBox, QStackedWidget, QDialogButtonBox,
                              QMessageBox, QWidget, QCheckBox, QInputDialog,
                              QWizard, QWizardPage, QFileDialog)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap

from settings import DEFAULT_SECRET_DIR


# ============================================================
#  登录对话框
# ============================================================
class LoginDialog(QDialog):
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

        enabled = self.auth.get_enabled_methods()

        if 'password' in enabled:
            w = self.create_password_widget(); self.stack.addWidget(w); self.methods.append('password')
        if 'question' in enabled:
            w = self.create_question_widget(); self.stack.addWidget(w); self.methods.append('question')
        if 'totp' in enabled:
            w = self.create_totp_widget(); self.stack.addWidget(w); self.methods.append('totp')
        if 'email' in enabled:
            w = self.create_email_widget(); self.stack.addWidget(w); self.methods.append('email')

        if not self.methods:
            QMessageBox.critical(self, "错误", "没有已启用的验证方式，请检查设置。")

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
        if not ok or not code: return
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
        if self.email_code: QMessageBox.information(self, "提示", "验证码已发送")
        else: QMessageBox.warning(self, "错误", "发送失败")

    def accept(self):
        if self.recovery_accepted:
            self.storage.log("登录成功 (恢复代码)")
            super().accept()
            return
        if not self.methods:
            QMessageBox.critical(self, "错误", "没有可用的验证方式")
            return
        method = self.method_combo.currentText()
        ok = False
        if method == 'password':
            ok = self.auth.verify_password(self.pw_input.text())
        elif method == 'question':
            ok = self.auth.verify_question(self.question_combo.currentText(),
                                            self.answer_input.text())
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


# ============================================================
#  首次运行设置向导
# ============================================================
class SetupWizard(QWizard):
    def __init__(self, auth_manager, storage_manager=None):
        super().__init__()
        self.auth = auth_manager
        self.storage = storage_manager
        self.setWindowTitle("SecureVault 首次设置")
        self.setWizardStyle(QWizard.ModernStyle)
        # 是否已从备份成功恢复验证信息（决定是否跳过手动配置页）
        self._imported_auth = False
        self._build_pages()

    # 页面索引：
    # 0 = 路径
    # 1 = 欢迎
    # 2 = 导入保险库（新）
    # 3 = 密码
    # 4 = 安全问题
    # 5 = TOTP
    # 6 = 邮箱
    # 7 = 完成

    def _build_pages(self):
        # ---------- 页0：加密文件存储位置 ----------
        p0 = QWizardPage()
        p0.setTitle("加密文件存储位置")
        p0.setSubTitle("选择加密后 .vault 文件的保存位置（可保持默认）")
        l = QVBoxLayout()
        l.addWidget(QLabel("加密文件目录："))
        row = QHBoxLayout()
        self.secret_dir_input = QLineEdit(DEFAULT_SECRET_DIR)
        self.secret_dir_input.setReadOnly(True)
        row.addWidget(self.secret_dir_input)
        btn = QPushButton("浏览...")
        btn.setFixedWidth(80)
        btn.clicked.connect(self._choose_secret_dir)
        row.addWidget(btn)
        l.addLayout(row)

        l.addSpacing(20)
        tip = QLabel("提示：仅需设置一次，后续可在“设置 → 安全”中修改。\n"
                     "配置文件和密钥固定保存在系统默认位置，以保证安全。")
        tip.setStyleSheet("color: #888;")
        tip.setWordWrap(True)
        l.addWidget(tip)
        l.addStretch()
        p0.setLayout(l)
        self.addPage(p0)

        # ---------- 页1：欢迎 ----------
        p1 = QWizardPage()
        p1.setTitle("欢迎")
        p1.setSubTitle("配置安全设置以保护您的文件")
        l = QVBoxLayout()
        l.addWidget(QLabel("请依次设置以下安全选项，至少需要配置一种验证方式。"))
        p1.setLayout(l); self.addPage(p1)

        # ---------- 页2：导入保险库（可选） ----------
        p_import = QWizardPage()
        p_import.setTitle("导入保险库（可选）")
        p_import.setSubTitle("已有 SecureVault 备份可在此导入，并恢复验证信息")
        l = QVBoxLayout()

        self.import_enable = QCheckBox(
            "从备份文件导入（会恢复密码 / 安全问题 / TOTP / 邮箱等验证信息）")
        l.addWidget(self.import_enable)

        l.addSpacing(8)
        l.addWidget(QLabel("备份文件："))
        row = QHBoxLayout()
        self.import_path_input = QLineEdit()
        self.import_path_input.setReadOnly(True)
        self.import_path_input.setPlaceholderText("未选择文件")
        row.addWidget(self.import_path_input)
        self.import_browse_btn = QPushButton("浏览...")
        self.import_browse_btn.setFixedWidth(80)
        self.import_browse_btn.clicked.connect(self._choose_import_file)
        row.addWidget(self.import_browse_btn)
        l.addLayout(row)

        l.addWidget(QLabel("备份密码："))
        self.import_password_input = QLineEdit()
        self.import_password_input.setEchoMode(QLineEdit.Password)
        self.import_password_input.setPlaceholderText("输入备份文件密码")
        l.addWidget(self.import_password_input)

        self.import_status_label = QLabel("")
        self.import_status_label.setWordWrap(True)
        self.import_status_label.setStyleSheet("color: #888;")
        l.addWidget(self.import_status_label)

        l.addStretch()

        tip = QLabel("提示：导入成功后，将跳过后面的验证方式配置页，直接进入完成步骤。\n"
                     "如果不需要导入，请保持未勾选并点击“下一步”。")
        tip.setStyleSheet("color: #888;")
        tip.setWordWrap(True)
        l.addWidget(tip)

        p_import.setLayout(l)
        self.addPage(p_import)

        # ---------- 页3：密码 ----------
        p3_pwd = QWizardPage()
        p3_pwd.setTitle("密码验证")
        p3_pwd.setSubTitle("（可选）设置登录密码")
        l = QVBoxLayout()
        self.pw_enable = QCheckBox("启用密码验证")
        l.addWidget(self.pw_enable)
        self.pw_input = QLineEdit(); self.pw_input.setEchoMode(QLineEdit.Password)
        self.pw_input.setPlaceholderText("输入密码（6-8 位，支持大小写字母、数字、符号）")
        l.addWidget(self.pw_input)
        self.pw_confirm = QLineEdit(); self.pw_confirm.setEchoMode(QLineEdit.Password)
        self.pw_confirm.setPlaceholderText("确认密码")
        l.addWidget(self.pw_confirm)
        p3_pwd.setLayout(l); self.addPage(p3_pwd)

        # ---------- 页4：安全问题 ----------
        p4_qa = QWizardPage()
        p4_qa.setTitle("安全问题")
        p4_qa.setSubTitle("（可选）设置三个安全问题和答案")
        l = QVBoxLayout()
        self.qa_enable = QCheckBox("启用安全问题")
        self.qa_enable.setChecked(True)
        l.addWidget(self.qa_enable)
        self.q1 = QLineEdit(); self.q1.setPlaceholderText("问题1")
        self.a1 = QLineEdit(); self.a1.setEchoMode(QLineEdit.Password); self.a1.setPlaceholderText("答案1")
        self.q2 = QLineEdit(); self.q2.setPlaceholderText("问题2")
        self.a2 = QLineEdit(); self.a2.setEchoMode(QLineEdit.Password); self.a2.setPlaceholderText("答案2")
        self.q3 = QLineEdit(); self.q3.setPlaceholderText("问题3")
        self.a3 = QLineEdit(); self.a3.setEchoMode(QLineEdit.Password); self.a3.setPlaceholderText("答案3")
        l.addWidget(QLabel("问题1")); l.addWidget(self.q1); l.addWidget(self.a1)
        l.addWidget(QLabel("问题2")); l.addWidget(self.q2); l.addWidget(self.a2)
        l.addWidget(QLabel("问题3")); l.addWidget(self.q3); l.addWidget(self.a3)
        p4_qa.setLayout(l); self.addPage(p4_qa)

        # ---------- 页5：TOTP ----------
        p5_totp = QWizardPage()
        p5_totp.setTitle("TOTP 验证")
        p5_totp.setSubTitle("使用 Microsoft Authenticator 等应用扫描二维码")
        l = QVBoxLayout()
        self.totp_enable = QCheckBox("启用 TOTP")
        l.addWidget(self.totp_enable)
        self.qr_label = QLabel(); self.qr_label.setAlignment(Qt.AlignCenter)
        l.addWidget(self.qr_label)
        self.totp_code = QLineEdit(); self.totp_code.setPlaceholderText("输入当前动态码以验证")
        l.addWidget(self.totp_code)
        self.totp_secret_label = QLabel()
        l.addWidget(self.totp_secret_label)
        p5_totp.setLayout(l)
        self.totp_secret = None
        self.totp_setup_done = False
        self.addPage(p5_totp)

        # ---------- 页6：邮箱 ----------
        p6_email = QWizardPage()
        p6_email.setTitle("邮箱验证")
        p6_email.setSubTitle("配置SMTP发送验证码")
        l = QVBoxLayout()
        self.email_enable = QCheckBox("启用邮箱验证")
        l.addWidget(self.email_enable)
        self.smtp_server = QLineEdit(); self.smtp_server.setPlaceholderText("SMTP服务器 (如 smtp.qq.com)")
        l.addWidget(self.smtp_server)
        self.smtp_port = QLineEdit(); self.smtp_port.setPlaceholderText("端口 (如 587)")
        l.addWidget(self.smtp_port)
        self.sender_email = QLineEdit(); self.sender_email.setPlaceholderText("发件邮箱")
        l.addWidget(self.sender_email)
        self.sender_password = QLineEdit(); self.sender_password.setEchoMode(QLineEdit.Password)
        self.sender_password.setPlaceholderText("授权码或密码")
        l.addWidget(self.sender_password)
        self.receiver_email = QLineEdit(); self.receiver_email.setPlaceholderText("收件邮箱（用于接收验证码）")
        l.addWidget(self.receiver_email)
        p6_email.setLayout(l); self.addPage(p6_email)

        # ---------- 页7：完成 ----------
        p7_done = QWizardPage()
        p7_done.setTitle("完成")
        p7_done.setSubTitle("设置已保存，点击完成启动程序")
        l = QVBoxLayout()
        l.addWidget(QLabel("所有设置将加密存储，请牢记您的安全信息。"))
        p7_done.setLayout(l); self.addPage(p7_done)

    # ============================================================
    #  页面跳转控制
    # ============================================================
    def nextId(self):
        # 若在导入页成功恢复了验证信息，直接跳到完成页
        if self.currentId() == 2 and self._imported_auth:
            return 7
        return super().nextId()

    # ============================================================
    #  文件选择
    # ============================================================
    def _choose_secret_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择加密文件目录",
                                              self.secret_dir_input.text())
        if d:
            self.secret_dir_input.setText(d)

    def _choose_import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择备份文件", "",
            "SecureVault Backup (*.vaultbk);;All Files (*.*)")
        if path:
            self.import_path_input.setText(path)
            self.import_enable.setChecked(True)

    # ============================================================
    #  初始化页面
    # ============================================================
    def initializePage(self, id):
        if id == 5:  # TOTP 页
            if not self.totp_setup_done:
                self.totp_secret = self.auth.generate_totp_secret()
                totp = pyotp.TOTP(self.totp_secret)
                uri = totp.provisioning_uri(name="SecureVault", issuer_name="SecureApp")
                image = qrcode.make(uri)
                buffer = BytesIO()
                image.save(buffer, format='PNG')
                pixmap = QPixmap(); pixmap.loadFromData(buffer.getvalue())
                self.qr_label.setPixmap(pixmap.scaled(200, 200, Qt.KeepAspectRatio))
                self.totp_secret_label.setText(f"密钥：{self.totp_secret}")
                self.totp_setup_done = True

    # ============================================================
    #  每点一次"下一步"，验证当前页
    # ============================================================
    def validateCurrentPage(self):
        page_id = self.currentId()

        # 页0：路径
        if page_id == 0:
            new_dir = self.secret_dir_input.text().strip()
            if new_dir and os.path.normcase(os.path.abspath(new_dir)) != \
                    os.path.normcase(os.path.abspath(DEFAULT_SECRET_DIR)):
                try:
                    os.makedirs(new_dir, exist_ok=True)
                except Exception as e:
                    QMessageBox.warning(self, "错误", f"无法创建目录：{e}")
                    return False
            return True

        # 页1：欢迎
        if page_id == 1:
            return True

        # 页2：导入保险库
        if page_id == 2:
            if not self.import_enable.isChecked():
                return True
            if self._imported_auth:
                return True  # 已成功导入过，不重复执行
            return self._do_import()

        # 页3：密码
        if page_id == 3:
            if not self.pw_enable.isChecked():
                return True
            pw = self.pw_input.text()
            if not (6 <= len(pw) <= 8):
                QMessageBox.warning(self, "错误", "密码长度必须为 6-8 位")
                return False
            if pw != self.pw_confirm.text():
                QMessageBox.warning(self, "错误", "两次密码输入不一致")
                return False
            return True

        # 页4：安全问题
        if page_id == 4:
            if not self.qa_enable.isChecked():
                return True
            for i, (q, a) in enumerate(
                    [(self.q1, self.a1), (self.q2, self.a2), (self.q3, self.a3)], 1):
                if not q.text().strip() or not a.text().strip():
                    QMessageBox.warning(self, "错误", f"请完整填写问题 {i} 和答案")
                    return False
            return True

        # 页5：TOTP
        if page_id == 5:
            if not self.totp_enable.isChecked():
                return True
            if not self.totp_secret:
                QMessageBox.warning(self, "错误", "TOTP 密钥未生成，请返回上一页再进入")
                return False
            code = self.totp_code.text().strip()
            if not code:
                QMessageBox.warning(self, "错误", "请输入 Authenticator 中显示的当前动态码")
                self.totp_code.setFocus()
                return False
            if not self.auth.verify_totp_secret(self.totp_secret, code):
                QMessageBox.warning(
                    self, "验证失败",
                    "TOTP 动态码不正确，或已超过 30 秒有效期。\n"
                    "请打开 Authenticator 查看当前最新的 6 位数字，重新输入。")
                self.totp_code.clear()
                self.totp_code.setFocus()
                return False
            return True

        # 页6：邮箱
        if page_id == 6:
            if not self.email_enable.isChecked():
                return True
            server = self.smtp_server.text().strip()
            try:
                port = int(self.smtp_port.text().strip())
            except ValueError:
                QMessageBox.warning(self, "错误", "端口必须为数字")
                return False
            sender = self.sender_email.text().strip()
            email_password = self.sender_password.text()
            receiver = self.receiver_email.text().strip()
            if not all([server, sender, email_password, receiver]):
                QMessageBox.warning(self, "错误", "请完整填写邮箱配置")
                return False

            success, result = self.auth.test_email_config(
                server, port, sender, email_password, receiver)
            if not success:
                QMessageBox.warning(self, "错误", f"邮箱配置测试失败：{result}")
                return False

            verify_code, ok = QInputDialog.getText(
                self, "验证邮箱",
                f"验证码已发送到 {receiver}\n请输入收到的 6 位验证码：")
            if not ok:
                return False
            if verify_code.strip() != result:
                QMessageBox.warning(self, "错误", "验证码错误，请重试或重新发送")
                return False
            return True

        # 页7：完成
        if page_id == 7:
            if self._imported_auth:
                return True  # 已从备份恢复验证信息
            if not any((self.pw_enable.isChecked(), self.qa_enable.isChecked(),
                        self.totp_enable.isChecked(), self.email_enable.isChecked())):
                QMessageBox.warning(self, "错误", "至少需要配置一种验证方式")
                return False
            return True

        return True

    # ============================================================
    #  执行导入
    # ============================================================
    def _do_import(self):
        path = self.import_path_input.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "错误", "请选择有效的备份文件")
            return False
        if self.storage is None:
            QMessageBox.warning(self, "错误", "内部错误：未初始化存储管理器")
            return False
        password = self.import_password_input.text()
        if not password:
            QMessageBox.warning(self, "错误", "请输入备份密码")
            return False

        try:
            result = self.storage.import_vault(path, password)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"无法导入备份：{e}")
            return False

        auth_settings = result.get('auth_settings') if isinstance(result, dict) else None
        imported_count = result.get('imported_count', 0) if isinstance(result, dict) else 0

        if auth_settings:
            try:
                self.auth.import_auth_settings(auth_settings)
            except Exception as e:
                QMessageBox.warning(self, "错误", f"恢复验证信息失败：{e}")
                return False
            self._imported_auth = True
            self.import_status_label.setText(
                f"已成功导入 {imported_count} 个文件，并恢复验证信息。\n"
                f"点击“下一步”将直接进入完成步骤。")
            self.import_status_label.setStyleSheet("color: #4caf50;")
            return True
        else:
            self._imported_auth = False
            self.import_status_label.setText(
                f"已导入 {imported_count} 个文件，但备份中未包含验证信息。\n"
                f"请继续在后续页面手动配置验证方式。")
            self.import_status_label.setStyleSheet("color: #ffaa00;")
            return True

    # ============================================================
    #  最后一步：保存
    # ============================================================
    def accept(self):
        if not self._imported_auth:
            # 1) 密码
            if self.pw_enable.isChecked():
                self.auth.set_password(self.pw_input.text())

            # 2) 安全问题
            if self.qa_enable.isChecked():
                qa_list = [
                    (self.q1.text().strip(), self.a1.text().strip()),
                    (self.q2.text().strip(), self.a2.text().strip()),
                    (self.q3.text().strip(), self.a3.text().strip()),
                ]
                self.auth.set_questions(qa_list)

            # 3) TOTP
            if self.totp_enable.isChecked():
                self.auth.save_totp_secret(self.totp_secret)
            else:
                self.auth.settings_dict.pop('totp_secret', None)
                self.auth.totp_secret = None

            # 4) 邮箱
            if self.email_enable.isChecked():
                self.auth.save_email_config(
                    self.smtp_server.text().strip(),
                    int(self.smtp_port.text().strip()),
                    self.sender_email.text().strip(),
                    self.sender_password.text(),
                    self.receiver_email.text().strip())
            else:
                self.auth.email_config = {}
                self.auth.settings_dict.pop('email', None)

            # 5) 启用映射
            enabled_map = {}
            if self.pw_enable.isChecked(): enabled_map['password'] = True
            if self.qa_enable.isChecked(): enabled_map['question'] = True
            if self.totp_enable.isChecked(): enabled_map['totp'] = True
            if self.email_enable.isChecked(): enabled_map['email'] = True
            self.auth.settings_dict['method_enabled'] = enabled_map

        # 6) 加密文件目录（通用，无论是否导入都需要保存）
        new_dir = self.secret_dir_input.text().strip()
        if new_dir and os.path.normcase(os.path.abspath(new_dir)) != \
                os.path.normcase(os.path.abspath(DEFAULT_SECRET_DIR)):
            self.auth.settings.set_secret_dir(new_dir)

        self.auth.settings_dict['initialized'] = True
        self.auth._save()
        super().accept()
