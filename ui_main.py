import os
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                              QPushButton, QListWidget, QListWidgetItem, QLabel,
                              QMessageBox, QFileDialog, QDialog, QCheckBox,
                              QDialogButtonBox, QInputDialog, QAbstractItemView)
from PyQt5.QtCore import Qt

from constants import VERSION
from ui_styles import DARK_STYLE, LIGHT_STYLE
from ui_utils import protect_window
from ui_viewer import FileViewer
from ui_log import LogDialog
from ui_dialogs import AuthDialog, DeleteAuthDialog, UploadDialog
from ui_settings import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self, storage, auth, is_recovery_login=False):
        super().__init__()
        self.storage = storage
        self.auth = auth
        self.is_recovery_login = is_recovery_login
        self.current_tag = None
        self.screenshot_protection = self.auth.settings_dict.get('screenshot_protection', False)
        self.setWindowTitle(f"SecureVault {VERSION}")
        self.setGeometry(100, 100, 900, 600)
        self.initUI()
        self.load_files()
        theme = self.auth.settings_dict.get('theme', '明亮')
        self.apply_theme(theme)
        self.setAcceptDrops(True)
        self.apply_screenshot_protection()

    # ---------- 主题 / 截屏防护 ----------
    def apply_theme(self, theme):
        if theme == "暗黑":
            self.setStyleSheet(DARK_STYLE)
        else:
            self.setStyleSheet(LIGHT_STYLE)

    def apply_screenshot_protection(self):
        protect_window(self, self.screenshot_protection)

    # ---------- UI ----------
    def initUI(self):
        central = QWidget(); self.setCentralWidget(central)
        main_layout = QHBoxLayout()

        # ===== 左侧标签面板 =====
        left_panel = QWidget(); left_panel.setFixedWidth(200)
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("标签分类"))
        self.tag_list = QListWidget()
        self.tag_list.addItem("全部")
        self.tag_list.itemClicked.connect(self.on_tag_clicked)
        left_layout.addWidget(self.tag_list)
        tag_btn_layout = QHBoxLayout()
        add_tag_btn = QPushButton("+"); add_tag_btn.setToolTip("创建新标签")
        add_tag_btn.clicked.connect(self.create_tag)
        tag_btn_layout.addWidget(add_tag_btn)
        del_tag_btn = QPushButton("-"); del_tag_btn.setToolTip("删除选中标签")
        del_tag_btn.clicked.connect(self.delete_tag)
        tag_btn_layout.addWidget(del_tag_btn)
        left_layout.addLayout(tag_btn_layout)
        left_panel.setLayout(left_layout)
        main_layout.addWidget(left_panel)

        # ===== 右侧文件区 =====
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        top_bar = QHBoxLayout()
        self.upload_btn = QPushButton("上传加密")
        self.import_btn = QPushButton("导入加密文件")
        self.export_btn = QPushButton("导出解密文件")
        self.refresh_btn = QPushButton("刷新")
        self.settings_btn = QPushButton("设置")
        self.delete_btn = QPushButton("删除")
        self.log_btn = QPushButton("日志")
        top_bar.addWidget(self.upload_btn); top_bar.addWidget(self.import_btn)
        top_bar.addWidget(self.export_btn); top_bar.addWidget(self.refresh_btn)
        top_bar.addWidget(self.settings_btn); top_bar.addWidget(self.delete_btn)
        top_bar.addWidget(self.log_btn)
        right_layout.addLayout(top_bar)

        self.file_list = QListWidget()
        self.file_list.setDragEnabled(True)
        self.file_list.setAcceptDrops(True)
        self.file_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.file_list.itemDoubleClicked.connect(self.open_file)
        right_layout.addWidget(self.file_list)
        right_panel.setLayout(right_layout)
        main_layout.addWidget(right_panel)

        central.setLayout(main_layout)

        # ===== 信号 =====
        self.upload_btn.clicked.connect(self.upload_file)
        self.import_btn.clicked.connect(self.import_vault_file)
        self.export_btn.clicked.connect(self.export_decrypted_file)
        self.refresh_btn.clicked.connect(self.load_files)
        self.settings_btn.clicked.connect(self.open_settings)
        self.delete_btn.clicked.connect(self.delete_file)
        self.log_btn.clicked.connect(self.open_log)
        self.setAcceptDrops(True)

    # ---------- 日志窗口 ----------
    def open_log(self):
        dialog = LogDialog(self, self.storage)
        dialog.show()

    # ---------- 标签 ----------
    def load_tags(self):
        self.tag_list.clear(); self.tag_list.addItem("全部")
        for tag in self.storage.get_all_tags():
            self.tag_list.addItem(tag)
        if self.current_tag:
            items = self.tag_list.findItems(self.current_tag, Qt.MatchExactly)
            if items:
                self.tag_list.setCurrentItem(items[0])

    def on_tag_clicked(self, item):
        self.current_tag = None if item.text() == "全部" else item.text()
        self.load_files()

    def create_tag(self):
        tag, ok = QInputDialog.getText(self, "创建标签", "输入新标签名称：")
        if ok and tag and tag not in self.storage.get_all_tags():
            selected = self.file_list.currentItem()
            if selected:
                entry_id = selected.data(Qt.UserRole)
                self.storage.add_tag_to_entry(entry_id, tag)
                self.load_files(); self.load_tags()
                self.storage.log(f"创建标签: {tag}")
            else:
                QMessageBox.information(self, "提示", "请先选择一个文件来添加标签。")

    def delete_tag(self):
        current = self.tag_list.currentItem()
        if not current or current.text() == "全部":
            return
        tag = current.text()
        reply = QMessageBox.question(self, "确认", f"确定删除标签 '{tag}' 吗？",
                                      QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            for entry in self.storage.get_all_entries():
                if tag in entry.get('tags', []):
                    entry['tags'].remove(tag)
            self.storage._save_index()
            self.load_tags(); self.load_files()
            self.storage.log(f"删除标签: {tag}")

    # ---------- 拖拽上传 ----------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                self._do_upload(file_path)
        event.acceptProposedAction()

    def _do_upload(self, file_path):
        dialog = UploadDialog(self, file_path)
        if dialog.exec_():
            try:
                uid = self.storage.add_file(file_path, dialog.user_dest,
                                            dialog.is_advanced, dialog.second_methods)
                self.storage.log(f"加密文件: {os.path.basename(file_path)}")
                QMessageBox.information(self, "成功", f"文件已加密保存，ID: {uid}")
                self.load_files(); self.load_tags()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"加密失败: {e}")

    # ---------- 文件列表 ----------
    def load_files(self):
        self.file_list.clear()
        entries = self.storage.get_all_entries()
        if self.current_tag:
            entries = [e for e in entries if self.current_tag in e.get('tags', [])]
        for entry in entries:
            tags_str = "[" + ", ".join(entry.get('tags', [])) + "] " if entry.get('tags') else ""
            item_text = f"{tags_str}{entry['original_name']}  {'[高级]' if entry['is_advanced'] else ''}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, entry['id'])
            self.file_list.addItem(item)

    def upload_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择要加密的文件")
        if file_path:
            self._do_upload(file_path)

    # ---------- 导入加密文件 ----------
    def import_vault_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择要导入的 .vault 加密文件", "", "Vault Files (*.vault)")
        if not file_path:
            return
        is_advanced = QMessageBox.question(
            self, "高级文件", "是否标记为高级文件？",
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes
        second_methods = []
        if is_advanced:
            dialog = QDialog(self); dialog.setWindowTitle("选择二次验证方式")
            layout = QVBoxLayout()
            cb_totp = QCheckBox("TOTP"); cb_email = QCheckBox("邮箱")
            cb_question = QCheckBox("问题"); cb_password = QCheckBox("密码")
            layout.addWidget(cb_totp); layout.addWidget(cb_email)
            layout.addWidget(cb_question); layout.addWidget(cb_password)
            btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btn_box.accepted.connect(dialog.accept); btn_box.rejected.connect(dialog.reject)
            layout.addWidget(btn_box); dialog.setLayout(layout)
            if dialog.exec_() == QDialog.Accepted:
                if cb_totp.isChecked(): second_methods.append('totp')
                if cb_email.isChecked(): second_methods.append('email')
                if cb_question.isChecked(): second_methods.append('question')
                if cb_password.isChecked(): second_methods.append('password')
                if not second_methods:
                    QMessageBox.warning(self, "提示", "至少选一种"); return
        try:
            uid = self.storage.import_vault_file(file_path, is_advanced=is_advanced,
                                                  second_auth_methods=second_methods)
            self.storage.log(f"导入加密文件: {os.path.basename(file_path)}")
            QMessageBox.information(self, "成功", f"文件已导入，ID: {uid}")
            self.load_files(); self.load_tags()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败: {e}")

    # ---------- 导出解密 ----------
    def export_decrypted_file(self):
        current = self.file_list.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选择文件"); return
        entry_id = current.data(Qt.UserRole)
        entry = self.storage.get_entry_by_id(entry_id)
        if not entry:
            QMessageBox.warning(self, "错误", "记录不存在"); return

        if entry['is_advanced']:
            methods = entry['second_auth_methods']
            if not methods:
                QMessageBox.warning(self, "提示", "未设置二次验证"); return
            auth_dialog = AuthDialog(self, self.auth, methods, entry_id, self.storage)
            if auth_dialog.exec_() != QDialog.Accepted: return
        else:
            avail = self._get_available_auth_methods()
            if not avail:
                QMessageBox.warning(self, "提示", "无可用验证方式"); return
            auth_dialog = DeleteAuthDialog(self, self.auth, avail)
            if auth_dialog.exec_() != QDialog.Accepted: return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "导出解密文件", entry['original_name'], "All Files (*.*)")
        if not save_path:
            return
        try:
            data = self.storage.get_file_data(entry_id)
            with open(save_path, 'wb') as f:
                f.write(data)
            self.storage.log(f"解密导出文件: {entry['original_name']}")
            QMessageBox.information(self, "成功", f"导出到：{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {e}")

    # ---------- 打开文件 ----------
    def open_file(self, item):
        entry_id = item.data(Qt.UserRole)
        entry = self.storage.get_entry_by_id(entry_id)
        if not entry:
            return
        if entry['is_advanced']:
            methods = entry['second_auth_methods']
            if not methods:
                QMessageBox.warning(self, "提示", "未设置二次验证"); return
            auth_dialog = AuthDialog(self, self.auth, methods, entry_id, self.storage)
            if auth_dialog.exec_() != QDialog.Accepted:
                return
        try:
            data = self.storage.get_file_data(entry_id)
            viewer = FileViewer(self, data, entry['type'], entry['original_name'])
            viewer.setAttribute(Qt.WA_DeleteOnClose)
            viewer.show()
            self.storage.log(f"查看文件: {entry['original_name']}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开失败: {e}")

    # ---------- 设置 ----------
    def open_settings(self):
        dialog = SettingsDialog(self, self.auth, self.is_recovery_login)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()

    # ---------- 删除文件 ----------
    def delete_file(self):
        current = self.file_list.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选择文件"); return
        entry_id = current.data(Qt.UserRole)
        entry = self.storage.get_entry_by_id(entry_id)
        avail = self._get_available_auth_methods()
        if not avail:
            QMessageBox.warning(self, "提示", "无可用验证方式"); return
        auth_dialog = DeleteAuthDialog(self, self.auth, avail)
        if auth_dialog.exec_() != QDialog.Accepted:
            return
        reply = QMessageBox.question(self, "确认删除", "确定永久删除该文件？",
                                      QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                self.storage.remove_entry(entry_id, destroy=False)
                self.storage.log(f"删除文件: {entry['original_name']}")
                self.load_files()
                QMessageBox.information(self, "成功", "已删除")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败: {e}")

    # ---------- 获取已启用的验证方式 ----------
    def _get_available_auth_methods(self):
        """返回当前已配置且已启用的验证方式。"""
        return self.auth.get_enabled_methods()
