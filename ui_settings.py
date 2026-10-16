import os, sys, shutil, secrets, time
from io import BytesIO
import qrcode
import pyotp
from datetime import datetime
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QComboBox, QDialogButtonBox, QMessageBox,
                              QCheckBox, QGroupBox, QFileDialog, QInputDialog,
                              QApplication, QListWidget, QListWidgetItem,
                              QStackedWidget, QWidget, QScrollArea)
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, QSize
from PyQt5.QtGui import QPixmap

from constants import VERSION, WEB_PORT, ISSUES_URL
from ui_utils import protect_window, apply_protection_to_all_windows
from ui_dialogs import DeleteAuthDialog
from download_helper import EmailConfigHelperDownloader, create_download_button
from i18n import tr
from ui_styles import DARK_STYLE, LIGHT_STYLE
from ui_settings_style import get_sidebar_qss, get_content_qss

from ui_settings_pages.page_security import SecurityPage
from ui_settings_pages.page_web import WebPage
from ui_settings_pages.page_appearance import AppearancePage
from ui_settings_pages.page_language import LanguagePage
from ui_settings_pages.page_update import UpdatePage
from ui_settings_pages.page_about import AboutPage


UNLOCK_TTL_SECONDS = 120


class SmoothScrollArea(QScrollArea):
    """支持鼠标滚轮平滑滚动的 QScrollArea。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._animation = QPropertyAnimation(self.verticalScrollBar(), b"value")
        self._animation.setDuration(200)
        self._animation.setEasingCurve(QEasingCurve.OutQuad)

    def wheelEvent(self, event):
        if event.angleDelta().y() == 0:
            super().wheelEvent(event)
            return

        delta = event.angleDelta().y()
        scrollbar = self.verticalScrollBar()
        current = scrollbar.value()

        step = 60
        if delta > 0:
            target = max(0, current - step)
        else:
            target = min(scrollbar.maximum(), current + step)

        self._animation.stop()
        self._animation.setStartValue(current)
        self._animation.setEndValue(target)
        self._animation.start()
        event.accept()


def _is_subpath(child, parent):
    try:
        child = os.path.normcase(os.path.abspath(child))
        parent = os.path.normcase(os.path.abspath(parent))
        if child == parent:
            return True
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


class SettingsDialog(QDialog):
    def __init__(self, parent, auth_manager, is_recovery_login=False):
        super().__init__(parent)
        self.auth = auth_manager
        self.is_recovery_login = is_recovery_login
        self.parent_main = parent
        self.storage = parent.storage

        if is_recovery_login:
            self._unlocked_until = getattr(self.auth, 'recovery_verified_until', 0.0)
        else:
            self._unlocked_until = 0.0
        self._email_downloader = None

        self.setWindowTitle(tr("settings.title"))
        self.setModal(False)

        self.setMinimumSize(680, 450)

        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            w = min(900, int(available.width() * 0.9))
            w = max(w, self.minimumWidth())
            h = min(600, int(available.height() * 0.85))
            h = max(h, 450)
            self.resize(w, h)
        else:
            self.resize(900, 600)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(180)
        self.sidebar.setFocusPolicy(Qt.NoFocus)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        main_layout.addWidget(self.sidebar)

        self.content_wrapper = QWidget()
        self.content_wrapper.setObjectName("SettingsPage")
        wrapper_layout = QVBoxLayout(self.content_wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Stack")

        self.scroll_area = SmoothScrollArea()
        self.scroll_area.setWidget(self.stack)
        self.scroll_area.setViewportMargins(0, 0, 10, 0)
        wrapper_layout.addWidget(self.scroll_area)

        # ---------- 安全锁定覆盖层 ----------
        self.security_overlay = QWidget(self.content_wrapper)
        overlay_layout = QVBoxLayout(self.security_overlay)
        overlay_layout.addStretch()

        self.overlay_hint_label = QLabel(tr("security.locked_hint"))
        self.overlay_hint_label.setAlignment(Qt.AlignCenter)
        self.overlay_hint_label.setWordWrap(True)
        self.overlay_hint_label.setStyleSheet("font-size: 14pt; color: #888;")
        overlay_layout.addWidget(self.overlay_hint_label)

        overlay_layout.addSpacing(20)

        overlay_btn_layout = QHBoxLayout()
        overlay_btn_layout.addStretch()
        self.overlay_verify_btn = QPushButton(tr("security.verify_button"))
        self.overlay_verify_btn.setFixedWidth(180)
        self.overlay_verify_btn.setMinimumHeight(38)
        self.overlay_verify_btn.clicked.connect(self._on_overlay_verify_clicked)
        overlay_btn_layout.addWidget(self.overlay_verify_btn)
        overlay_btn_layout.addStretch()
        overlay_layout.addLayout(overlay_btn_layout)

        overlay_layout.addStretch()
        self.security_overlay.hide()

        main_layout.addWidget(self.content_wrapper, 1)

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
        self.sidebar.setCurrentRow(0)

        self.apply_style()
        self._center_on_screen()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            window_geo = self.frameGeometry()
            window_geo.moveCenter(screen_geo.center())
            self.move(window_geo.topLeft())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.security_overlay.setGeometry(self.content_wrapper.rect())

    def _is_unlocked(self):
        return time.time() < self._unlocked_until

    def _update_security_overlay(self):
        if self.sidebar.currentItem() and self.sidebar.currentItem().data(Qt.UserRole) == 'security':
            if self._is_unlocked():
                self.security_overlay.hide()
            else:
                self.security_overlay.show()
                self.security_overlay.raise_()
        else:
            self.security_overlay.hide()

    def _on_overlay_verify_clicked(self):
        methods = self.auth.get_enabled_methods()
        if not methods:
            QMessageBox.warning(self, tr("common.warning"), "没有可用的验证方式")
            return
        dialog = DeleteAuthDialog(self, self.auth, methods)
        if dialog.exec_() == QDialog.Accepted:
            self._unlocked_until = time.time() + UNLOCK_TTL_SECONDS
            self._update_security_overlay()
            page = self.pages.get('security')
            if page:
                page.refresh_rows()

    def closeEvent(self, event):
        """关闭时不需要停止下载（下载在 UpdateManager 中独立进行），
        只需断开 update 页面的信号订阅。"""
        update_page = self.pages.get('update')
        if update_page is not None:
            try:
                update_page.detach_from_manager()
            except Exception:
                pass
        super().closeEvent(event)

    def apply_style(self):
        theme = self.auth.settings_dict.get('theme', '明亮')
        base = DARK_STYLE if theme == "暗黑" else LIGHT_STYLE
        self.setStyleSheet(base)
        self.sidebar.setStyleSheet(get_sidebar_qss(theme))
        self.content_wrapper.setStyleSheet(get_content_qss(theme))

        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.scroll_area.viewport().setStyleSheet("background: transparent;")

        if theme == "暗黑":
            self.security_overlay.setStyleSheet("background-color: #2b2b2b;")
        else:
            self.security_overlay.setStyleSheet("background-color: #f5f5f5;")

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
            item.setTextAlignment(Qt.AlignCenter)
            item.setSizeHint(QSize(self.sidebar.width() - 4, 42))
            self.sidebar.addItem(item)

    def on_sidebar_changed(self, row):
        if self._ignore_change or row < 0:
            return
        item = self.sidebar.item(row)
        if item is None:
            return
        key = item.data(Qt.UserRole)
        if key == 'feedback':
            self._ignore_change = True
            self.sidebar.setCurrentRow(self._last_row)
            self._ignore_change = False
            self.open_feedback()
            return
        self._last_row = row

        if key in self.pages:
            # 管理 update 页面的信号订阅
            update_page = self.pages.get('update')
            if update_page is not None:
                if key == 'update':
                    parent_main = getattr(self, 'parent_main', None)
                    manager = getattr(parent_main, 'update_manager', None) if parent_main else None
                    if manager is not None:
                        update_page.attach_to_manager(manager)
                    update_page.sync_state()
                else:
                    update_page.detach_from_manager()

            self.stack.setCurrentWidget(self.pages[key])
            self.scroll_area.verticalScrollBar().setValue(0)
            self._update_security_overlay()
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
        count = self.sidebar.count()
        safe_row = max(0, min(self._last_row, count - 1))
        self.sidebar.setCurrentRow(safe_row)
        self._last_row = safe_row
        self._ignore_change = False
        for page in self.pages.values():
            if hasattr(page, 'retranslate'):
                try:
                    page.retranslate()
                except Exception:
                    pass
        self.overlay_hint_label.setText(tr("security.locked_hint"))
        self.overlay_verify_btn.setText(tr("security.verify_button"))

    def _verify_identity(self):
        if time.time() < self._unlocked_until:
            return True
        methods = self.auth.get_enabled_methods()
        if not methods:
            QMessageBox.warning(self, tr("common.warning"), "没有可用的验证方式")
            return False
        dialog = DeleteAuthDialog(self, self.auth, methods)
        if dialog.exec_() == QDialog.Accepted:
            self._unlocked_until = time.time() + UNLOCK_TTL_SECONDS
            return True
        return False

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

    def toggle_secure_delete(self, state):
        enabled = (state == Qt.Checked)
        self.auth.settings_dict['secure_delete'] = enabled
        self.auth._save()
        self.storage.log(f"安全擦除: {'启用' if enabled else '禁用'}")

    def toggle_crash_report(self, state):
        enabled = (state == Qt.Checked)
        self.auth.settings_dict['crash_report_enabled'] = enabled
        self.auth._save()
        self.storage.log(f"崩溃报告: {'启用' if enabled else '禁用'}")

    def toggle_context_menu(self, enabled):
        from context_menu import register_context_menu, unregister_context_menu
        if enabled:
            ok, msg = register_context_menu()
        else:
            ok, msg = unregister_context_menu()
        if not ok:
            QMessageBox.warning(self, tr("common.error"), msg)
            try:
                page = self.pages.get('appearance')
                if page and hasattr(page, 'context_menu_cb'):
                    page.context_menu_cb.blockSignals(True)
                    page.context_menu_cb.setChecked(not enabled)
                    page.context_menu_cb.blockSignals(False)
            except Exception:
                pass
        else:
            self.storage.log(f"右键菜单: {'启用' if enabled else '禁用'}")

    def generate_recovery(self):
        try:
            if not self._verify_identity():
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
                    path, _ = QFileDialog.getSaveFileName(
                        self, "保存恢复代码", "recovery_code.txt", "Text Files (*.txt)")
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

    def export_vault_backup(self):
        if not self._verify_identity():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出保险库", "SecureVault_Backup.vaultbk",
            "SecureVault Backup (*.vaultbk)")
        if not path:
            return
        if not path.lower().endswith('.vaultbk'):
            path += '.vaultbk'

        password, ok = QInputDialog.getText(
            self, "备份密码",
            "输入备份密码（至少 8 位，用于跨设备迁移）：",
            QLineEdit.Password)
        if not ok:
            return
        if len(password) < 8:
            QMessageBox.warning(self, tr("common.error"), "备份密码长度至少 8 位")
            return
        confirm, ok = QInputDialog.getText(
            self, "确认密码", "再次输入备份密码：", QLineEdit.Password)
        if not ok or confirm != password:
            QMessageBox.warning(self, tr("common.error"), "两次密码不一致")
            return

        try:
            auth_settings = self.auth.export_auth_settings()
            self.storage.export_vault(path, password, auth_settings=auth_settings)
            self.storage.log("导出保险库备份（含验证信息）")
            QMessageBox.information(self, tr("common.success"), f"备份已保存到：{path}")
        except Exception as e:
            QMessageBox.critical(self, tr("common.error"), f"导出失败：{e}")

    def import_vault_backup(self):
        if not self._verify_identity():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "导入保险库", "", "SecureVault Backup (*.vaultbk);;All Files (*.*)")
        if not path:
            return
        password, ok = QInputDialog.getText(
            self, "备份密码", "输入备份密码：", QLineEdit.Password)
        if not ok:
            return
        if not password:
            QMessageBox.warning(self, tr("common.error"), "备份密码不能为空")
            return
        try:
            result = self.storage.import_vault(path, password)
        except Exception as e:
            QMessageBox.critical(self, tr("common.error"), f"导入失败：{e}")
            return

        auth_settings = result.get('auth_settings') if isinstance(result, dict) else None
        if auth_settings:
            reply = QMessageBox.question(
                self, "恢复验证信息",
                "备份包中包含验证信息（密码 / 安全问题 / TOTP / 邮箱等）。\n\n"
                "是否使用备份中的配置覆盖当前验证方式？\n"
                "选择“否”仅导入文件，验证方式保持不变。",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    if self.auth.import_auth_settings(auth_settings):
                        self.storage.log("从备份恢复验证信息")
                        QMessageBox.information(
                            self, tr("common.success"),
                            "验证信息已从备份恢复。\n部分更改可能需要重新登录后完全生效。")
                        self._refresh_security_page()
                except Exception as e:
                    QMessageBox.warning(
                        self, tr("common.error"),
                        f"恢复验证信息失败：{e}\n文件已导入，但验证方式未变。")

        if self.parent_main:
            self.parent_main.load_files()
            self.parent_main.load_tags()
        self.storage.log("导入保险库备份")
        QMessageBox.information(self, tr("common.success"), "备份已合并到当前保险库")

    # ============================================================
    #  检查更新（不再弹窗，只操作 UpdatePage）
    # ============================================================
    def check_update(self):
        import updater

        update_page = self.pages.get('update')
        if update_page:
            update_page.hide_update_areas()
            update_page.set_result(tr("update.checking"), "#888888")
        QApplication.processEvents()

        try:
            data = updater.get_latest_release(timeout=15)
            latest = data.get('tag_name', '')
            self.storage.log(f"检查更新: 当前{VERSION}, 远程{latest}")

            if getattr(updater.SSLTrustState, 'degraded', False) and update_page:
                update_page.set_result(
                    "⚠ " + updater.SSLTrustState.degraded_reason, "#ffaa00")
                QApplication.processEvents()

            if updater.is_newer(latest):
                if update_page:
                    update_page.set_result(
                        f"{tr('update.new_available')}: {latest}", "#5a8cbf")
                    update_page.show_update_prompt(latest, data)
            else:
                if update_page:
                    update_page.set_result(
                        f"{tr('update.up_to_date')}（{VERSION}）", "#4caf50")
        except Exception as e:
            if update_page:
                update_page.set_result(f"{tr('common.error')}: {e}", "#ff4444")

    # ============================================================
    #  密码/邮箱等修改功能（未改动）
    # ============================================================
    def change_password(self):
        if not self._verify_identity(): return
        pw, ok = QInputDialog.getText(
            self, "修改密码",
            "输入新密码（至少 6 个字符，UTF-8 编码不超过 72 字节，支持大小写字母、数字、符号）：",
            QLineEdit.Password)
        if not ok: return
        if not (len(pw) >= 6 and len(pw.encode('utf-8')) <= 72):
            QMessageBox.warning(self, tr("common.error"), "密码长度必须为 至少 6 个字符，UTF-8 编码不超过 72 字节")
            return
        confirm, ok = QInputDialog.getText(self, "修改密码", "再次输入新密码：", QLineEdit.Password)
        if not ok or pw != confirm:
            QMessageBox.warning(self, tr("common.error"), "两次密码不一致"); return
        self.auth.set_password(pw)
        self.storage.log("修改密码")
        QMessageBox.information(self, tr("common.success"), "密码已更新")
        self._refresh_security_page()

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
        if any(len(answer.text().encode('utf-8')) > 72 for answer in (a1, a2, a3)):
            QMessageBox.warning(self, tr('common.error'), '答案的 UTF-8 编码不超过 72 字节')
            return
        self.auth.set_questions([(q1.text(), a1.text()), (q2.text(), a2.text()), (q3.text(), a3.text())])
        self.storage.log("修改安全问题")
        QMessageBox.information(self, tr("common.success"), "安全问题已更新")
        self._refresh_security_page()

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
                self._refresh_security_page()
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

        self.download_helper_btn = create_download_button(self)
        self.download_helper_btn.clicked.connect(self._download_email_helper)
        layout.addWidget(self.download_helper_btn)

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
        if not ok:
            return
        vc_clean = vc.strip()
        if not vc_clean.isascii() or not vc_clean.isdigit():
            QMessageBox.warning(self, tr("common.error"), "验证码应为 6 位数字")
            return
        if not secrets.compare_digest(vc_clean.encode('utf-8'),
                                      str(result).encode('utf-8')):
            QMessageBox.warning(self, tr("common.error"), "验证码错误")
            return
        self.auth.save_email_config(smtp.text(), port_i, sender.text(), pwd.text(), recv.text())
        self.storage.log("修改邮箱配置")
        QMessageBox.information(self, tr("common.success"), "邮箱配置已更新")
        self._refresh_security_page()

    def _download_email_helper(self):
        if self._email_downloader is None:
            self._email_downloader = EmailConfigHelperDownloader(self)
        self._email_downloader.start()

    def change_secret_dir(self):
        if not self._verify_identity():
            return

        current = self.storage.SECRET_DIR
        new_dir = QFileDialog.getExistingDirectory(self, "选择新的加密文件目录", current)
        if not new_dir:
            return
        new_dir = os.path.abspath(new_dir)

        if os.path.normcase(new_dir) == os.path.normcase(os.path.abspath(current)):
            QMessageBox.information(self, "提示", "路径未改变")
            return

        if _is_subpath(new_dir, current) or _is_subpath(current, new_dir):
            QMessageBox.warning(self, "错误", "新目录不能与当前目录相同或嵌套")
            return

        if os.path.exists(new_dir) and os.listdir(new_dir):
            QMessageBox.warning(self, "错误", f"目标目录不为空：\n{new_dir}")
            return

        try:
            total_needed = 0
            for entry in self.storage.index:
                for key in ('secret_path', 'user_path'):
                    p = entry.get(key)
                    if p and os.path.exists(p):
                        try:
                            total_needed += os.path.getsize(p)
                        except OSError:
                            pass
            for name in ('index.enc', 'index.enc.bak', 'securevault.log'):
                p = os.path.join(current, name)
                if os.path.exists(p):
                    try:
                        total_needed += os.path.getsize(p)
                    except OSError:
                        pass
            needed_with_margin = int(total_needed * 1.1)
            free = shutil.disk_usage(new_dir).free
            if free < needed_with_margin:
                QMessageBox.warning(
                    self, "磁盘空间不足",
                    f"目标目录剩余空间 {free / (1024*1024):.1f} MB\n"
                    f"预计需要 {needed_with_margin / (1024*1024):.1f} MB\n\n"
                    f"请清理空间后重试。")
                return
        except Exception as e:
            self.storage.log(f"磁盘空间检查失败（将继续迁移）: {e}")

        n = len(self.storage.index)
        file_count = 0
        for entry in self.storage.index:
            for key in ('secret_path', 'user_path'):
                p = entry.get(key)
                if p and os.path.exists(p):
                    file_count += 1
        reply = QMessageBox.question(
            self, "确认迁移",
            f"将把加密文件目录迁移到：\n{new_dir}\n\n"
            f"共 {n} 条记录（{file_count} 个文件）将被移动，完成后需要重启程序。是否继续？",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._do_migrate_secret_dir(current, new_dir)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "迁移失败",
                                 f"迁移过程中出错，已回滚到原目录：\n{e}")
            return
        QApplication.restoreOverrideCursor()

        self.storage.log(f"迁移加密文件目录到: {new_dir}")
        try:
            self.parent_main.load_files()
        except Exception:
            pass
        QMessageBox.information(
            self, "成功",
            f"加密文件目录已迁移到：\n{new_dir}\n\n请立即重启程序以完成迁移。")

    def _do_migrate_secret_dir(self, old_dir, new_dir):
        os.makedirs(new_dir, exist_ok=True)
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(new_dir, 2)
        except Exception:
            pass

        tasks = []
        for entry in self.storage.index:
            for key in ('secret_path', 'user_path'):
                old_path = entry.get(key)
                if not old_path or not os.path.exists(old_path):
                    continue
                if os.path.normcase(os.path.dirname(old_path)) == os.path.normcase(new_dir):
                    continue
                base = os.path.basename(old_path)
                new_path = os.path.join(new_dir, base)
                if os.path.exists(new_path):
                    stem, ext = os.path.splitext(base)
                    counter = 1
                    while os.path.exists(new_path):
                        new_path = os.path.join(new_dir, f"{stem}_{counter}{ext}")
                        counter += 1
                tasks.append((old_path, new_path, entry, key))

        orig_secret_dir = self.storage.SECRET_DIR
        orig_index_path = self.storage.INDEX_PATH
        orig_backup_path = self.storage.INDEX_BACKUP_PATH
        orig_log_path = self.storage.LOG_PATH
        orig_settings_dir = self.storage.settings.get_secret_dir()
        orig_entry_paths = []
        for entry in self.storage.index:
            for key in ('secret_path', 'user_path'):
                orig_entry_paths.append((entry, key, entry.get(key)))

        copied = []
        copied_aux = []
        failed_cleanup = []
        try:
            for old_path, new_path, entry, key in tasks:
                shutil.copy2(old_path, new_path)
                copied.append((old_path, new_path, entry, key))
            for name in ('index.enc', 'index.enc.bak', 'securevault.log'):
                src = os.path.join(old_dir, name)
                dst = os.path.join(new_dir, name)
                if os.path.exists(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
                    copied_aux.append(dst)
            self.storage.SECRET_DIR = new_dir
            self.storage.INDEX_PATH = os.path.join(new_dir, 'index.enc')
            self.storage.INDEX_BACKUP_PATH = os.path.join(new_dir, 'index.enc.bak')
            self.storage.LOG_PATH = os.path.join(new_dir, 'securevault.log')
            for _, new_path, entry, key in copied:
                entry[key] = new_path
            self.storage.settings.set_secret_dir(new_dir)
            self.storage._save_index()
        except Exception as e:
            self.storage.SECRET_DIR = orig_secret_dir
            self.storage.INDEX_PATH = orig_index_path
            self.storage.INDEX_BACKUP_PATH = orig_backup_path
            self.storage.LOG_PATH = orig_log_path
            self.storage.settings.set_secret_dir(orig_settings_dir)
            for entry, key, val in orig_entry_paths:
                entry[key] = val
            for _, new_path, _, _ in copied:
                try:
                    if os.path.exists(new_path):
                        os.remove(new_path)
                except OSError as ce:
                    failed_cleanup.append((new_path, str(ce)))
                    self.storage.log(f"迁移回滚清理失败: {new_path} ({ce})")
            for dst in copied_aux:
                try:
                    if os.path.exists(dst):
                        os.remove(dst)
                except OSError as ce:
                    failed_cleanup.append((dst, str(ce)))
                    self.storage.log(f"迁移回滚清理失败: {dst} ({ce})")
            if failed_cleanup:
                msg = f"{e}\n\n注意：新目录中有 {len(failed_cleanup)} 个文件未能清理，请手动检查：\n{new_dir}"
                raise RuntimeError(msg) from e
            raise

        for old_path, _, _, _ in copied:
            try:
                if os.path.normcase(os.path.dirname(old_path)) != os.path.normcase(new_dir):
                    os.remove(old_path)
            except OSError:
                pass

    def _refresh_security_page(self):
        page = self.pages.get('security')
        if page and hasattr(page, 'on_config_changed'):
            try:
                page.on_config_changed()
            except Exception:
                pass
