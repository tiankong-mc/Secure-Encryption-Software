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
        self.apply_style()
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
        import updater

        update_page = self.pages.get('update')
        if update_page:
            update_page.set_result(tr("update.checking"), "#888888")
        QApplication.processEvents()

        try:
            data = updater.get_latest_release(timeout=15)
            latest = data.get('tag_name', '')
            self.storage.log(f"检查更新: 当前{VERSION}, 远程{latest}")
            if updater.is_newer(latest):
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
        import updater
        import subprocess as sp

        try:
            latest = data.get('tag_name', '')
            asset = updater.find_exe_asset(data)
            if not asset:
                QMessageBox.warning(self, tr("common.error"), "未找到可执行文件")
                return
            url = asset['browser_download_url']
            expected_sha = updater.extract_sha256(data)

            self.storage.log(f"开始下载更新: {latest}")
            exe_dir = os.path.dirname(sys.executable)
            temp_path = os.path.join(exe_dir, "SecureVault_update.exe")

            # 上次失败可能残留，先清理一次以从零开始
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

            progress = QProgressDialog("正在下载更新...", "取消", 0, 100, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.show()

            def on_progress(done, total):
                if total:
                    progress.setValue(int(done / total * 100))
                QApplication.processEvents()
                if progress.wasCanceled():
                    raise KeyboardInterrupt

            try:
                updater.download_file(url, temp_path, progress_callback=on_progress)
            except KeyboardInterrupt:
                try: os.remove(temp_path)
                except: pass
                progress.close()
                QMessageBox.information(self, tr("common.info"), "已取消下载")
                return

            progress.setValue(100)
            progress.close()

            # SHA-256 校验
            if expected_sha:
                if not updater.verify_sha256(temp_path, expected_sha):
                    QMessageBox.critical(self, tr("common.error"), "SHA-256 校验失败")
                    try: os.remove(temp_path)
                    except: pass
                    return
            else:
                if QMessageBox.question(self, tr("common.warning"),
                                        "未提供 SHA-256，继续？",
                                        QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                    try: os.remove(temp_path)
                    except: pass
                    return

            QMessageBox.information(self, "更新完成",
                f"新版本 {latest} 已下载并准备替换。\n\n"
                "请手动关闭本程序，然后双击运行 SecureVault.exe 启动新版本。")

            bat_path = updater.write_update_bat(exe_dir, temp_path, sys.executable)
            sp.Popen([bat_path], creationflags=sp.CREATE_NEW_CONSOLE)
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
