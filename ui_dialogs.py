import os
import time
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QComboBox, QStackedWidget, QDialogButtonBox,
                              QMessageBox, QWidget, QCheckBox, QGroupBox, QFileDialog,
                              QApplication)
from PyQt5.QtCore import Qt, QTimer

from auth_helpers import verify_email_code


def _method_has_data(auth_manager, method):
    if method == 'password':
        return bool(auth_manager.password_hash)
    if method == 'question':
        return bool(auth_manager.get_questions())
    if method == 'totp':
        return bool(auth_manager.totp_secret)
    if method == 'email':
        return bool(auth_manager.email_config)
    return False


def _filter_methods(auth_manager, methods):
    enabled = set(auth_manager.get_enabled_methods())
    result = []
    for m in methods:
        if m not in enabled:
            continue
        if not _method_has_data(auth_manager, m):
            continue
        result.append(m)
    return result


class _BaseAuthDialog(QDialog):
    def __init__(self, parent, auth_manager, allowed_methods):
        super().__init__(parent)
        self.auth = auth_manager
        self.allowed_methods = allowed_methods
        self.widgets = {}
        self.stack = None
        self.method_combo = None
        self.btn_box = None
        self.email_code = None
        self.email_code_time = 0
        self._lock_timer = None
        self._lock_seconds = 0
        self._lock_label = None

    def _setup_ui(self, prompt_text):
        layout = QVBoxLayout()

        if not self.allowed_methods:
            warn_label = QLabel(
                "此操作当前没有可用的验证方式。\n\n"
                "请到「设置 → 安全」中配置并启用至少一种验证方式后再试。")
            warn_label.setWordWrap(True)
            warn_label.setStyleSheet("color: #ffaa00; padding: 12px; font-size: 10pt;")
            layout.addWidget(warn_label)

            self.stack = QStackedWidget()
            layout.addWidget(self.stack)
            self.method_combo = QComboBox()
            self.method_combo.setEnabled(False)
            layout.addWidget(self.method_combo)

            btn_row = QHBoxLayout()
            open_settings_btn = QPushButton("打开设置")
            open_settings_btn.clicked.connect(self._open_settings_page)

            ok_btn = QPushButton("确定")
            ok_btn.setEnabled(False)
            cancel_btn = QPushButton("取消")
            cancel_btn.clicked.connect(self.reject)

            btn_row.addWidget(open_settings_btn)
            btn_row.addStretch()
            btn_row.addWidget(ok_btn)
            btn_row.addWidget(cancel_btn)
            layout.addLayout(btn_row)

            self.btn_box = None
            self.setLayout(layout)
            return

        layout.addWidget(QLabel(prompt_text))

        self.stack = QStackedWidget()
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

    def _find_main_window(self):
        """
        修复 M4：优先从 parent 链查找带 open_settings 的窗口；
        找不到时回退到 QApplication.topLevelWidgets()。
        """
        # 1) parent 链
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'open_settings'):
                return parent
            try:
                parent = parent.parent()
            except Exception:
                parent = None

        # 2) 顶层窗口兜底
        try:
            for w in QApplication.topLevelWidgets():
                if hasattr(w, 'open_settings'):
                    try:
                        if w.isVisible():
                            return w
                    except Exception:
                        continue
        except Exception:
            pass

        return None

    def _open_settings_page(self):
        """尝试打开主窗口的设置对话框并跳到安全页。"""
        try:
            parent = self._find_main_window()
            if parent is None:
                QMessageBox.information(
                    self, "提示",
                    "请手动打开「设置 → 安全」进行配置。")
                return
            parent.open_settings()
            dlg = getattr(parent, '_settings_dialog', None)
            if dlg is not None:
                try:
                    dlg.sidebar.setCurrentRow(0)
                except Exception:
                    pass
            self.reject()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开设置：{e}")

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
        w.setLayout(l); return w

    def send_email_code(self):
        self.email_code = self.auth.send_verification_code()
        if self.email_code:
            self.email_code_time = time.time()
            QMessageBox.information(self, "提示", "验证码已发送至您的邮箱")
        else:
            self.email_code_time = 0
            QMessageBox.warning(self, "错误", "邮件发送失败，请检查配置")

    def _check_credentials(self):
        method = self.method_combo.currentText() if self.method_combo else ""
        if method == 'password':
            return self.auth.verify_password(self.pw_input.text())
        elif method == 'question':
            return self.auth.verify_question(self.question_combo.currentText(),
                                             self.answer_input.text())
        elif method == 'totp':
            return self.auth.verify_totp(self.totp_input.text())
        elif method == 'email':
            status, msg = verify_email_code(
                self.email_code_input.text(), self.email_code, self.email_code_time)
            if status in ('no_code', 'expired'):
                QMessageBox.warning(self, "提示", msg)
                if status == 'expired':
                    self.email_code = None
                    self.email_code_time = 0
                return None
            return status == 'ok'
        return False


class AuthDialog(_BaseAuthDialog):
    MAX_ATTEMPTS = 5

    def __init__(self, parent, auth_manager, allowed_methods, entry_id, storage):
        filtered = _filter_methods(auth_manager, allowed_methods)
        super().__init__(parent, auth_manager, filtered)
        self.entry_id = entry_id
        self.storage = storage
        self.setWindowTitle("二次验证")
        self.setModal(True)
        self.resize(400, 300)
        self.auth.reset_fail_count()
        self._setup_ui("请通过以下任意一种方式验证：")

    def accept(self):
        if not self.allowed_methods:
            super().reject()
            return

        result = self._check_credentials()
        if result is None:
            return
        if result:
            self.auth.reset_fail_count()
            self.storage.log(f"二次验证成功 (文件ID: {self.entry_id})")
            super().accept()
            return

        count = self.auth.increment_fail_count()
        self.storage.log(f"二次验证失败 (文件ID: {self.entry_id})")

        if count >= self.MAX_ATTEMPTS:
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

    def _has_usable_email(self):
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

    def _close_and_quit(self):
        try:
            self.reject()
        except Exception:
            pass
        QTimer.singleShot(0, QApplication.quit)

    def _trigger_emergency_action(self):
        storage = self.storage
        self.auth.reset_fail_count()
        parent_widget = self.parent()

        entry = storage.get_entry_by_id(self.entry_id)
        if not entry:
            storage.log("紧急处理：找不到目标记录，程序将退出")
            QMessageBox.critical(parent_widget, "错误",
                                 "找不到目标文件记录，程序将退出。")
            self._close_and_quit()
            return

        if not self._has_usable_email():
            storage.log("紧急处理：未配置或未启用邮箱验证方式，程序退出，本地文件保留")
            QMessageBox.critical(
                parent_widget, "安全退出",
                "错误次数过多，且未配置或未启用邮箱验证方式。\n\n"
                "为避免误删数据，本地加密文件将保留，程序将退出。")
            self._close_and_quit()
            return

        email_cfg = self.auth.email_config
        to_email = email_cfg.get('receiver_email')

        vault_path = entry.get('secret_path')
        user_path = entry.get('user_path')
        if not (vault_path and os.path.exists(vault_path)):
            if user_path and os.path.exists(user_path):
                vault_path = user_path
            else:
                storage.log(f"紧急处理：文件已不存在 ({entry['id']})，程序将退出")
                QMessageBox.critical(
                    parent_widget, "文件丢失",
                    "错误次数过多，但目标加密文件已不存在。\n程序将退出。")
                self._close_and_quit()
                return

        display_name = entry.get('original_name', 'file') + '.vault'
        files = [(vault_path, display_name)]

        from backup import BackupManager
        try:
            storage.log(f"紧急处理：正在发送文件 {entry.get('original_name')} 到 {to_email}")
            BackupManager.send_multiple_vault_files(files, to_email, email_cfg)
            storage.log("紧急处理：邮件发送成功")
        except Exception as e:
            storage.log(f"紧急处理：邮件发送失败 {e}")
            QMessageBox.critical(
                parent_widget, "发送失败",
                f"将该文件发送到邮箱失败：\n{e}\n\n"
                "为避免误删数据，本地加密文件将保留，程序将退出。")
            self._close_and_quit()
            return

        storage.log(f"紧急处理：删除本地文件 {entry.get('original_name')}")
        try:
            storage.remove_entry(self.entry_id, destroy=True)
            QMessageBox.information(
                parent_widget, "紧急处理完成",
                f"文件已发送到：{to_email}\n"
                f"本地加密副本已删除。\n\n程序将退出。")
        except Exception as e:
            storage.log(f"紧急处理：删除失败 {e}")
            QMessageBox.warning(
                parent_widget, "删除失败",
                f"文件已发送到：{to_email}\n\n"
                f"但本地文件删除失败：\n{e}\n\n"
                f"请手动清理后退出程序。")

        self._close_and_quit()


class DeleteAuthDialog(_BaseAuthDialog):
    def __init__(self, parent, auth_manager, allowed_methods):
        filtered = _filter_methods(auth_manager, allowed_methods)
        super().__init__(parent, auth_manager, filtered)
        self.setWindowTitle("身份验证")
        self.setModal(True)
        self.resize(420, 360)

        self._setup_ui("请验证身份以继续操作：")

        if self.allowed_methods:
            layout = self.layout()
            self._lock_label = QLabel("")
            self._lock_label.setAlignment(Qt.AlignCenter)
            self._lock_label.setStyleSheet(
                "color: #ff6666; font-size: 11pt; padding: 6px; font-weight: bold;")
            self._lock_label.setWordWrap(True)
            self._lock_label.setVisible(False)
            layout.insertWidget(0, self._lock_label)

            self._apply_lock_if_needed()

    def _apply_lock_if_needed(self):
        remaining = self.auth.get_op_lock_remaining()
        if remaining > 0:
            self._apply_lock(remaining)

    def _apply_lock(self, seconds):
        self._lock_seconds = seconds
        if self.stack is not None:
            self.stack.setEnabled(False)
        if self.method_combo is not None:
            self.method_combo.setEnabled(False)
        if self.btn_box is not None:
            self.btn_box.setEnabled(False)
        if self._lock_label is not None:
            self._lock_label.setVisible(True)
        self._update_lock_label()
        if self._lock_timer is not None:
            self._lock_timer.stop()
        self._lock_timer = QTimer(self)
        self._lock_timer.timeout.connect(self._on_lock_tick)
        self._lock_timer.start(1000)

    def _on_lock_tick(self):
        self._lock_seconds -= 1
        if self._lock_seconds <= 0:
            if self._lock_timer is not None:
                self._lock_timer.stop()
                self._lock_timer = None
            self._release_lock()
        else:
            self._update_lock_label()

    def _update_lock_label(self):
        if self._lock_label is not None:
            self._lock_label.setText(
                f"错误次数过多，请等待 {self._lock_seconds} 秒后再试")

    def _release_lock(self):
        if self._lock_label is not None:
            self._lock_label.setVisible(False)
        if self.stack is not None:
            self.stack.setEnabled(True)
        if self.method_combo is not None:
            self.method_combo.setEnabled(True)
        if self.btn_box is not None:
            self.btn_box.setEnabled(True)

    def closeEvent(self, event):
        if self._lock_timer is not None:
            self._lock_timer.stop()
            self._lock_timer = None
        super().closeEvent(event)

    def accept(self):
        if not self.allowed_methods:
            super().reject()
            return

        remaining = self.auth.get_op_lock_remaining()
        if remaining > 0:
            self._apply_lock(remaining)
            return

        result = self._check_credentials()
        if result is None:
            return

        if result:
            self.auth.reset_op_lock()
            super().accept()
            return

        fail_count, lock_seconds = self.auth.register_op_failure()
        if lock_seconds > 0:
            QMessageBox.warning(
                self, "验证失败",
                f"错误次数已达 {self.auth.OP_MAX_ATTEMPTS} 次，"
                f"已锁定 {lock_seconds} 秒。")
            self._apply_lock(lock_seconds)
        else:
            QMessageBox.warning(self, "验证失败", f"失败 {fail_count} 次")


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
