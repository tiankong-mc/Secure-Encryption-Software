import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import os, sys, re, threading, socket, subprocess, hashlib
from io import BytesIO
import requests
import qrcode
import pyotp
from datetime import datetime
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QComboBox, QDialogButtonBox, QMessageBox,
                              QCheckBox, QGroupBox, QFileDialog, QInputDialog,
                              QApplication, QProgressDialog, QListWidget, QListWidgetItem,
                              QStackedWidget, QWidget)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from packaging.version import parse as parse_version

from constants import VERSION, WEB_PORT, ISSUES_URL
from ui_utils import protect_window, apply_protection_to_all_windows
from ui_dialogs import DeleteAuthDialog
from i18n import tr
from ui_styles import DARK_STYLE, LIGHT_STYLE

from ui_settings_pages.page_security import SecurityPage
from ui_settings_pages.page_web import WebPage
from ui_settings_pages.page_appearance import AppearancePage
from ui_settings_pages.page_language import LanguagePage
from ui_settings_pages.page_update import UpdatePage
from ui_settings_pages.page_about import AboutPage


class SettingsDialog(QDialog):
    def __init__(self, parent, auth_manager, is_recovery_login=False):
        super().__init__(parent)
        self.auth = auth_manager
        self.is_recovery_login = is_recovery_login
        self.parent_main = parent
        self.storage = parent.storage

        self.setWindowTitle(tr("settings.title"))
        self.setModal(False)
        self.resize(780, 560)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 侧边栏（样式在 apply_style 中设置）
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(160)
        main_layout.addWidget(self.sidebar)

        # 页面堆叠
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget{background:transparent;}")
        main_layout.addWidget(self.stack, 1)

        # 创建页面
        self.pages = {
            'security': SecurityPage(self),
            'web': WebPage(self),
            'appearance': AppearancePage(self),
            'language': LanguagePage(self),
            'update': UpdatePage(self),
            'about': AboutPage(self),
        }
        for key, page in self.pages.items():
            self.stack.addWidget(page)

        self._last_row = 0
        self._ignore_change = False

        self._build_sidebar()
        self.sidebar.currentRowChanged.connect(self.on_sidebar_changed)

        # 首次应用样式
        self.apply_style()

    # ---------- 样式 ----------
    def apply_style(self):
        theme = self.auth.settings_dict.get('theme', '明亮')
        base = DARK_STYLE if theme == "暗黑" else LIGHT_STYLE
        self.setStyleSheet(base)
        self._update_sidebar_style(theme)

    def _update_sidebar_style(self, theme):
        if theme == "暗黑":
            qss = (
                "QListWidget{border:none;background:#262626;color:#ddd;padding:8px 0;}"
                "QListWidget::item{padding:10px 16px;}"
                "QListWidget::item:selected{background:#3a3a3a;color:#fff;}"
            )
        else:
            qss = (
                "QListWidget{border:none;background:#f3f3f3;color:#333;padding:8px 0;}"
                "QListWidget::item{padding:10px 16px;}"
                "QListWidget::item:selected{background:#d9d9d9;color:#000;}"
            )
        self.sidebar.setStyleSheet(qss)

    # ---------- 侧边栏 ----------
    def _build_sidebar(self):
        self.sidebar.clear()
        items = [
            ('security', 'settings.sidebar.security'),
            ('web', 'settings.sidebar.web'),
            ('appearance', 'settings.sidebar.appearance'),
            ('language', 'settings.sidebar.language'),
            ('feedback', 'settings.sidebar.feedback'),
            ('update', 'settings.sidebar.update'),
            ('about', 'settings.sidebar.about'),
        ]
        for key, tk in items:
            item = QListWidgetItem(tr(tk))
            item.setData(Qt.UserRole, key)
            self.sidebar.addItem(item)

    def on_sidebar_changed(self, row):
        if self._ignore_change or row < 0:
            return
        item = self.sidebar.item(row)
        key = item.data(Qt.UserRole)
        if key == 'feedback':
            self._ignore_change = True
            self.sidebar.setCurrentRow(self._last_row)
            self._ignore_change = False
            self.open_feedback()
            return
        self._last_row = row
        if key in self.pages:
            self.stack.setCurrentWidget(self.pages[key])
        self.storage.log(f"打开设置页面: {key}")

    def open_feedback(self):
        QMessageBox.information(self, tr("common.info"), tr("feedback.vpn_tip"))
        try:
            import webbrowser
            webbrowser.open(ISSUES_URL)
            self.storage.log("打开反馈页面")
        except Exception as e:
            QMessageBox.warning(self, tr("common.error"), str(e))

    def showEvent(self, event):
        super().showEvent(event)
        # 无论开启还是关闭，都同步一次当前设置窗口的截屏保护状态
        enabled = getattr(self.parent_main, 'screenshot_protection', False)
        protect_window(self, enabled)

    def retranslate_all(self):
        self.setWindowTitle(tr("settings.title"))
        self.apply_style()
        self._build_sidebar()
        self._ignore_change = True
        self.sidebar.setCurrentRow(self._last_row)
        self._ignore_change = False
        for page in self.pages.values():
            if hasattr(page, 'retranslate'):
                try:
                    page.retranslate()
                except Exception:
                    pass

    # ---------- 权限验证 ----------
    def _verify_identity(self):
        if self.is_recovery_login:
            return True
        methods = []
        if self.auth.password_hash: methods.append('password')
        if self.auth.qa: methods.append('question')
        if self.auth.totp_secret: methods.append('totp')
        if self.auth.email_config: methods.append('email')
        if not methods:
            QMessageBox.warning(self, tr("common.warning"), "没有可用的验证方式")
            return False
        dialog = DeleteAuthDialog(self, self.auth, methods)
        return dialog.exec_() == QDialog.Accepted

    # ---------- 主题/开关 ----------
    def on_theme_changed(self, theme):
        self.auth.settings_dict['theme'] = theme
        self.auth._save()
        self.apply_style()  # 更新设置窗口 + 侧边栏样式
        if self.parent_main:
            self.parent_main.apply_theme(theme)
            self.storage.log(f"切换主题为: {theme}")

    def toggle_screenshot_protection(self, state):
        enabled = (state == Qt.Checked)
        self.auth.settings_dict['screenshot_protection'] = enabled
        self.auth._save()
        if self.parent_main:
            self.parent_main.screenshot_protection = enabled
            self.parent_main.apply_screenshot_protection()
            self.storage.log(f"截屏保护: {'启用' if enabled else '禁用'}")
        # 同步更新所有已打开的窗口（设置窗口、预览窗口等）
        apply_protection_to_all_windows(enabled)

    def toggle_log(self, state):
        enabled = (state == Qt.Checked)
        self.auth.settings_dict['log_enabled'] = enabled
        self.auth._save()
        self.storage.log(f"日志记录: {'启用' if enabled else '禁用'}")

    # ---------- 恢复代码 ----------
    def generate_recovery(self):
        try:
            if not self.is_recovery_login and not self._verify_identity():
                return
            code = self.auth.generate_recovery_code()
            self.storage.log("生成紧急恢复代码")
            dialog = QDialog(self); dialog.setWindowTitle("紧急恢复代码")
            layout = QVBoxLayout()
            layout.addWidget(QLabel("您的紧急恢复代码已生成，请妥善保管："))
            code_label = QLabel(code)
            code_label.setStyleSheet("font-size:16pt;font-weight:bold;font-family:monospace;")
            code_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(code_label)
            code_edit = QLineEdit(code); code_edit.setReadOnly(True)
            code_edit.setStyleSheet("font-family:monospace;")
            layout.addWidget(code_edit)
            export_btn = QPushButton("导出为 .txt 文件")

            def export_code():
                try:
                    path, _ = QFileDialog.getSaveFileName(self, "保存恢复代码", "recovery_code.txt", "Text Files (*.txt)")
                    if path:
                        with open(path, 'w') as f:
                            f.write(f"紧急恢复代码：{code}\n\n生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                        QMessageBox.information(dialog, "导出成功", f"代码已保存到：{path}")
                except Exception as e:
                    QMessageBox.warning(dialog, "导出失败", str(e))
            export_btn.clicked.connect(export_code)
            layout.addWidget(export_btn)
            btn_box = QDialogButtonBox(QDialogButtonBox.Close)
            btn_box.rejected.connect(dialog.accept)
            layout.addWidget(btn_box)
            dialog.setLayout(layout); dialog.exec_()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成恢复代码失败: {e}")

    # ---------- 检查更新 ----------
    def check_update(self):
        update_page = self.pages.get('update')
        if update_page:
            update_page.set_result(tr("update.checking"), "#888888")
        QApplication.processEvents()

        try:
            headers = {'User-Agent': 'SecureVault'}
            resp = requests.get(
                "https://api.github.com/repos/tiankong-mc/Secure-Encryption-Software/releases/latest",
                timeout=10, headers=headers, verify=False)
            if resp.status_code != 200:
                if update_page:
                    update_page.set_result(f"{tr('common.error')}: HTTP {resp.status_code}", "#ff4444")
                return
            data = resp.json()
            latest = data.get('tag_name', '')
            self.storage.log(f"检查更新: 当前{VERSION}, 远程{latest}")
            if parse_version(latest) > parse_version(VERSION):
                if update_page:
                    update_page.set_result(f"{tr('update.new_available')}: {latest}", "#5a8cbf")
                ret = QMessageBox.question(
                    self, tr("update.new_available"),
                    f"{latest} > {VERSION}\n\n是否下载并更新？",
                    QMessageBox.Yes | QMessageBox.No)
                if ret == QMessageBox.Yes:
                    self.download_update(data)
            else:
                if update_page:
                    update_page.set_result(f"{tr('update.up_to_date')}（{VERSION}）", "#4caf50")
        except Exception as e:
            if update_page:
                update_page.set_result(f"{tr('common.error')}: {e}", "#ff4444")

    def download_update(self, data):
        try:
            latest = data.get('tag_name', '')
            self.storage.log(f"开始下载更新: {latest}")
            assets = data.get('assets', []); exe_asset = None
            for a in assets:
                if a.get('name', '').lower() == 'encryption.exe':
                    exe_asset = a; break
            if not exe_asset:
                QMessageBox.warning(self, tr("common.error"), "未找到可执行文件"); return
            url = exe_asset['browser_download_url']
            progress = QProgressDialog("正在下载更新...", "取消", 0, 100, self)
            progress.setWindowModality(Qt.WindowModal); progress.show()
            response = requests.get(url, stream=True, verify=False)
            total_size = int(response.headers.get('content-length', 0))
            block_size = 8192
            temp_path = os.path.join(os.path.dirname(sys.executable), "SecureVault_update.exe")
            sha256 = hashlib.sha256()
            with open(temp_path, 'wb') as f:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=block_size):
                    if chunk:
                        f.write(chunk); downloaded += len(chunk)
                        sha256.update(chunk)
                        if total_size:
                            progress.setValue(int(downloaded / total_size * 100))
                        QApplication.processEvents()
            progress.setValue(100)
            body = data.get('body', '')
            match = re.search(r'sha256[:\s]*([a-fA-F0-9]{64})', body)
            if match:
                if sha256.hexdigest().lower() != match.group(1).lower():
                    QMessageBox.critical(self, tr("common.error"), "SHA-256 校验失败")
                    try: os.remove(temp_path)
                    except: pass
                    return
            else:
                if QMessageBox.question(self, tr("common.warning"), "未提供 SHA-256，继续？",
                                        QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                    try: os.remove(temp_path)
                    except: pass
                    return
            QMessageBox.information(self, "更新完成",
                f"新版本 {latest} 已下载并准备替换。\n\n"
                "请手动关闭本程序，然后双击运行 SecureVault.exe 启动新版本。")
            bat_path = os.path.join(os.path.dirname(sys.executable), "update.bat")
            with open(bat_path, 'w') as f:
                f.write(f"""@echo off
timeout /t 2 > nul
copy /Y "{temp_path}" "{sys.executable}"
del "{temp_path}"
del "%~f0"
""")
            subprocess.Popen([bat_path], creationflags=subprocess.CREATE_NEW_CONSOLE)
            self.storage.log("更新替换完成，用户手动启动")
            QApplication.quit()
        except Exception as e:
            QMessageBox.critical(self, tr("common.error"), f"更新失败: {e}")

    # ---------- 修改验证信息 ----------
    def change_password(self):
        if not self._verify_identity(): return
        pw, ok = QInputDialog.getText(self, "修改密码", "输入新密码（至少8位）：", QLineEdit.Password)
        if not ok: return
        if len(pw) < 8:
            QMessageBox.warning(self, tr("common.error"), "密码长度至少8位"); return
        confirm, ok = QInputDialog.getText(self, "修改密码", "再次输入新密码：", QLineEdit.Password)
        if not ok or pw != confirm:
            QMessageBox.warning(self, tr("common.error"), "两次密码不一致"); return
        self.auth.set_password(pw)
        self.storage.log("修改密码")
        QMessageBox.information(self, tr("common.success"), "密码已更新")

    def change_questions(self):
        if not self._verify_identity(): return
        dialog = QDialog(self); dialog.setWindowTitle("修改安全问题")
        layout = QVBoxLayout()
        q1 = QLineEdit(); a1 = QLineEdit(); a1.setEchoMode(QLineEdit.Password)
        q2 = QLineEdit(); a2 = QLineEdit(); a2.setEchoMode(QLineEdit.Password)
        q3 = QLineEdit(); a3 = QLineEdit(); a3.setEchoMode(QLineEdit.Password)
        layout.addWidget(QLabel("问题1")); layout.addWidget(q1); layout.addWidget(a1)
        layout.addWidget(QLabel("问题2")); layout.addWidget(q2); layout.addWidget(a2)
        layout.addWidget(QLabel("问题3")); layout.addWidget(q3); layout.addWidget(a3)
        btn = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn.accepted.connect(dialog.accept); btn.rejected.connect(dialog.reject)
        layout.addWidget(btn); dialog.setLayout(layout)
        if dialog.exec_() != QDialog.Accepted: return
        if not all([q1.text(), a1.text(), q2.text(), a2.text(), q3.text(), a3.text()]):
            QMessageBox.warning(self, tr("common.error"), "请完整填写"); return
        self.auth.set_questions([(q1.text(), a1.text()), (q2.text(), a2.text()), (q3.text(), a3.text())])
        self.storage.log("修改安全问题")
        QMessageBox.information(self, tr("common.success"), "安全问题已更新")

    def change_totp(self):
        if not self._verify_identity(): return
        if QMessageBox.question(self, "确认", "重新生成 TOTP 密钥？",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        temp_secret = self.auth.generate_totp_secret()
        totp = pyotp.TOTP(temp_secret)
        uri = totp.provisioning_uri(name="SecureVault", issuer_name="SecureApp")
        qr_img = qrcode.make(uri)
        buf = BytesIO(); qr_img.save(buf, format='PNG')
        pixmap = QPixmap(); pixmap.loadFromData(buf.getvalue())
        dialog = QDialog(self); dialog.setWindowTitle("TOTP 设置")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("扫描二维码："))
        img = QLabel(); img.setPixmap(pixmap.scaled(200, 200, Qt.KeepAspectRatio))
        layout.addWidget(img)
        layout.addWidget(QLabel(f"临时密钥：{temp_secret}"))
        code_input = QLineEdit(); code_input.setPlaceholderText("输入动态码验证")
        layout.addWidget(code_input)
        btn = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn.accepted.connect(dialog.accept); btn.rejected.connect(dialog.reject)
        layout.addWidget(btn); dialog.setLayout(layout)
        if dialog.exec_() == QDialog.Accepted:
            if self.auth.verify_totp_secret(temp_secret, code_input.text()):
                self.auth.save_totp_secret(temp_secret)
                self.storage.log("修改 TOTP")
                QMessageBox.information(self, tr("common.success"), "TOTP 已更新")
            else:
                QMessageBox.warning(self, tr("common.error"), "验证码不正确")

    def change_email(self):
        if not self._verify_identity(): return
        dialog = QDialog(self); dialog.setWindowTitle("修改邮箱配置")
        layout = QVBoxLayout()
        smtp = QLineEdit(self.auth.email_config.get('smtp_server', ''))
        port = QLineEdit(str(self.auth.email_config.get('port', '')))
        sender = QLineEdit(self.auth.email_config.get('sender_email', ''))
        pwd = QLineEdit(self.auth.email_config.get('password', '')); pwd.setEchoMode(QLineEdit.Password)
        recv = QLineEdit(self.auth.email_config.get('receiver_email', ''))
        layout.addWidget(QLabel("SMTP服务器")); layout.addWidget(smtp)
        layout.addWidget(QLabel("端口")); layout.addWidget(port)
        layout.addWidget(QLabel("发件邮箱")); layout.addWidget(sender)
        layout.addWidget(QLabel("授权码")); layout.addWidget(pwd)
        layout.addWidget(QLabel("收件邮箱")); layout.addWidget(recv)
        btn = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn.accepted.connect(dialog.accept); btn.rejected.connect(dialog.reject)
        layout.addWidget(btn); dialog.setLayout(layout)
        if dialog.exec_() != QDialog.Accepted: return
        try:
            port_i = int(port.text())
        except:
            QMessageBox.warning(self, tr("common.error"), "端口必须为数字"); return
        if not all([smtp.text(), sender.text(), pwd.text(), recv.text()]):
            QMessageBox.warning(self, tr("common.error"), "请完整填写"); return
        ok, result = self.auth.test_email_config(smtp.text(), port_i, sender.text(), pwd.text(), recv.text())
        if not ok:
            QMessageBox.warning(self, tr("common.error"), f"测试失败: {result}"); return
        vc, ok = QInputDialog.getText(self, "验证邮箱", f"输入 {recv.text()} 收到的验证码")
        if not ok or vc != result:
            QMessageBox.warning(self, tr("common.error"), "验证码错误"); return
        self.auth.save_email_config(smtp.text(), port_i, sender.text(), pwd.text(), recv.text())
        self.storage.log("修改邮箱配置")
        QMessageBox.information(self, tr("common.success"), "邮箱配置已更新")
