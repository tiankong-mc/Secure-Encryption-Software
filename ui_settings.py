import os, sys, shutil, secrets, threading
from io import BytesIO
import qrcode
import pyotp
from datetime import datetime
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QComboBox, QDialogButtonBox, QMessageBox,
                              QCheckBox, QGroupBox, QFileDialog, QInputDialog,
                              QApplication, QProgressDialog, QListWidget, QListWidgetItem,
                              QStackedWidget, QWidget)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap

from constants import VERSION, WEB_PORT, ISSUES_URL
from ui_utils import protect_window, apply_protection_to_all_windows
from ui_dialogs import DeleteAuthDialog
from i18n import tr
from ui_styles import DARK_STYLE, LIGHT_STYLE
from ui_settings_style import get_sidebar_qss, get_content_qss

from ui_settings_pages.page_security import SecurityPage
from ui_settings_pages.page_web import WebPage
from ui_settings_pages.page_appearance import AppearancePage
from ui_settings_pages.page_language import LanguagePage
from ui_settings_pages.page_update import UpdatePage
from ui_settings_pages.page_about import AboutPage


def _is_subpath(child, parent):
    try:
        child = os.path.normcase(os.path.abspath(child))
        parent = os.path.normcase(os.path.abspath(parent))
        if child == parent:
            return True
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


# ============================================================
#  后台下载线程
# ============================================================
class DownloadWorker(QThread):
    """在后台线程执行下载，避免阻塞主线程导致 UI 卡死。"""

    progress = pyqtSignal(int, int, str, float)   # (downloaded, total, source_name, speed_kbps)
    finished_ok = pyqtSignal(str)                  # dest_path
    failed = pyqtSignal(str)                       # error message

    def __init__(self, url, dest_path, parent=None):
        super().__init__(parent)
        self.url = url
        self.dest_path = dest_path
        self._cancel_event = threading.Event()

    def cancel(self):
        """请求取消。设置事件后，下载循环会在下一个 chunk 检查时立即退出。"""
        self._cancel_event.set()

    def run(self):
        import updater
        try:
            def on_progress(done, total, source_name, speed_kbps):
                if self._cancel_event.is_set():
                    return
                try:
                    self.progress.emit(int(done), int(total),
                                       str(source_name), float(speed_kbps))
                except RuntimeError:
                    # 接收方已销毁
                    pass

            updater.download_file(
                self.url, self.dest_path,
                progress_callback=on_progress,
                cancel_event=self._cancel_event)
            if self._cancel_event.is_set():
                self.failed.emit("__cancelled__")
            else:
                self.finished_ok.emit(self.dest_path)
        except KeyboardInterrupt:
            self.failed.emit("__cancelled__")
        except Exception as e:
            try:
                self.failed.emit(str(e))
            except RuntimeError:
                pass


class SettingsDialog(QDialog):
    def __init__(self, parent, auth_manager, is_recovery_login=False):
        super().__init__(parent)
        self.auth = auth_manager
        self.is_recovery_login = is_recovery_login
        self.parent_main = parent
        self.storage = parent.storage

        self._unlocked = bool(is_recovery_login)
        self._download_worker = None

        self.setWindowTitle(tr("settings.title"))
        self.setModal(False)
        self.resize(820, 580)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(180)
        self.sidebar.setFocusPolicy(Qt.NoFocus)
        main_layout.addWidget(self.sidebar)

        self.content_wrapper = QWidget()
        self.content_wrapper.setObjectName("SettingsPage")
        wrapper_layout = QVBoxLayout(self.content_wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Stack")
        wrapper_layout.addWidget(self.stack)

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

    # ---------- 关闭时清理下载线程 ----------
    def closeEvent(self, event):
        """
        关闭设置对话框前，必须先停掉下载线程。
        否则 QThread 在 C++ 对象已销毁的情况下仍在 emit 信号，
        会导致主程序崩溃。
        """
        self._stop_download_worker()
        super().closeEvent(event)

    def _stop_download_worker(self):
        """主动停止下载线程并等待其退出。"""
        worker = self._download_worker
        if worker is None:
            return
        self._download_worker = None

        # 1. 先断开所有信号，防止 closeEvent 过程中触发槽函数
        for sig in (worker.progress, worker.finished_ok, worker.failed):
            try:
                sig.disconnect()
            except Exception:
                pass

        # 2. 请求取消
        try:
            worker.cancel()
        except Exception:
            pass

        # 3. 等待线程真正结束（最多 5 秒）
        try:
            if worker.isRunning():
                if not worker.wait(5000):
                    # 5 秒还没退，强制终止（不优雅但避免崩溃）
                    worker.terminate()
                    worker.wait(1000)
        except Exception:
            pass

    # ---------- 样式 ----------
    def apply_style(self):
        theme = self.auth.settings_dict.get('theme', '明亮')
        base = DARK_STYLE if theme == "暗黑" else LIGHT_STYLE
        self.setStyleSheet(base)
        self.sidebar.setStyleSheet(get_sidebar_qss(theme))
        self.content_wrapper.setStyleSheet(get_content_qss(theme))

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
            item = QListWidgetItem("  " + tr(tk))
            item.setData(Qt.UserRole, key)
            item.setSizeHint(item.sizeHint().__class__(180, 42))
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
        if self._unlocked:
            return True
        methods = self.auth.get_enabled_methods()
        if not methods:
            QMessageBox.warning(self, tr("common.warning"), "没有可用的验证方式")
            return False
        dialog = DeleteAuthDialog(self, self.auth, methods)
        if dialog.exec_() == QDialog.Accepted:
            self._unlocked = True
            return True
        return False

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

    def toggle_secure_delete(self, state):
        enabled = (state == Qt.Checked)
        self.auth.settings_dict['secure_delete'] = enabled
        self.auth._save()
        self.storage.log(f"安全擦除: {'启用' if enabled else '禁用'}")

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

    # ---------- 恢复代码 ----------
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

    # ---------- 保险库备份 ----------
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
        try:
            result = self.storage.import_vault(path, password or None)
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

            if getattr(updater.SSLTrustState, 'degraded', False) and update_page:
                update_page.set_result(
                    "⚠ " + updater.SSLTrustState.degraded_reason, "#ffaa00")
                QApplication.processEvents()

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

    # ---------- 下载更新（后台线程） ----------
    def download_update(self, data):
        import updater

        try:
            if not getattr(sys, 'frozen', False):
                QMessageBox.warning(
                    self, tr("common.warning"),
                    "源码运行时不能自动替换程序，请到 GitHub 手动下载新版本。")
                return

            if self._download_worker is not None and self._download_worker.isRunning():
                QMessageBox.information(self, tr("common.info"), "已有下载任务正在进行中")
                return

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

            # 注意：不删除已有的 temp_path，让断点续传能继续
            # 如果上一轮下载已完成，会在 finished 时被替换掉
            if os.path.exists(temp_path):
                # 如果文件已存在但大小异常小，认为是脏数据，清掉
                try:
                    sz = os.path.getsize(temp_path)
                    if sz == 0:
                        os.remove(temp_path)
                except OSError:
                    pass

            progress = QProgressDialog("正在下载更新...", "取消", 0, 100, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            progress.setValue(0)
            progress.show()

            self._download_worker = DownloadWorker(url, temp_path, self)
            self._download_worker.progress.connect(
                lambda done, total, src, spd: self._on_download_progress(
                    progress, done, total, src, spd))
            self._download_worker.finished_ok.connect(
                lambda path: self._on_download_finished(
                    path, expected_sha, latest, progress))
            self._download_worker.failed.connect(
                lambda err: self._on_download_failed(err, progress))
            progress.canceled.connect(self._download_worker.cancel)
            self._download_worker.start()

        except Exception as e:
            QMessageBox.critical(self, tr("common.error"), f"更新失败: {e}")

    def _on_download_progress(self, progress, done, total, source_name, speed_kbps):
        if total:
            progress.setValue(int(done / total * 100))
        done_mb = done / 1024 / 1024
        total_mb = total / 1024 / 1024 if total else 0
        speed_str = f"{speed_kbps:.1f} KB/s" if speed_kbps > 0 else "计算中..."
        progress.setLabelText(
            f"正在从 {source_name} 下载...\n"
            f"{done_mb:.1f} MB / {total_mb:.1f} MB\n"
            f"速度: {speed_str}")

    def _on_download_finished(self, path, expected_sha, latest, progress):
        import updater
        import subprocess as sp

        progress.setValue(100)
        progress.close()

        if expected_sha:
            if not updater.verify_sha256(path, expected_sha):
                QMessageBox.critical(self, tr("common.error"), "SHA-256 校验失败")
                try: os.remove(path)
                except: pass
                self._cleanup_download_worker()
                return
        else:
            if QMessageBox.question(
                    self, tr("common.warning"),
                    "未提供 SHA-256，继续？",
                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                try: os.remove(path)
                except: pass
                self._cleanup_download_worker()
                return

        QMessageBox.information(
            self, "更新完成",
            f"新版本 {latest} 已下载并准备替换。\n\n"
            "请手动关闭本程序，然后双击运行 SecureVault.exe 启动新版本。")

        exe_dir = os.path.dirname(sys.executable)
        bat_path = updater.write_update_bat(exe_dir, path, sys.executable)
        sp.Popen([bat_path], creationflags=sp.CREATE_NEW_CONSOLE)
        self.storage.log("更新替换完成，用户手动启动")
        self._cleanup_download_worker()
        QApplication.quit()

    def _on_download_failed(self, err, progress):
        try:
            progress.close()
        except Exception:
            pass
        self._cleanup_download_worker()
        if err == "__cancelled__":
            try:
                QMessageBox.information(self, tr("common.info"), "已取消下载")
            except Exception:
                pass
        else:
            try:
                QMessageBox.critical(self, tr("common.error"), f"更新失败: {err}")
            except Exception:
                pass

    def _cleanup_download_worker(self):
        """下载线程结束后释放引用（不 wait，只断信号）。"""
        worker = self._download_worker
        if worker is None:
            return
        self._download_worker = None
        for sig in (worker.progress, worker.finished_ok, worker.failed):
            try:
                sig.disconnect()
            except Exception:
                pass

    # ---------- 修改验证信息 ----------
    def change_password(self):
        if not self._verify_identity(): return
        pw, ok = QInputDialog.getText(
            self, "修改密码",
            "输入新密码（6-8 位，支持大小写字母、数字、符号）：",
            QLineEdit.Password)
        if not ok: return
        if not (6 <= len(pw) <= 8):
            QMessageBox.warning(self, tr("common.error"), "密码长度必须为 6-8 位")
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
        if not ok or not secrets.compare_digest(vc.strip(), str(result)):
            QMessageBox.warning(self, tr("common.error"), "验证码错误"); return
        self.auth.save_email_config(smtp.text(), port_i, sender.text(), pwd.text(), recv.text())
        self.storage.log("修改邮箱配置")
        QMessageBox.information(self, tr("common.success"), "邮箱配置已更新")
        self._refresh_security_page()

    # ============================================================
    #  修改加密文件目录
    # ============================================================
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

        n = len(self.storage.index)
        reply = QMessageBox.question(
            self, "确认迁移",
            f"将把加密文件目录迁移到：\n{new_dir}\n\n"
            f"共 {n} 个文件将被移动，完成后需要重启程序。是否继续？",
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
        except Exception:
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
                except OSError:
                    pass
            for dst in copied_aux:
                try:
                    if os.path.exists(dst):
                        os.remove(dst)
                except OSError:
                    pass
            raise

        for old_path, _, _, _ in copied:
            try:
                if os.path.normcase(os.path.dirname(old_path)) != os.path.normcase(new_dir):
                    os.remove(old_path)
            except OSError:
                pass

    # ---------- 内部辅助 ----------
    def _refresh_security_page(self):
        page = self.pages.get('security')
        if page and hasattr(page, 'on_config_changed'):
            try:
                page.on_config_changed()
            except Exception:
                pass
