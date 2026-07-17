import sys
import os
import tempfile
import subprocess
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from io import BytesIO
from PIL import Image, ImageQt
import docx
import PyPDF2
from backup import BackupManager

# ---------- 内置文件查看器 ----------
class FileViewer(QDialog):
    def __init__(self, parent, data, ftype, original_name):
        super().__init__(parent)
        self.setWindowTitle(f"查看: {original_name}")
        self.setModal(True)
        self.resize(700, 500)
        layout = QVBoxLayout()
        self.tmp_path = None
        self.player = None
        self.file_data = data          # 保存原始数据用于导出

        if ftype == 'text':
            text_edit = QTextEdit()
            text_edit.setPlainText(data.decode('utf-8', errors='replace'))
            text_edit.setReadOnly(True)
            layout.addWidget(text_edit)

        elif ftype == 'image':
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                label = QLabel()
                label.setPixmap(pixmap.scaled(600, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                layout.addWidget(label)
            else:
                try:
                    img = Image.open(BytesIO(data))
                    qimg = ImageQt.ImageQt(img)
                    pixmap = QPixmap.fromImage(qimg)
                    label = QLabel()
                    label.setPixmap(pixmap.scaled(600, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    layout.addWidget(label)
                except:
                    layout.addWidget(QLabel("无法显示该图片（格式不支持或数据损坏）"))

        elif ftype in ['video', 'audio']:
            try:
                ext = os.path.splitext(original_name)[1]
                tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
                os.close(tmp_fd)
                with open(tmp_path, 'wb') as f:
                    f.write(data)
                self.tmp_path = tmp_path
                abs_path = os.path.abspath(tmp_path)

                self.player = QMediaPlayer()
                if ftype == 'video':
                    self.video_widget = QVideoWidget()
                    layout.addWidget(self.video_widget)
                    self.player.setVideoOutput(self.video_widget)

                media_url = QUrl.fromLocalFile(abs_path)
                content = QMediaContent(media_url)
                self.player.setMedia(content)

                self.load_ok = False
                self.player.mediaStatusChanged.connect(self.check_media_status)
                QTimer.singleShot(5000, self.check_load_timeout)

                control_layout = QHBoxLayout()
                play_btn = QPushButton("播放/暂停")
                play_btn.clicked.connect(self.toggle_play)
                control_layout.addWidget(play_btn)
                stop_btn = QPushButton("停止")
                stop_btn.clicked.connect(self.player.stop)
                control_layout.addWidget(stop_btn)
                if ftype == 'audio':
                    self.position_label = QLabel("00:00 / 00:00")
                    control_layout.addWidget(self.position_label)
                    self.timer = QTimer(self)
                    self.timer.timeout.connect(self.update_position)
                    self.timer.start(1000)

                self.export_btn = QPushButton("导出并观看（内置播放失败时使用）")
                self.export_btn.clicked.connect(self.export_and_view)
                control_layout.addWidget(self.export_btn)

                layout.addLayout(control_layout)

                self.status_label = QLabel("正在加载媒体...")
                layout.addWidget(self.status_label)

                self.player.play()
                self.finished.connect(self.cleanup_tmp)

            except Exception as e:
                layout.addWidget(QLabel(f"播放器初始化失败: {e}"))
                btn = QPushButton("导出并观看")
                btn.clicked.connect(self.export_and_view)
                layout.addWidget(btn)

        elif ftype == 'document':
            ext = os.path.splitext(original_name)[1].lower()
            text_content = ""
            try:
                if ext in ['.docx']:
                    doc = docx.Document(BytesIO(data))
                    for para in doc.paragraphs:
                        text_content += para.text + "\n"
                elif ext in ['.pdf']:
                    pdf_reader = PyPDF2.PdfReader(BytesIO(data))
                    for page in pdf_reader.pages:
                        text_content += page.extract_text() + "\n"
                elif ext in ['.doc', '.odt', '.rtf']:
                    text_content = "此文档格式暂不支持直接预览，请导出为明文后使用外部程序查看。"
                else:
                    text_content = "未知文档格式"
            except Exception as e:
                text_content = f"文档解析失败: {e}"
            text_edit = QTextEdit()
            text_edit.setPlainText(text_content)
            text_edit.setReadOnly(True)
            layout.addWidget(text_edit)

        else:
            layout.addWidget(QLabel("不支持预览此文件类型，仅加密存储。"))

        self.setLayout(layout)

    def check_media_status(self, status):
        if status == QMediaPlayer.LoadedMedia or status == QMediaPlayer.BufferedMedia:
            self.load_ok = True
            if hasattr(self, 'status_label'):
                self.status_label.setText("媒体已加载，正在播放...")
        elif status == QMediaPlayer.InvalidMedia:
            if hasattr(self, 'status_label'):
                self.status_label.setText("❌ 媒体格式不支持或文件损坏，请使用“导出并观看”")
            self.load_ok = False
        elif status == QMediaPlayer.NoMedia:
            if hasattr(self, 'status_label'):
                self.status_label.setText("无媒体")
            self.load_ok = False

    def check_load_timeout(self):
        if not hasattr(self, 'load_ok') or not self.load_ok:
            if hasattr(self, 'status_label'):
                self.status_label.setText("⚠️ 加载超时，可能系统缺少解码器。请尝试“导出并观看”。")

    def toggle_play(self):
        if self.player and self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def update_position(self):
        if hasattr(self, 'player') and self.player:
            if self.player.state() != QMediaPlayer.StoppedState:
                pos = self.player.position()
                dur = self.player.duration()
                if dur > 0:
                    pos_str = f"{pos//60000:02d}:{(pos%60000)//1000:02d}"
                    dur_str = f"{dur//60000:02d}:{(dur%60000)//1000:02d}"
                    self.position_label.setText(f"{pos_str} / {dur_str}")

    def export_and_view(self):
        """从原始数据导出到新临时文件，避免文件占用问题"""
        if hasattr(self, 'file_data') and self.file_data:
            # 获取扩展名
            ext = os.path.splitext(self.windowTitle().replace("查看: ", ""))[1] if hasattr(self, 'windowTitle') else '.bin'
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(self.file_data)
                export_path = tmp.name
            os.startfile(export_path)
            QMessageBox.information(self, "提示", f"文件已导出到临时目录：{export_path}\n播放器关闭后该文件不会被自动删除，您可手动清理。")
        else:
            QMessageBox.warning(self, "错误", "没有可导出的数据")

    def cleanup_tmp(self):
        if hasattr(self, 'tmp_path') and self.tmp_path and os.path.exists(self.tmp_path):
            try:
                os.unlink(self.tmp_path)
            except:
                pass


# ---------- 二次验证对话框 ----------
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
        display_name = entry['original_name'] + '.vault'
        try:
            BackupManager.send_vault_file(vault_path, to_email, smtp_config, display_name)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"邮件发送失败: {e}")
            return
        storage.remove_entry(self.entry_id, destroy=True)
        auth.reset_fail_count()
        QMessageBox.critical(self, "紧急备份", f"加密文件已发送至您的邮箱，原始文件已被销毁。程序将退出。")
        QApplication.quit()


# ---------- 删除文件/操作验证对话框（不累计错误） ----------
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
        if ok:
            super().accept()
        else:
            QMessageBox.warning(self, "验证失败", "身份验证未通过，请重试或取消")


# ---------- 上传对话框 ----------
class UploadDialog(QDialog):
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
        methods_layout = QVBoxLayout()
        self.totp_cb = QCheckBox("TOTP (Authenticator)")
        self.email_cb = QCheckBox("邮箱验证码")
        self.question_cb = QCheckBox("安全问题")
        self.password_cb = QCheckBox("密码")
        methods_layout.addWidget(self.totp_cb)
        methods_layout.addWidget(self.email_cb)
        methods_layout.addWidget(self.question_cb)
        methods_layout.addWidget(self.password_cb)
        self.method_group.setLayout(methods_layout)
        layout.addWidget(self.method_group)
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
            if not self.second_methods:
                QMessageBox.warning(self, "提示", "高级文件至少选择一种二次验证方式")
                return
        super().accept()


# ---------- 首次设置向导 ----------
class SetupWizard(QWizard):
    def __init__(self, auth_manager):
        super().__init__()
        self.auth = auth_manager
        self.setWindowTitle("SecureVault 首次设置")
        self.setWizardStyle(QWizard.ModernStyle)
        page1 = QWizardPage()
        page1.setTitle("欢迎")
        page1.setSubTitle("配置安全设置以保护您的文件")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("请依次设置以下安全选项，至少需要配置一种验证方式。"))
        page1.setLayout(layout)
        self.addPage(page1)
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
        page6 = QWizardPage()
        page6.setTitle("完成")
        page6.setSubTitle("设置已保存，点击完成启动程序")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("所有设置将加密存储，请牢记您的安全信息。"))
        page6.setLayout(layout)
        self.addPage(page6)

    def initializePage(self, id):
        if id == 3:
            if not self.totp_setup_done:
                self.totp_secret = self.auth.setup_totp()
                qr_data = self.auth.setup_totp()
                pixmap = QPixmap()
                pixmap.loadFromData(qr_data)
                self.qr_label.setPixmap(pixmap.scaled(200, 200, Qt.KeepAspectRatio))
                self.totp_secret_label.setText(f"密钥：{self.auth.totp_secret}")
                self.totp_setup_done = True

    def accept(self):
        if self.pw_enable.isChecked():
            pw = self.pw_input.text()
            if len(pw) < 8:
                QMessageBox.warning(self, "错误", "密码长度至少8位")
                return
            if pw != self.pw_confirm.text():
                QMessageBox.warning(self, "错误", "两次密码输入不一致")
                return
            self.auth.set_password(pw)
        qa_list = []
        for q, a in [(self.q1.text(), self.a1.text()), (self.q2.text(), self.a2.text()), (self.q3.text(), self.a3.text())]:
            if not q or not a:
                QMessageBox.warning(self, "错误", "请完整填写所有安全问题和答案")
                return
            qa_list.append((q, a))
        self.auth.set_questions(qa_list)
        if self.totp_enable.isChecked():
            code = self.totp_code.text()
            if not self.auth.verify_totp(code):
                QMessageBox.warning(self, "错误", "TOTP验证码不正确，请重新输入")
                return
        else:
            self.auth.settings_dict.pop('totp_secret', None)
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
        self.auth.settings_dict['initialized'] = True
        self.auth._save()
        super().accept()


# ---------- 登录对话框 ----------
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
        file_info_list = storage.get_all_vault_paths_with_names()
        if not file_info_list:
            QMessageBox.critical(self, "错误", "没有可备份的文件")
            return
        try:
            BackupManager.send_multiple_vault_files(file_info_list, to_email, smtp_config)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"邮件发送失败: {e}")
            return
        for entry in storage.get_all_entries():
            storage.remove_entry(entry['id'], destroy=True)
        storage.index = []
        storage._save_index()
        auth.reset_fail_count()
        QMessageBox.critical(self, "紧急备份", "所有加密文件已发送至您的邮箱，原始文件已被销毁。程序将退出。")
        QApplication.quit()


# ---------- 设置对话框 ----------
class SettingsDialog(QDialog):
    def __init__(self, parent, auth_manager):
        super().__init__(parent)
        self.auth = auth_manager
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(500, 400)
        layout = QVBoxLayout()

        info_label = QLabel("当前已启用的验证方式：")
        layout.addWidget(info_label)
        methods = []
        if self.auth.password_hash:
            methods.append("密码")
        if self.auth.qa:
            methods.append("安全问题")
        if self.auth.totp_secret:
            methods.append("TOTP")
        if self.auth.email_config:
            methods.append("邮箱验证码")
        status_text = ", ".join(methods) if methods else "无"
        status_label = QLabel(f"已启用：{status_text}")
        layout.addWidget(status_label)

        self.btn_change_password = QPushButton("修改密码")
        self.btn_change_password.clicked.connect(self.change_password)
        layout.addWidget(self.btn_change_password)

        self.btn_change_questions = QPushButton("修改安全问题")
        self.btn_change_questions.clicked.connect(self.change_questions)
        layout.addWidget(self.btn_change_questions)

        self.btn_change_totp = QPushButton("修改 TOTP 设置")
        self.btn_change_totp.clicked.connect(self.change_totp)
        layout.addWidget(self.btn_change_totp)

        self.btn_change_email = QPushButton("修改邮箱配置")
        self.btn_change_email.clicked.connect(self.change_email)
        layout.addWidget(self.btn_change_email)

        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self.setLayout(layout)

    def _verify_identity(self):
        available_methods = []
        if self.auth.password_hash:
            available_methods.append('password')
        if self.auth.qa:
            available_methods.append('question')
        if self.auth.totp_secret:
            available_methods.append('totp')
        if self.auth.email_config:
            available_methods.append('email')
        if not available_methods:
            QMessageBox.warning(self, "提示", "没有可用的验证方式，无法修改。")
            return False
        dialog = DeleteAuthDialog(self, self.auth, available_methods)
        return dialog.exec_() == QDialog.Accepted

    def change_password(self):
        if not self._verify_identity():
            return
        pw, ok = QInputDialog.getText(self, "修改密码", "输入新密码（至少8位）：", QLineEdit.Password)
        if not ok:
            return
        if len(pw) < 8:
            QMessageBox.warning(self, "错误", "密码长度至少8位")
            return
        confirm, ok = QInputDialog.getText(self, "修改密码", "再次输入新密码：", QLineEdit.Password)
        if not ok:
            return
        if pw != confirm:
            QMessageBox.warning(self, "错误", "两次密码不一致")
            return
        self.auth.set_password(pw)
        QMessageBox.information(self, "成功", "密码已更新")

    def change_questions(self):
        if not self._verify_identity():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("修改安全问题")
        layout = QVBoxLayout()
        q1 = QLineEdit(); q1.setPlaceholderText("问题1")
        a1 = QLineEdit(); a1.setEchoMode(QLineEdit.Password); a1.setPlaceholderText("答案1")
        q2 = QLineEdit(); q2.setPlaceholderText("问题2")
        a2 = QLineEdit(); a2.setEchoMode(QLineEdit.Password); a2.setPlaceholderText("答案2")
        q3 = QLineEdit(); q3.setPlaceholderText("问题3")
        a3 = QLineEdit(); a3.setEchoMode(QLineEdit.Password); a3.setPlaceholderText("答案3")
        layout.addWidget(QLabel("问题1"))
        layout.addWidget(q1)
        layout.addWidget(a1)
        layout.addWidget(QLabel("问题2"))
        layout.addWidget(q2)
        layout.addWidget(a2)
        layout.addWidget(QLabel("问题3"))
        layout.addWidget(q3)
        layout.addWidget(a3)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)
        dialog.setLayout(layout)
        if dialog.exec_() != QDialog.Accepted:
            return
        if not q1.text() or not a1.text() or not q2.text() or not a2.text() or not q3.text() or not a3.text():
            QMessageBox.warning(self, "错误", "请完整填写所有问题和答案")
            return
        qa_list = [(q1.text(), a1.text()), (q2.text(), a2.text()), (q3.text(), a3.text())]
        self.auth.set_questions(qa_list)
        QMessageBox.information(self, "成功", "安全问题已更新")

    def change_totp(self):
        if not self._verify_identity():
            return
        reply = QMessageBox.question(self, "确认", "重新生成 TOTP 密钥将导致之前的二维码失效，是否继续？", QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        qr_data = self.auth.setup_totp()
        pixmap = QPixmap()
        pixmap.loadFromData(qr_data)
        dialog = QDialog(self)
        dialog.setWindowTitle("TOTP 设置")
        layout = QVBoxLayout()
        label = QLabel("请使用 Authenticator 扫描以下二维码：")
        layout.addWidget(label)
        img_label = QLabel()
        img_label.setPixmap(pixmap.scaled(200, 200, Qt.KeepAspectRatio))
        layout.addWidget(img_label)
        secret_label = QLabel(f"密钥：{self.auth.totp_secret}")
        layout.addWidget(secret_label)
        code_input = QLineEdit()
        code_input.setPlaceholderText("输入动态码验证")
        layout.addWidget(code_input)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)
        dialog.setLayout(layout)
        if dialog.exec_() == QDialog.Accepted:
            if not self.auth.verify_totp(code_input.text()):
                QMessageBox.warning(self, "错误", "验证码不正确，请重新尝试")
                return
            QMessageBox.information(self, "成功", "TOTP 已更新")

    def change_email(self):
        if not self._verify_identity():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("修改邮箱配置")
        layout = QVBoxLayout()
        smtp_server = QLineEdit()
        smtp_server.setPlaceholderText("SMTP服务器 (如 smtp.qq.com)")
        smtp_server.setText(self.auth.email_config.get('smtp_server', ''))
        smtp_port = QLineEdit()
        smtp_port.setPlaceholderText("端口 (如 587)")
        smtp_port.setText(str(self.auth.email_config.get('port', '')))
        sender_email = QLineEdit()
        sender_email.setPlaceholderText("发件邮箱")
        sender_email.setText(self.auth.email_config.get('sender_email', ''))
        sender_password = QLineEdit()
        sender_password.setEchoMode(QLineEdit.Password)
        sender_password.setPlaceholderText("授权码或密码")
        sender_password.setText(self.auth.email_config.get('password', ''))
        receiver_email = QLineEdit()
        receiver_email.setPlaceholderText("收件邮箱（用于接收验证码）")
        receiver_email.setText(self.auth.email_config.get('receiver_email', ''))
        layout.addWidget(QLabel("SMTP服务器"))
        layout.addWidget(smtp_server)
        layout.addWidget(QLabel("端口"))
        layout.addWidget(smtp_port)
        layout.addWidget(QLabel("发件邮箱"))
        layout.addWidget(sender_email)
        layout.addWidget(QLabel("授权码/密码"))
        layout.addWidget(sender_password)
        layout.addWidget(QLabel("收件邮箱"))
        layout.addWidget(receiver_email)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)
        dialog.setLayout(layout)
        if dialog.exec_() != QDialog.Accepted:
            return
        if not all([smtp_server.text(), smtp_port.text(), sender_email.text(), sender_password.text(), receiver_email.text()]):
            QMessageBox.warning(self, "错误", "请完整填写所有字段")
            return
        try:
            port = int(smtp_port.text())
        except:
            QMessageBox.warning(self, "错误", "端口必须为数字")
            return
        self.auth.set_email_config(smtp_server.text(), port, sender_email.text(), sender_password.text(), receiver_email.text())
        code = self.auth.send_verification_code(receiver_email.text())
        if not code:
            QMessageBox.warning(self, "错误", "邮箱配置测试失败，请检查设置")
            return
        verify_code, ok = QInputDialog.getText(self, "验证邮箱", f"输入发送到 {receiver_email.text()} 的验证码")
        if not ok or verify_code != code:
            QMessageBox.warning(self, "错误", "验证码错误")
            return
        QMessageBox.information(self, "成功", "邮箱配置已更新")


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
        self.file_list = QListWidget()
        self.file_list.itemDoubleClicked.connect(self.open_file)
        layout.addWidget(self.file_list)
        central.setLayout(layout)
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
            layout.addWidget(cb_totp)
            layout.addWidget(cb_email)
            layout.addWidget(cb_question)
            layout.addWidget(cb_password)
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
        available_methods = self._get_available_auth_methods()
        if not available_methods:
            QMessageBox.warning(self, "提示", "没有可用的验证方式，请先设置安全选项。")
            return
        auth_dialog = DeleteAuthDialog(self, self.auth, available_methods)
        if auth_dialog.exec_() != QDialog.Accepted:
            return
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
        dialog = SettingsDialog(self, self.auth)
        dialog.exec_()

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
        return methods
