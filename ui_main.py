import os
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                              QPushButton, QListWidget, QListWidgetItem, QLabel,
                              QMessageBox, QFileDialog, QDialog, QCheckBox,
                              QDialogButtonBox, QInputDialog, QAbstractItemView,
                              QTreeWidget, QTreeWidgetItem, QMenu)
from PyQt5.QtCore import Qt, QMimeData

from constants import VERSION
from ui_styles import DARK_STYLE, LIGHT_STYLE
from ui_utils import protect_window
from ui_viewer import FileViewer
from ui_log import LogDialog
from ui_dialogs import AuthDialog, DeleteAuthDialog, UploadDialog
from ui_settings import SettingsDialog


MIME_TYPE = 'application/x-securevault-entry'


class EntryListWidget(QListWidget):
    def mimeData(self, items):
        mdata = QMimeData()
        if items:
            entry_id = items[0].data(Qt.UserRole)
            if entry_id:
                mdata.setData(MIME_TYPE, str(entry_id).encode('utf-8'))
        return mdata


class TagTreeWidget(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = None
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

    def _is_valid_drag(self, event):
        return event.mimeData().hasFormat(MIME_TYPE)

    def dragEnterEvent(self, event):
        if self._is_valid_drag(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not self._is_valid_drag(event):
            event.ignore()
            return
        item = self.itemAt(event.pos())
        if item and item.data(0, Qt.UserRole) != "全部":
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not self._is_valid_drag(event):
            return
        item = self.itemAt(event.pos())
        if not item or not self.main_window:
            return
        tag_path = item.data(0, Qt.UserRole)
        if not tag_path or tag_path == "全部":
            QMessageBox.information(
                self, "提示",
                "请先创建一个标签（点击左下角“+”），再把文件拖进去。")
            return
        try:
            entry_id = bytes(event.mimeData().data(MIME_TYPE)).decode('utf-8').strip()
        except Exception:
            entry_id = ''
        if not entry_id:
            return
        storage = self.main_window.storage
        if storage.add_tag_to_entry(entry_id, tag_path):
            storage.log(f"将文件添加到标签: {tag_path}")
            self.main_window.load_files()
            self.main_window.load_tags()
            QMessageBox.information(self, "成功", f"已添加到标签：{tag_path}")
        else:
            QMessageBox.information(self, "提示", f"文件已在标签 {tag_path} 中")
        event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self, storage, auth, is_recovery_login=False):
        super().__init__()
        self.storage = storage
        self.auth = auth
        self.is_recovery_login = is_recovery_login
        self.current_tag = None
        self.screenshot_protection = self.auth.settings_dict.get('screenshot_protection', False)
        self._settings_dialog = None
        self.setWindowTitle(f"SecureVault {VERSION}")
        self.setGeometry(100, 100, 900, 600)
        self.initUI()
        self.load_tags()
        self.load_files()
        theme = self.auth.settings_dict.get('theme', '明亮')
        self.apply_theme(theme)
        self.setAcceptDrops(True)
        self.apply_screenshot_protection()

    def apply_theme(self, theme):
        if theme == "暗黑":
            self.setStyleSheet(DARK_STYLE)
        else:
            self.setStyleSheet(LIGHT_STYLE)

    def apply_screenshot_protection(self):
        protect_window(self, self.screenshot_protection)

    def initUI(self):
        central = QWidget(); self.setCentralWidget(central)
        main_layout = QHBoxLayout()

        left_panel = QWidget(); left_panel.setFixedWidth(220)
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("标签分类"))

        self.tag_list = TagTreeWidget()
        self.tag_list.main_window = self
        self.tag_list.setHeaderHidden(True)
        self.tag_list.setIndentation(15)
        self.tag_list.itemClicked.connect(self.on_tag_clicked)
        self.tag_list.setStyleSheet("""
            QTreeWidget {
                background-color: #2b2b2b;
                border: 1px solid #555;
                color: #f0f0f0;
                outline: none;
            }
            QTreeWidget::item { height: 24px; }
            QTreeWidget::item:selected {
                background-color: #4a4a4a;
                color: #ffffff;
            }
            QTreeWidget::item:hover { background-color: #3c3c3c; }
        """)
        left_layout.addWidget(self.tag_list)

        tag_btn_layout = QHBoxLayout()
        add_tag_btn = QPushButton("+"); add_tag_btn.setToolTip("创建新标签")
        add_tag_btn.clicked.connect(self.create_tag)
        tag_btn_layout.addWidget(add_tag_btn)
        del_tag_btn = QPushButton("-"); del_tag_btn.setToolTip("删除选中标签")
        del_tag_btn.clicked.connect(self.delete_tag)
        tag_btn_layout.addWidget(del_tag_btn)
        left_layout.addLayout(tag_btn_layout)

        tip_label = QLabel("提示：把右侧文件拖到标签上即可归类")
        tip_label.setStyleSheet("color: #888; font-size: 8pt;")
        tip_label.setWordWrap(True)
        left_layout.addWidget(tip_label)

        left_panel.setLayout(left_layout)
        main_layout.addWidget(left_panel)

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

        self.file_list = EntryListWidget()
        self.file_list.setDragEnabled(True)
        self.file_list.setAcceptDrops(False)
        self.file_list.setDragDropMode(QAbstractItemView.DragOnly)
        self.file_list.itemDoubleClicked.connect(self.open_file)
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self.show_file_context_menu)
        right_layout.addWidget(self.file_list)
        right_panel.setLayout(right_layout)
        main_layout.addWidget(right_panel)

        central.setLayout(main_layout)

        self.upload_btn.clicked.connect(self.upload_file)
        self.import_btn.clicked.connect(self.import_vault_file)
        self.export_btn.clicked.connect(self.export_decrypted_file)
        self.refresh_btn.clicked.connect(self.load_files)
        self.settings_btn.clicked.connect(self.open_settings)
        self.delete_btn.clicked.connect(self.delete_file)
        self.log_btn.clicked.connect(self.open_log)
        self.setAcceptDrops(True)

    def open_log(self):
        dialog = LogDialog(self, self.storage)
        dialog.show()

    # ---------- 标签（树状） ----------
    def load_tags(self):
        self.tag_list.clear()
        root_item = QTreeWidgetItem(self.tag_list, ["全部"])
        root_item.setData(0, Qt.UserRole, "全部")
        tags = self.storage.get_all_tags()
        tag_nodes = {}
        for tag in tags:
            parts = tag.split('/')
            current_path = ""
            parent_item = root_item
            for part in parts:
                current_path = f"{current_path}/{part}" if current_path else part
                if current_path not in tag_nodes:
                    item = QTreeWidgetItem(parent_item, [part])
                    item.setData(0, Qt.UserRole, current_path)
                    tag_nodes[current_path] = item
                parent_item = tag_nodes[current_path]
        self.tag_list.expandAll()
        if self.current_tag and self.current_tag in tag_nodes:
            self.tag_list.setCurrentItem(tag_nodes[self.current_tag])
        else:
            self.tag_list.setCurrentItem(root_item)
            self.current_tag = None

    def on_tag_clicked(self, item, column):
        tag_path = item.data(0, Qt.UserRole)
        self.current_tag = None if tag_path == "全部" else tag_path
        self.load_files()

    def create_tag(self):
        item = self.tag_list.currentItem()
        if not item:
            return
        parent_path = item.data(0, Qt.UserRole)
        if parent_path == "全部":
            parent_path = ""
        tag, ok = QInputDialog.getText(
            self, "创建标签",
            "输入新标签名称（可再次选中后继续创建子标签）：")
        if ok and tag:
            tag = tag.strip()
            if not tag:
                return
            full_path = f"{parent_path}/{tag}" if parent_path else tag
            if full_path in self.storage.get_all_tags():
                QMessageBox.warning(self, "提示", f"标签 '{full_path}' 已存在")
                return
            self.storage.add_known_tag(full_path)
            self.load_tags()
            self.storage.log(f"创建标签: {full_path}")

    def delete_tag(self):
        item = self.tag_list.currentItem()
        if not item:
            return
        tag_path = item.data(0, Qt.UserRole)
        if tag_path == "全部":
            return
        reply = QMessageBox.question(
            self, "确认",
            f"确定删除标签 '{tag_path}' 及其所有子标签吗？\n（不会删除文件，只移除标签）",
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.storage.remove_known_tag(tag_path)
            for entry in self.storage.get_all_entries():
                tags = entry.get('tags', [])
                new_tags = [t for t in tags
                            if t != tag_path and not t.startswith(tag_path + "/")]
                if len(new_tags) != len(tags):
                    entry['tags'] = new_tags
            self.storage._save_index()
            self.current_tag = None
            self.load_tags()
            self.load_files()
            self.storage.log(f"删除标签: {tag_path}")

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
                result = self.storage.add_file(
                    file_path,
                    dialog.user_dest,
                    dialog.is_advanced,
                    dialog.second_methods,
                    delete_source=dialog.delete_source)
                if isinstance(result, dict):
                    uid = result.get('uid')
                    delete_error = result.get('delete_error')
                else:
                    uid = result
                    delete_error = None
                self.storage.log(f"加密文件: {os.path.basename(file_path)}")
                if delete_error:
                    QMessageBox.warning(
                        self, "部分成功",
                        f"文件已加密保存（ID: {uid}）。\n\n"
                        f"但删除原文件失败：\n{delete_error}\n\n"
                        f"原文件仍位于：\n{file_path}\n"
                        f"请手动确认是否删除。")
                else:
                    QMessageBox.information(self, "成功", f"文件已加密保存，ID: {uid}")
                self.load_files(); self.load_tags()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"加密失败: {e}")

    def load_files(self):
        self.file_list.clear()
        entries = self.storage.get_all_entries()
        if self.current_tag:
            entries = [
                e for e in entries
                if any(t == self.current_tag or t.startswith(self.current_tag + "/")
                       for t in e.get('tags', []))
            ]
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

    # ---------- 文件右键菜单 ----------
    def show_file_context_menu(self, pos):
        item = self.file_list.itemAt(pos)
        if not item:
            return
        self.file_list.setCurrentItem(item)
        entry_id = item.data(Qt.UserRole)
        menu = QMenu(self)
        open_action = menu.addAction("打开文件")
        open_action.triggered.connect(lambda: self.open_file(item))
        export_action = menu.addAction("导出解密")
        export_action.triggered.connect(self.export_decrypted_file)
        menu.addSeparator()
        add_menu = menu.addMenu("添加到标签")
        tags = self.storage.get_all_tags()
        if not tags:
            na = add_menu.addAction("（暂无标签，请先创建）")
            na.setEnabled(False)
        else:
            for tag in tags:
                act = add_menu.addAction(tag)
                act.triggered.connect(
                    lambda checked=False, t=tag, eid=entry_id:
                        self.add_entry_to_tag(eid, t))
        entry = self.storage.get_entry_by_id(entry_id)
        if entry and entry.get('tags'):
            remove_menu = menu.addMenu("从标签移除")
            for tag in list(entry.get('tags', [])):
                act = remove_menu.addAction(tag)
                act.triggered.connect(
                    lambda checked=False, t=tag, eid=entry_id:
                        self.remove_entry_from_tag(eid, t))
        menu.addSeparator()
        delete_action = menu.addAction("删除文件")
        delete_action.triggered.connect(self.delete_file)
        menu.exec_(self.file_list.viewport().mapToGlobal(pos))

    def add_entry_to_tag(self, entry_id, tag):
        if self.storage.add_tag_to_entry(entry_id, tag):
            self.storage.log(f"将文件添加到标签: {tag}")
            self.load_files()
            QMessageBox.information(self, "成功", f"已添加到标签：{tag}")
        else:
            QMessageBox.information(self, "提示", f"文件已在标签 {tag} 中")

    def remove_entry_from_tag(self, entry_id, tag):
        if self.storage.remove_tag_from_entry(entry_id, tag):
            self.storage.log(f"从标签移除文件: {tag}")
            self.load_files()

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

            configured = set(self.auth.get_configured_methods())
            enabled_set = set(self._get_available_auth_methods())
            for method, checkbox in (
                    ('totp', cb_totp), ('email', cb_email),
                    ('question', cb_question), ('password', cb_password)):
                if method in configured:
                    checkbox.setEnabled(True)
                    if method not in enabled_set:
                        checkbox.setToolTip(
                            "此方式当前未启用，勾选后需到“设置 → 安全”中启用才会生效")
                else:
                    checkbox.setEnabled(False)
                    checkbox.setToolTip("此验证方式尚未配置")

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

    def export_decrypted_file(self):
        current = self.file_list.currentItem()
        if not current:
            QMessageBox.warning(self, "提示", "请先选择文件"); return
        entry_id = current.data(Qt.UserRole)
        entry = self.storage.get_entry_by_id(entry_id)
        if not entry:
            QMessageBox.warning(self, "错误", "记录不存在"); return
        if entry['is_advanced']:
            methods = self._get_entry_auth_methods(entry)
            if not methods:
                # 修复 #4：区分"未设置"与"已设置但均未启用"
                if entry.get('second_auth_methods'):
                    QMessageBox.warning(
                        self, "提示",
                        "此文件要求的验证方式当前均未启用。\n"
                        "请在“设置 → 安全”中启用后重试。")
                else:
                    QMessageBox.warning(self, "提示", "此文件未设置二次验证")
                return
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

    def open_file(self, item):
        entry_id = item.data(Qt.UserRole)
        entry = self.storage.get_entry_by_id(entry_id)
        if not entry:
            return
        if entry['is_advanced']:
            methods = self._get_entry_auth_methods(entry)
            if not methods:
                # 修复 #4：区分"未设置"与"已设置但均未启用"
                if entry.get('second_auth_methods'):
                    QMessageBox.warning(
                        self, "提示",
                        "此文件要求的验证方式当前均未启用。\n"
                        "请在“设置 → 安全”中启用后重试。")
                else:
                    QMessageBox.warning(self, "提示", "此文件未设置二次验证")
                return
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

    def open_settings(self):
        if self._settings_dialog is not None:
            try:
                if self._settings_dialog.isVisible():
                    self._settings_dialog.raise_()
                    self._settings_dialog.activateWindow()
                    return
            except RuntimeError:
                self._settings_dialog = None
        self._settings_dialog = SettingsDialog(self, self.auth, self.is_recovery_login)
        self._settings_dialog.setAttribute(Qt.WA_DeleteOnClose)
        self._settings_dialog.destroyed.connect(
            lambda *_: setattr(self, '_settings_dialog', None))
        self._settings_dialog.show()

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

        secure_delete = bool(self.auth.settings_dict.get('secure_delete', False))
        if secure_delete:
            confirm_msg = ("确定永久删除该文件？\n\n"
                           "已启用「安全擦除」：将对数据进行多次覆写后删除，\n"
                           "速度较慢但难以被恢复工具还原。")
        else:
            confirm_msg = ("确定永久删除该文件？\n\n"
                           "提示：可在 设置 → 安全 中启用「安全擦除」以覆写数据。")

        reply = QMessageBox.question(self, "确认删除", confirm_msg,
                                      QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                self.storage.remove_entry(entry_id, destroy=secure_delete)
                self.storage.log(f"删除文件: {entry['original_name']} (覆写={secure_delete})")
                self.load_files()
                QMessageBox.information(self, "成功", "已删除")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败: {e}")

    def _get_available_auth_methods(self):
        return self.auth.get_enabled_methods()

    def _get_entry_auth_methods(self, entry):
        enabled = set(self._get_available_auth_methods())
        return [m for m in entry.get('second_auth_methods', []) if m in enabled]
