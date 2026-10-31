import os, time, re, tempfile
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QComboBox, QStackedWidget, QDialogButtonBox,
                              QMessageBox, QWidget, QCheckBox, QGroupBox, QFileDialog,
                              QApplication, QInputDialog)
from PyQt5.QtCore import Qt, QTimer
from auth_helpers import verify_email_code

def _method_has_data(auth_manager, method):
    if method == 'password': return bool(auth_manager.password_hash)
    if method == 'question': return bool(auth_manager.get_questions())
    if method == 'totp': return bool(auth_manager.totp_secret)
    if method == 'email': return bool(auth_manager.email_config)
    return False

def _filter_methods(auth_manager, methods):
    enabled = set(auth_manager.get_enabled_methods())
    return [m for m in methods if m in enabled and _method_has_data(auth_manager, m)]

class _BaseAuthDialog(QDialog):
    def __init__(self, parent, auth_manager, allowed_methods):
        super().__init__(parent)
        self.auth = auth_manager; self.allowed_methods = allowed_methods
        self.widgets = {}; self.stack = None; self.method_combo = None; self.btn_box = None
        self.email_code = None; self.email_code_time = 0
        self._lock_timer = None; self._lock_seconds = 0; self._lock_label = None

    def _setup_ui(self, prompt_text):
        layout = QVBoxLayout()
        if not self.allowed_methods:
            warn_label = QLabel("此操作当前没有可用的验证方式。\n\n请到「设置 → 安全」中配置并启用至少一种验证方式后再试。")
            warn_label.setWordWrap(True); warn_label.setStyleSheet("color: #ffaa00; padding: 12px; font-size: 10pt;")
            layout.addWidget(warn_label)
            self.stack = QStackedWidget(); layout.addWidget(self.stack)
            self.method_combo = QComboBox(); self.method_combo.setEnabled(False); layout.addWidget(self.method_combo)
            btn_row = QHBoxLayout()
            open_settings_btn = QPushButton("打开设置"); open_settings_btn.clicked.connect(self._open_settings_page)
            ok_btn = QPushButton("确定"); ok_btn.setEnabled(False)
            cancel_btn = QPushButton("取消"); cancel_btn.clicked.connect(self.reject)
            btn_row.addWidget(open_settings_btn); btn_row.addStretch(); btn_row.addWidget(ok_btn); btn_row.addWidget(cancel_btn)
            layout.addLayout(btn_row); self.btn_box = None; self.setLayout(layout); return

        layout.addWidget(QLabel(prompt_text))
        self.stack = QStackedWidget()
        for m in self.allowed_methods:
            if m == 'password': w = self.create_password_widget(); self.stack.addWidget(w); self.widgets['password'] = w
            elif m == 'question': w = self.create_question_widget(); self.stack.addWidget(w); self.widgets['question'] = w
            elif m == 'totp': w = self.create_totp_widget(); self.stack.addWidget(w); self.widgets['totp'] = w
            elif m == 'email': w = self.create_email_widget(); self.stack.addWidget(w); self.widgets['email'] = w
        layout.addWidget(self.stack)
        self.method_combo = QComboBox(); self.method_combo.addItems(self.widgets.keys()); self.method_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        layout.addWidget(self.method_combo)
        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_box.accepted.connect(self.accept); self.btn_box.rejected.connect(self.reject)
        layout.addWidget(self.btn_box); self.setLayout(layout)

    def _find_main_window(self):
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'open_settings'): return parent
            try: parent = parent.parent()
            except Exception: parent = None
        try:
            for w in QApplication.topLevelWidgets():
                if hasattr(w, 'open_settings') and w.isVisible(): return w
        except Exception: pass
        return None

    def _open_settings_page(self):
        try:
            parent = self._find_main_window()
            if parent is None: QMessageBox.information(self, "提示", "请手动打开「设置 → 安全」进行配置。"); return
            parent.open_settings()
            dlg = getattr(parent, '_settings_dialog', None)
            if dlg: dlg.sidebar.setCurrentRow(0)
            self.reject()
        except Exception as e: QMessageBox.warning(self, "错误", f"无法打开设置：{e}")

    def create_password_widget(self):
        w = QWidget(); l = QVBoxLayout()
        l.addWidget(QLabel("输入密码："))
        self.pw_input = QLineEdit(); self.pw_input.setEchoMode(QLineEdit.Password)
        l.addWidget(self.pw_input); w.setLayout(l); return w

    def create_question_widget(self):
        w = QWidget(); l = QVBoxLayout()
        l.addWidget(QLabel("选择安全问题："))
        self.question_combo = QComboBox(); self.question_combo.addItems(self.auth.get_questions())
        l.addWidget(self.question_combo); l.addWidget(QLabel("输入答案："))
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
        self.send_btn = QPushButton("发送验证码"); self.send_btn.clicked.connect(self.send_email_code)
        l.addWidget(self.send_btn); w.setLayout(l); return w

    def send_email_code(self):
        self.email_code = self.auth.send_verification_code()
        if self.email_code: self.email_code_time = time.time(); QMessageBox.information(self, "提示", "验证码已发送至您的邮箱")
        else: self.email_code_time = 0; QMessageBox.warning(self, "错误", "邮件发送失败，请检查配置")

    def _check_credentials(self):
        method = self.method_combo.currentText() if self.method_combo else ""
        if method == 'password': return self.auth.verify_password(self.pw_input.text())
        elif method == 'question': return self.auth.verify_question(self.question_combo.currentText(), self.answer_input.text())
        elif method == 'totp': return self.auth.verify_totp(self.totp_input.text(), domain='op')
        elif method == 'email':
            status, msg = verify_email_code(self.email_code_input.text(), self.email_code, self.email_code_time)
            if status in ('no_code', 'expired'):
                QMessageBox.warning(self, "提示", msg)
                if status == 'expired': self.email_code = None; self.email_code_time = 0
                return None
            return status == 'ok'
        return False

class DeleteAuthDialog(_BaseAuthDialog):
    def __init__(self, parent, auth_manager, allowed_methods):
        filtered = _filter_methods(auth_manager, allowed_methods)
        super().__init__(parent, auth_manager, filtered)
        self.setWindowTitle("身份验证"); self.setModal(True); self.resize(420, 360)
        self._setup_ui("请验证身份以继续操作：")
        if self.allowed_methods:
            layout = self.layout()
            self._lock_label = QLabel(""); self._lock_label.setAlignment(Qt.AlignCenter)
            self._lock_label.setStyleSheet("color: #ff6666; font-size: 11pt; padding: 6px; font-weight: bold;")
            self._lock_label.setWordWrap(True); self._lock_label.setVisible(False)
            layout.insertWidget(0, self._lock_label); self._apply_lock_if_needed()

    def _apply_lock_if_needed(self):
        remaining = self.auth.get_op_lock_remaining()
        if remaining > 0: self._apply_lock(remaining)

    def _apply_lock(self, seconds):
        self._lock_seconds = seconds
        if self.stack: self.stack.setEnabled(False)
        if self.method_combo: self.method_combo.setEnabled(False)
        if self.btn_box: self.btn_box.setEnabled(False)
        if self._lock_label: self._lock_label.setVisible(True)
        self._update_lock_label()
        if self._lock_timer: self._lock_timer.stop()
        self._lock_timer = QTimer(self); self._lock_timer.timeout.connect(self._on_lock_tick); self._lock_timer.start(1000)

    def _on_lock_tick(self):
        self._lock_seconds -= 1
        if self._lock_seconds <= 0:
            if self._lock_timer: self._lock_timer.stop(); self._lock_timer = None
            self._release_lock()
        else: self._update_lock_label()

    def _update_lock_label(self):
        if self._lock_label: self._lock_label.setText(f"错误次数过多，请等待 {self._lock_seconds} 秒后再试")

    def _release_lock(self):
        if self._lock_label: self._lock_label.setVisible(False)
        if self.stack: self.stack.setEnabled(True)
        if self.method_combo: self.method_combo.setEnabled(True)
        if self.btn_box: self.btn_box.setEnabled(True)

    def closeEvent(self, event):
        if self._lock_timer: self._lock_timer.stop(); self._lock_timer = None
        super().closeEvent(event)

    def accept(self):
        if not self.allowed_methods: super().reject(); return
        remaining = self.auth.get_op_lock_remaining()
        if remaining > 0: self._apply_lock(remaining); return
        result = self._check_credentials()
        if result is None: return
        if result: self.auth.reset_op_lock(); super().accept(); return
        fail_count, lock_seconds = self.auth.register_op_failure()
        if lock_seconds > 0:
            QMessageBox.warning(self, "验证失败", f"错误次数已达 {self.auth.OP_MAX_ATTEMPTS} 次，已锁定 {lock_seconds} 秒。")
            self._apply_lock(lock_seconds)
        else: QMessageBox.warning(self, "验证失败", f"失败 {fail_count} 次")

class AuthDialog(DeleteAuthDialog):
    def __init__(self, parent, auth_manager, allowed_methods, entry_id, storage, target_type='file'):
        self.entry_id = entry_id; self.storage = storage; self.target_type = target_type
        super().__init__(parent, auth_manager, allowed_methods)
        self.setWindowTitle("二次验证")

    def _has_usable_email(self):
        cfg = self.auth.email_config or {}
        if not all(cfg.get(k) for k in ('smtp_server', 'port', 'sender_email', 'password', 'receiver_email')): return False
        try: return 'email' in self.auth.get_enabled_methods()
        except Exception: return False

    def _close_and_quit(self):
        try: self.reject()
        except Exception: pass
        QTimer.singleShot(0, QApplication.quit)

    def _trigger_emergency_action(self):
        storage = self.storage
        parent_widget = self.parent() or self
        email_cfg = self.auth.email_config; to_email = email_cfg.get('receiver_email')
        files_to_send = []

        if self.target_type == 'file':
            entry = storage.get_entry_by_id(self.entry_id)
            if not entry: QMessageBox.critical(parent_widget, "错误", "找不到目标记录。"); return False
            vault_path = entry.get('secret_path')
            if not (vault_path and os.path.exists(vault_path)): QMessageBox.critical(parent_widget, "文件丢失", "目标文件已不存在。"); return False
            original_name = entry.get('original_name', 'file')
            safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '', original_name) or "Backup"
            if not safe_name.endswith('.vault'): safe_name += '.vault'
            files_to_send.append((vault_path, f"SecureVault_{safe_name}"))
            del_func = lambda: storage.remove_entry(self.entry_id, destroy=True)
            success_msg = "本地副本已删除。"
        else:
            folder_path = self.entry_id
            safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '', os.path.basename(folder_path)) or "Folder"
            zip_path = os.path.join(tempfile.gettempdir(), f"SecureVault_Folder_{safe_name}.zip")
            try:
                storage.export_folder_as_zip(folder_path, zip_path)
                files_to_send.append((zip_path, f"SecureVault_Folder_{safe_name}.zip"))
            except Exception as e: QMessageBox.critical(parent_widget, "打包失败", f"打包失败：{e}"); return False
            del_func = lambda: storage.delete_folder(folder_path)
            success_msg = "本地文件夹及内容已删除。"

        # 按产品设计：高级文件/文件夹验证失败 5 次将自动发送到绑定邮箱并删除本地副本，
        # 此行为是既定的安全策略，不提供“取消”选项。
        from backup import BackupManager
        try:
            storage.log(f"紧急处理：正在发送 {self.target_type} 到 {to_email}")
            BackupManager.send_multiple_vault_files(files_to_send, to_email, email_cfg)
        except Exception as e:
            storage.log(f"紧急处理：发送失败 {e}")
            if self.target_type == 'folder':
                try: os.remove(files_to_send[0][0])
                except Exception: pass
            QMessageBox.critical(parent_widget, "发送失败", f"发送失败：\n{e}\n\n本地数据保留，程序将进入锁定状态。")
            return False

        self.auth.reset_file_fail_count(self.entry_id)
        try:
            del_func()
            QMessageBox.information(parent_widget, "完成", f"已发送到：{to_email}\n{success_msg}\n程序退出。")
        except Exception as e:
            QMessageBox.warning(parent_widget, "删除失败", f"已发送，但本地删除失败：\n{e}")

        if self.target_type == 'folder':
            try: os.remove(files_to_send[0][0])
            except Exception: pass
        self._close_and_quit()
        return True

    def _lock_and_exit(self):
        """未配置邮箱（或发送失败）时：持久化锁定并退出程序。"""
        try:
            op_fail, lock_seconds = self.auth.register_op_failure()
            if lock_seconds <= 0:
                lock_seconds = self.auth.OP_BASE_LOCK
            self.auth.settings_dict['op_lock_until'] = int(time.time()) + lock_seconds
            self.auth._save()
            QMessageBox.warning(
                self, "验证失败",
                f"错误次数已达上限，已锁定 {lock_seconds} 秒。\n程序将退出。")
        except Exception:
            pass
        self._close_and_quit()

    def accept(self):
        if not self.allowed_methods: super().reject(); return
        remaining = self.auth.get_op_lock_remaining()
        if remaining > 0: self._apply_lock(remaining); return

        result = self._check_credentials()
        if result is None: return
        if result:
            self.auth.reset_op_lock()
            self.auth.reset_file_fail_count(self.entry_id)
            QDialog.accept(self)
            return

        fail_count = self.auth.register_file_failure(self.entry_id)

        # 达到高级文件失败上限：
        #   配置了可用邮箱 -> 自动发送到绑定邮箱 + 删除本地副本 + 退出程序
        #   未配置邮箱     -> 只锁定 + 退出程序
        if fail_count >= self.auth.FILE_MAX_ATTEMPTS:
            if self._has_usable_email():
                if self._trigger_emergency_action():
                    return
                # 发送失败：保留本地数据，锁定后退出
            self._lock_and_exit()
            return

        # 未达到上限：记录一次操作失败（用于全局锁定），并提示
        op_fail, lock_seconds = self.auth.register_op_failure()
        if lock_seconds > 0:
            QMessageBox.warning(self, "验证失败", f"错误次数已达上限，已锁定 {lock_seconds} 秒。")
            self._apply_lock(lock_seconds)
        else:
            QMessageBox.warning(self, "验证失败", f"失败 {fail_count} 次")

class UploadDialog(QDialog):
    def __init__(self, parent, file_path, folder_path=""):
        super().__init__(parent)
        self.file_path = file_path; self.folder_path = folder_path
        self.is_advanced = False; self.is_editable = False; self.second_methods = []; self.delete_source = False
        self.setWindowTitle("上传加密选项"); self.setModal(True); self.resize(420, 420)
        storage = getattr(parent, 'storage', None)
        can_edit = storage.is_text_file(os.path.basename(file_path)) if storage else False

        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"文件：{os.path.basename(file_path)}"))
        self.advanced_cb = QCheckBox("标记为高级文件（需二次验证）"); self.advanced_cb.toggled.connect(self._on_advanced_toggled); layout.addWidget(self.advanced_cb)
        self.edit_cb = QCheckBox("允许在软件内编辑（仅限文本类）"); self.edit_cb.setEnabled(can_edit)
        if not can_edit: self.edit_cb.setToolTip("此文件类型不支持在线编辑")
        self.edit_cb.toggled.connect(self._on_edit_toggled); layout.addWidget(self.edit_cb)
        self.delete_source_cb = QCheckBox("加密成功后删除原文件"); layout.addWidget(self.delete_source_cb)

        self.method_group = QGroupBox("二次验证方式"); self.method_group.setEnabled(False)
        ml = QVBoxLayout()
        self.totp_cb = QCheckBox("TOTP (Authenticator)"); self.email_cb = QCheckBox("邮箱验证码")
        self.question_cb = QCheckBox("安全问题"); self.password_cb = QCheckBox("密码")
        auth = getattr(parent, 'auth', None)
        enabled = set(auth.get_enabled_methods()) if auth else set()
        for method, checkbox in (('totp', self.totp_cb), ('email', self.email_cb), ('question', self.question_cb), ('password', self.password_cb)):
            checkbox.setEnabled(method in enabled)
            if method not in enabled: checkbox.setToolTip("此验证方式尚未配置或未启用")
        ml.addWidget(self.totp_cb); ml.addWidget(self.email_cb); ml.addWidget(self.question_cb); ml.addWidget(self.password_cb)
        self.method_group.setLayout(ml); layout.addWidget(self.method_group)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept); btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box); self.setLayout(layout)

    def _on_advanced_toggled(self, checked):
        if checked:
            self.edit_cb.blockSignals(True); self.edit_cb.setChecked(False); self.edit_cb.blockSignals(False); self.edit_cb.setEnabled(False)
        else:
            storage = getattr(self.parent(), 'storage', None)
            if storage and storage.is_text_file(os.path.basename(self.file_path)): self.edit_cb.setEnabled(True)
        self.method_group.setEnabled(checked)

    def _on_edit_toggled(self, checked):
        if checked:
            self.advanced_cb.blockSignals(True); self.advanced_cb.setChecked(False); self.advanced_cb.blockSignals(False); self.advanced_cb.setEnabled(False)
            self.method_group.setEnabled(True); self.method_group.setTitle("二次验证方式（编辑时需验证）")
        else:
            self.advanced_cb.setEnabled(True); self.method_group.setEnabled(False); self.method_group.setTitle("二次验证方式（高级文件时可用）")

    def accept(self):
        self.is_advanced = self.advanced_cb.isChecked(); self.is_editable = self.edit_cb.isChecked(); self.delete_source = self.delete_source_cb.isChecked()
        if self.is_advanced or self.is_editable:
            self.second_methods = []
            if self.totp_cb.isChecked(): self.second_methods.append('totp')
            if self.email_cb.isChecked(): self.second_methods.append('email')
            if self.question_cb.isChecked(): self.second_methods.append('question')
            if self.password_cb.isChecked(): self.second_methods.append('password')
            if not self.second_methods: QMessageBox.warning(self, "提示", "请至少选择一种二次验证方式"); return
        super().accept()

class CreateFolderDialog(QDialog):
    def __init__(self, parent, title="新建文件夹", folder_name="", is_advanced=False, methods=None):
        super().__init__(parent)
        self.setWindowTitle(title); self.setModal(True); self.resize(380, 350)
        self.is_advanced = is_advanced; self.second_methods = methods or []
        layout = QVBoxLayout()
        layout.addWidget(QLabel("文件夹名称："))
        self.name_input = QLineEdit(folder_name); layout.addWidget(self.name_input)
        self.advanced_cb = QCheckBox("设为高级文件夹（进入需二次验证）"); self.advanced_cb.setChecked(is_advanced); self.advanced_cb.toggled.connect(self._toggle_advanced); layout.addWidget(self.advanced_cb)
        self.method_group = QGroupBox("二次验证方式"); self.method_group.setEnabled(is_advanced)
        ml = QVBoxLayout()
        self.totp_cb = QCheckBox("TOTP (Authenticator)"); self.email_cb = QCheckBox("邮箱验证码")
        self.question_cb = QCheckBox("安全问题"); self.password_cb = QCheckBox("密码")
        auth = getattr(parent, 'auth', None)
        enabled = set(auth.get_enabled_methods()) if auth else set()
        for method, checkbox in (('totp', self.totp_cb), ('email', self.email_cb), ('question', self.question_cb), ('password', self.password_cb)):
            checkbox.setEnabled(method in enabled)
            if method in self.second_methods: checkbox.setChecked(True)
        ml.addWidget(self.totp_cb); ml.addWidget(self.email_cb); ml.addWidget(self.question_cb); ml.addWidget(self.password_cb)
        self.method_group.setLayout(ml); layout.addWidget(self.method_group)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept); btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box); self.setLayout(layout)

    def _toggle_advanced(self, checked): self.method_group.setEnabled(checked)

    def accept(self):
        name = self.name_input.text().strip()
        if not name: QMessageBox.warning(self, "提示", "名称不能为空"); return
        self.is_advanced = self.advanced_cb.isChecked()
        if self.is_advanced:
            self.second_methods = []
            if self.totp_cb.isChecked(): self.second_methods.append('totp')
            if self.email_cb.isChecked(): self.second_methods.append('email')
            if self.question_cb.isChecked(): self.second_methods.append('question')
            if self.password_cb.isChecked(): self.second_methods.append('password')
            if not self.second_methods: QMessageBox.warning(self, "提示", "高级文件夹必须至少选择一种验证方式"); return
        else: self.second_methods = []
        super().accept()