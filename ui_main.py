import os
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                              QPushButton, QListWidget, QListWidgetItem, QLabel,
                              QMessageBox, QFileDialog, QDialog, QCheckBox,
                              QDialogButtonBox, QInputDialog, QAbstractItemView,
                              QTreeWidget, QTreeWidgetItem, QMenu, QLineEdit,
                              QStackedWidget)
from PyQt5.QtCore import Qt, QMimeData
from constants import VERSION
from ui_styles import DARK_STYLE, LIGHT_STYLE
from ui_utils import protect_window
from ui_viewer import FileViewer
from ui_log import LogDialog
from ui_dialogs import AuthDialog, DeleteAuthDialog, UploadDialog, CreateFolderDialog
from ui_settings import SettingsDialog
from update_manager import UpdateManager

MIME_TYPE = 'application/x-securevault-entry'


class EntryListWidget(QListWidget):
    def mimeData(self, items):
        mdata = QMimeData()
        if items:
            entry_id = items[0].data(Qt.UserRole)
            if entry_id: mdata.setData(MIME_TYPE, str(entry_id).encode('utf-8'))
        return mdata


class FolderTreeWidget(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = None
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHeaderHidden(True)
        self.setIndentation(15)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def _is_valid_drag(self, event):
        return event.mimeData().hasFormat(MIME_TYPE)

    def dragEnterEvent(self, event):
        if self._is_valid_drag(event): event.acceptProposedAction()
        else: event.ignore()

    def dragMoveEvent(self, event):
        if not self._is_valid_drag(event): event.ignore(); return
        if self.itemAt(event.pos()): event.acceptProposedAction()
        else: event.ignore()

    def dropEvent(self, event):
        if not self._is_valid_drag(event): return
        item = self.itemAt(event.pos())
        if not item or not self.main_window: return
        target_path = item.data(0, Qt.UserRole)
        try: entry_id = bytes(event.mimeData().data(MIME_TYPE)).decode('utf-8').strip()
        except Exception: entry_id = ''
        if not entry_id: return
        if self.main_window.storage.move_file_to_folder(entry_id, target_path):
            self.main_window.storage.log(f"移动文件到: {target_path}")
            self.main_window.load_files()
            event.acceptProposedAction()
        else:
            QMessageBox.warning(self, "失败", "移动文件失败")

    def _on_context_menu(self, pos):
        item = self.itemAt(pos)
        menu = QMenu(self)
        if item:
            path = item.data(0, Qt.UserRole)
            if path == "":
                menu.addAction("新建文件夹", lambda: self.main_window.create_folder(""))
            else:
                menu.addAction("新建子文件夹", lambda: self.main_window.create_folder(path))
                menu.addSeparator()
                menu.addAction("重命名", lambda: self.main_window.rename_folder(item))
                menu.addAction("删除文件夹", lambda: self.main_window.delete_folder(item))
        else:
            menu.addAction("新建文件夹", lambda: self.main_window.create_folder(""))
        menu.exec_(self.viewport().mapToGlobal(pos))


class MainWindow(QMainWindow):
    def __init__(self, storage, auth, is_recovery_login=False):
        super().__init__()
        self.storage = storage
        self.auth = auth
        self.is_recovery_login = is_recovery_login
        self.current_folder = ""
        self._last_folder = ""
        self.screenshot_protection = self.auth.settings_dict.get('screenshot_protection', False)
        self._settings_dialog = None
        self.update_manager = UpdateManager(self)
        self.setWindowTitle(f"SecureVault {VERSION}")
        self.setGeometry(100, 100, 900, 600)
        self.initUI()
        self.load_tree()
        self.load_files()
        theme = self.auth.settings_dict.get('theme', '明亮')
        self.apply_theme(theme)
        self.setAcceptDrops(True)
        self.apply_screenshot_protection()

    def apply_theme(self, theme):
        if theme == "暗黑": self.setStyleSheet(DARK_STYLE)
        else: self.setStyleSheet(LIGHT_STYLE)

    def apply_screenshot_protection(self):
        protect_window(self, self.screenshot_protection)

    def initUI(self):
        central = QWidget(); self.setCentralWidget(central)
        main_layout = QHBoxLayout()
        left_panel = QWidget(); left_panel.setFixedWidth(240)
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("文件库目录"))
        self.tree = FolderTreeWidget()
        self.tree.main_window = self
        self.tree.itemClicked.connect(self.on_tree_clicked)
        left_layout.addWidget(self.tree)
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
        self.delete_btn = QPushButton("删除文件")
        self.log_btn = QPushButton("日志")
        top_bar.addWidget(self.upload_btn); top_bar.addWidget(self.import_btn)
        top_bar.addWidget(self.export_btn); top_bar.addWidget(self.refresh_btn)
        top_bar.addWidget(self.settings_btn); top_bar.addWidget(self.delete_btn)
        top_bar.addWidget(self.log_btn)
        right_layout.addLayout(top_bar)
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索文件名...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.load_files)
        search_layout.addWidget(self.search_input)
        right_layout.addLayout(search_layout)
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
        self.import_btn.clicked.connect(self.import_file)
        self.export_btn.clicked.connect(self.export_decrypted_file)
        self.refresh_btn.clicked.connect(self.load_files)
        self.settings_btn.clicked.connect(self.open_settings)
        self.delete_btn.clicked.connect(self.delete_file)
        self.log_btn.clicked.connect(self.open_log)
        self.setAcceptDrops(True)

    def load_tree(self):
        self.tree.clear()
        root = QTreeWidgetItem(self.tree, ["保险库 (根目录)"])
        root.setData(0, Qt.UserRole, "")
        nodes = {"": root}
        all_folders = set(self.storage.folders.keys())
        for entry in self.storage.index:
            f_path = entry.get('folder_path', '')
            if f_path:
                parts = f_path.split('/')
                for i in range(1, len(parts)+1): all_folders.add('/'.join(parts[:i]))
        for f_path in sorted(all_folders):
            parts = f_path.split('/')
            name = parts[-1]
            parent_path = '/'.join(parts[:-1])
            if parent_path in nodes:
                node = QTreeWidgetItem(nodes[parent_path], [name])
                node.setData(0, Qt.UserRole, f_path)
                nodes[f_path] = node
        self.tree.expandAll()
        if self.current_folder in nodes: self.tree.setCurrentItem(nodes[self.current_folder])
        else:
            self.tree.setCurrentItem(root)
            self.current_folder = ""; self._last_folder = ""

    def on_tree_clicked(self, item, column):
        target_path = item.data(0, Qt.UserRole)
        if target_path == self.current_folder: return
        folder_info = self.storage.folders.get(target_path, {})
        if folder_info.get('is_advanced'):
            methods = folder_info.get('second_auth_methods', [])
            enabled = set(self.auth.get_enabled_methods())
            valid_methods = [m for m in methods if m in enabled]
            if not valid_methods:
                QMessageBox.warning(self, "提示", "此高级文件夹要求的验证方式当前均未启用。")
                self._restore_selection(); return
            dialog = AuthDialog(self, self.auth, valid_methods, target_path, self.storage, target_type='folder')
            if dialog.exec_() != QDialog.Accepted:
                self._restore_selection(); return
        self.current_folder = target_path
        self._last_folder = target_path
        self.load_files()

    def _restore_selection(self):
        from PyQt5.QtWidgets import QTreeWidgetItemIterator
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            if it.value().data(0, Qt.UserRole) == self._last_folder:
                self.tree.blockSignals(True)
                self.tree.setCurrentItem(it.value())
                self.tree.blockSignals(False)
                break
            it += 1

    def create_folder(self, parent_path):
        dialog = CreateFolderDialog(self, "新建文件夹")
        if dialog.exec_() == QDialog.Accepted:
            name = dialog.name_input.text().strip()
            new_path = f"{parent_path}/{name}" if parent_path else name
            if self.storage.create_folder(new_path, dialog.is_advanced, dialog.second_methods):
                self.storage.log(f"创建文件夹: {new_path}")
                self.load_tree()
            else:
                QMessageBox.warning(self, "错误", "文件夹已存在或名称无效")

    def rename_folder(self, item):
        old_path = item.data(0, Qt.UserRole)
        old_name = old_path.split('/')[-1]
        new_name, ok = QInputDialog.getText(self, "重命名", "输入新名称:", text=old_name)
        if ok and new_name and new_name != old_name:
            parent = '/'.join(old_path.split('/')[:-1])
            new_path = f"{parent}/{new_name}" if parent else new_name
            if self.storage.rename_folder(old_path, new_path):
                self.current_folder = new_path
                self._last_folder = new_path
                self.load_tree()
                self.load_files()

    def delete_folder(self, item):
        path = item.data(0, Qt.UserRole)
        methods = self.auth.get_enabled_methods()
        if not methods:
            QMessageBox.warning(self, "提示", "没有可用的验证方式，无法执行删除操作。"); return
        auth_dialog = DeleteAuthDialog(self, self.auth, methods)
        if auth_dialog.exec_() != QDialog.Accepted: return
        count = sum(1 for e in self.storage.index if e.get('folder_path') == path or e.get('folder_path','').startswith(path+'/'))
        msg = f"确定删除文件夹 '{path}' 吗？"
        if count > 0: msg = f"文件夹内还有 {count} 个文件，是否一并删除？"
        if QMessageBox.question(self, "确认删除", msg, QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
            secure_delete = bool(self.auth.settings_dict.get('secure_delete', False))
            self.storage.delete_folder(path, destroy=secure_delete)
            self.storage.log(f"删除文件夹: {path} (覆写={secure_delete})")
            if self.current_folder == path or self.current_folder.startswith(path + '/'):
                self.current_folder = ""; self._last_folder = ""
            self.load_tree()
            self.load_files()

    def load_files(self):
        self.file_list.clear()
        entries = self.storage.get_all_entries()
        entries = [e for e in entries if e.get('folder_path', '') == self.current_folder]
        keyword = self.search_input.text().strip().lower()
        if keyword: entries = [e for e in entries if keyword in (e.get('original_name', '') or '').lower()]
        for entry in entries:
            tags = []
            if entry.get('is_advanced'): tags.append("高级")
            if entry.get('is_editable'): tags.append("可编辑")
            tag_str = f"[{','.join(tags)}] " if tags else ""
            item = QListWidgetItem(f"{tag_str}{entry['original_name']}")
            item.setData(Qt.UserRole, entry['id'])
            self.file_list.addItem(item)

    def upload_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择要加密的文件")
        if file_path: self._do_upload(file_path)

    def _do_upload(self, file_path):
        dialog = UploadDialog(self, file_path, self.current_folder)
        if dialog.exec_():
            try:
                result = self.storage.add_file(
                    file_path, folder_path=self.current_folder,
                    is_advanced=dialog.is_advanced, is_editable=dialog.is_editable,
                    second_auth_methods=dialog.second_methods, delete_source=dialog.delete_source)
                if isinstance(result, dict) and result.get('delete_error'):
                    QMessageBox.warning(self, "部分成功", f"文件已加密保存。\n\n但删除原文件失败：\n{result['delete_error']}\n请手动处理。")
                else:
                    QMessageBox.information(self, "成功", "文件已加密保存")
                self.storage.log(f"加密文件: {os.path.basename(file_path)}")
                self.load_files()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"加密失败: {e}")

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入文件", "", "加密文件 (*.vault *.zip);;All Files (*.*)")
        if not path: return
        if path.lower().endswith('.zip'):
            name, ok = QInputDialog.getText(self, "导入文件夹", "输入恢复后的文件夹名称：", text="恢复的文件夹")
            if ok and name:
                try:
                    self.storage.import_zip_folder(path, name)
                    self.load_tree(); self.load_files()
                    QMessageBox.information(self, "成功", "文件夹恢复成功")
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"导入失败: {e}")
            return
        try:
            uid = self.storage.import_vault_file(path, target_folder=self.current_folder)
            QMessageBox.information(self, "成功", "文件已导入")
            self.load_files()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败: {e}")

    def open_file(self, item):
        entry_id = item.data(Qt.UserRole)
        entry = self.storage.get_entry_by_id(entry_id)
        if not entry: return
        if entry.get('is_advanced'):
            methods = entry.get('second_auth_methods', [])
            valid = [m for m in methods if m in set(self.auth.get_enabled_methods())]
            if not valid:
                QMessageBox.warning(self, "提示", "此文件要求的验证方式当前均未启用。"); return
            dialog = AuthDialog(self, self.auth, valid, entry_id, self.storage, target_type='file')
            if dialog.exec_() != QDialog.Accepted: return
        try:
            data = self.storage.get_file_data(entry_id)
            viewer = FileViewer(self, entry, self.storage, self.auth, data)
            viewer.setAttribute(Qt.WA_DeleteOnClose)
            viewer.show()
            self.storage.log(f"查看文件: {entry['original_name']}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开失败: {e}")

    def export_decrypted_file(self):
        current = self.file_list.currentItem()
        if not current: QMessageBox.warning(self, "提示", "请先选择文件"); return
        entry_id = current.data(Qt.UserRole)
        entry = self.storage.get_entry_by_id(entry_id)
        if not entry: return
        if entry.get('is_advanced'):
            methods = entry.get('second_auth_methods', [])
            valid = [m for m in methods if m in set(self.auth.get_enabled_methods())]
            if not valid:
                QMessageBox.warning(self, "提示", "此文件要求的验证方式未启用"); return
            dialog = AuthDialog(self, self.auth, valid, entry_id, self.storage, target_type='file')
            if dialog.exec_() != QDialog.Accepted: return
        save_path, _ = QFileDialog.getSaveFileName(self, "导出", entry['original_name'])
        if save_path:
            try:
                data = self.storage.get_file_data(entry_id)
                with open(save_path, 'wb') as f: f.write(data)
                QMessageBox.information(self, "成功", "导出成功")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出失败: {e}")

    def delete_file(self):
        current = self.file_list.currentItem()
        if not current: return
        entry_id = current.data(Qt.UserRole)
        entry = self.storage.get_entry_by_id(entry_id)
        if not entry: return
        methods = self.auth.get_enabled_methods()
        dialog = DeleteAuthDialog(self, self.auth, methods)
        if dialog.exec_() != QDialog.Accepted: return
        if QMessageBox.question(self, "确认删除", "确定永久删除该文件？", QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
            secure_delete = bool(self.auth.settings_dict.get('secure_delete', False))
            self.storage.remove_entry(entry_id, destroy=secure_delete)
            self.load_files()

    def show_file_context_menu(self, pos):
        item = self.file_list.itemAt(pos)
        if not item: return
        self.file_list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("打开", lambda: self.open_file(item))
        menu.addAction("导出解密", self.export_decrypted_file)
        menu.addSeparator()
        menu.addAction("删除文件", self.delete_file)
        menu.exec_(self.file_list.viewport().mapToGlobal(pos))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path): self._do_upload(file_path)
        event.acceptProposedAction()

    def open_log(self):
        LogDialog(self, self.storage).show()

    def open_settings(self):
        if self._settings_dialog is not None:
            try:
                if self._settings_dialog.isVisible():
                    self._settings_dialog.raise_()
                    self._settings_dialog.activateWindow()
                    return
            except RuntimeError: self._settings_dialog = None
        self._settings_dialog = SettingsDialog(self, self.auth, self.is_recovery_login)
        self._settings_dialog.setAttribute(Qt.WA_DeleteOnClose)
        self._settings_dialog.destroyed.connect(self._on_settings_dialog_destroyed)
        self._settings_dialog.show()

    def _on_settings_dialog_destroyed(self, obj=None):
        # 只有被销毁的确实是当前窗口时才清引用，避免旧窗口销毁清掉新窗口
        if obj is None or obj is self._settings_dialog:
            self._settings_dialog = None

    def closeEvent(self, event):
        # 取消并等待正在进行的更新下载，避免退出时 QThread 仍在运行
        try:
            if self.update_manager is not None:
                self.update_manager.cancel()
                self.update_manager.shutdown()
        except Exception: pass
        super().closeEvent(event)