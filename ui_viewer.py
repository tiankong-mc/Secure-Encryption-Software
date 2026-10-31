import os, tempfile
from io import BytesIO
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QTextEdit, QMessageBox, QFileDialog)
from PyQt5.QtCore import Qt, QUrl, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PIL import Image, ImageQt
import docx, PyPDF2
from ui_utils import protect_window


def _auto_decode_text(data):
    if not data: return "", "utf-8", "\n"
    newline = "\r\n" if b"\r\n" in data else "\n"
    if data.startswith(b'\xef\xbb\xbf'): return data[3:].decode('utf-8', errors='replace'), "utf-8-sig", newline
    if data.startswith(b'\xff\xfe'): return data[2:].decode('utf-16-le', errors='replace'), "utf-16-le", newline
    if data.startswith(b'\xfe\xff'): return data[2:].decode('utf-16-be', errors='replace'), "utf-16-be", newline
    # 编码探测顺序：utf-8 → big5 → gb18030 → gbk（Big5 先于 gb18030，避免繁体被误判）
    for enc in ('utf-8', 'big5', 'gb18030', 'gbk'):
        try: return data.decode(enc), enc, newline
        except UnicodeDecodeError: pass
    return data.decode('utf-8', errors='replace'), "utf-8", newline


class FileViewer(QDialog):
    def __init__(self, parent, entry, storage, auth, data):
        super().__init__(parent)
        self.parent_window = parent
        self.entry = entry
        self.storage = storage
        self.auth = auth
        self.original_name = entry['original_name']
        self.file_data = data
        self.is_editing = False
        self.tmp_path = None
        self.player = None
        self.exported_tmp_files = []
        self._encoding = "utf-8"
        self._newline = "\n"
        self.setWindowTitle(f"查看: {self.original_name}")
        self.setModal(False)
        self.resize(700, 500)
        self.main_layout = QVBoxLayout()
        self.toolbar = QHBoxLayout()
        self.toolbar.addStretch()
        self.edit_btn = QPushButton("编辑"); self.edit_btn.setVisible(False); self.edit_btn.clicked.connect(self._start_edit)
        self.save_btn = QPushButton("保存"); self.save_btn.setVisible(False); self.save_btn.clicked.connect(self._save_edit)
        self.history_btn = QPushButton("历史版本"); self.history_btn.setVisible(False); self.history_btn.clicked.connect(self._show_history)
        self.toolbar.addWidget(self.edit_btn); self.toolbar.addWidget(self.history_btn); self.toolbar.addWidget(self.save_btn)
        self.main_layout.addLayout(self.toolbar)
        ftype = entry.get('type', 'other')
        if ftype == 'text':
            self.text_edit = QTextEdit()
            decoded, self._encoding, self._newline = _auto_decode_text(data)
            self.text_edit.setPlainText(decoded)
            self.text_edit.setReadOnly(True)
            self.main_layout.addWidget(self.text_edit)
            if entry.get('is_editable'):
                self.edit_btn.setVisible(True); self.history_btn.setVisible(True)
        elif ftype == 'image':
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                label = QLabel(); label.setPixmap(pixmap.scaled(600, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.main_layout.addWidget(label)
        elif ftype in ['video', 'audio']:
            try:
                ext = os.path.splitext(self.original_name)[1]
                fd, path = tempfile.mkstemp(suffix=ext); os.close(fd)
                with open(path, 'wb') as f: f.write(data)
                self.tmp_path = path
                self.player = QMediaPlayer()
                if ftype == 'video':
                    self.video_widget = QVideoWidget(); self.main_layout.addWidget(self.video_widget)
                    self.player.setVideoOutput(self.video_widget)
                self.player.setMedia(QMediaContent(QUrl.fromLocalFile(os.path.abspath(path))))
                cl = QHBoxLayout()
                pb = QPushButton("播放/暂停"); pb.clicked.connect(lambda: self.player.pause() if self.player.state() == QMediaPlayer.PlayingState else self.player.play())
                cl.addWidget(pb); self.main_layout.addLayout(cl)
                self.player.play()
            except Exception as e: self.main_layout.addWidget(QLabel(f"播放失败: {e}"))
        elif ftype == 'document':
            ext = os.path.splitext(self.original_name)[1].lower()
            text_content = ""
            try:
                if ext in ['.docx']:
                    for para in docx.Document(BytesIO(data)).paragraphs: text_content += para.text + "\n"
                elif ext in ['.pdf']:
                    for page in PyPDF2.PdfReader(BytesIO(data)).pages: text_content += (page.extract_text() or "") + "\n"
            except Exception as e: text_content = f"解析失败: {e}"
            te = QTextEdit(); te.setPlainText(text_content); te.setReadOnly(True)
            self.main_layout.addWidget(te)
        else:
            self.main_layout.addWidget(QLabel("不支持预览"))
        self.setLayout(self.main_layout)

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self.parent_window, 'screenshot_protection', False): protect_window(self, True)

    def _start_edit(self):
        methods = self.entry.get('second_auth_methods', [])
        enabled = set(self.auth.get_enabled_methods())
        valid_methods = [m for m in methods if m in enabled]
        if not valid_methods and enabled:
            valid_methods = list(enabled)  # 空方法列表时使用全局启用方法
        if not valid_methods:
            QMessageBox.warning(self, "提示", "此文件要求的验证方式当前均未启用。"); return
        from ui_dialogs import DeleteAuthDialog
        dialog = DeleteAuthDialog(self, self.auth, valid_methods)
        if dialog.exec_() == QDialog.Accepted:
            self.text_edit.setReadOnly(False)
            self.is_editing = True
            self.edit_btn.setVisible(False); self.history_btn.setVisible(False); self.save_btn.setVisible(True)
            self.setWindowTitle(f"编辑中: {self.original_name}")

    def _save_edit(self):
        text = self.text_edit.toPlainText()
        if self._newline == "\r\n": text = text.replace("\n", "\r\n")
        try:
            new_data = text.encode(self._encoding)
            if self._encoding == 'utf-8-sig': new_data = b'\xef\xbb\xbf' + new_data
            elif self._encoding == 'utf-16-le': new_data = b'\xff\xfe' + new_data
            elif self._encoding == 'utf-16-be': new_data = b'\xfe\xff' + new_data
        except Exception:
            new_data = text.encode('utf-8')
        try:
            self.storage.update_file_content(self.entry['id'], new_data)
            self.file_data = new_data
            QMessageBox.information(self, "成功", "文件已保存。")
            self.text_edit.setReadOnly(True)
            self.is_editing = False
            self.save_btn.setVisible(False); self.edit_btn.setVisible(True); self.history_btn.setVisible(True)
            self.setWindowTitle(f"查看: {self.original_name}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def _show_history(self):
        history = self.storage.get_file_history(self.entry['id'])
        if not history:
            QMessageBox.information(self, "提示", "暂无历史版本（仅保留3天内）。"); return
        from PyQt5.QtWidgets import QInputDialog
        import datetime
        items = [f"{datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')}" for ts, p in history]
        item, ok = QInputDialog.getItem(self, "历史版本", "选择要回滚的版本:", items, 0, False)
        if ok and item:
            idx = items.index(item)
            hist_path = history[idx][1]
            methods = self.entry.get('second_auth_methods', [])
            valid_methods = [m for m in methods if m in set(self.auth.get_enabled_methods())]
            if not valid_methods and self.auth.get_enabled_methods():
                valid_methods = self.auth.get_enabled_methods()
            if valid_methods:
                from ui_dialogs import DeleteAuthDialog
                dlg = DeleteAuthDialog(self, self.auth, valid_methods)
                if dlg.exec_() != QDialog.Accepted: return
            else:
                if not self.auth.get_enabled_methods():
                    QMessageBox.warning(self, "提示", "没有可用的验证方式"); return
            if self.is_editing:
                if QMessageBox.question(self, "警告", "回滚将放弃当前未保存的修改，是否继续？", QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes: return
                self.is_editing = False
                self.save_btn.setVisible(False); self.edit_btn.setVisible(True); self.history_btn.setVisible(True)
                self.text_edit.setReadOnly(True)
                self.setWindowTitle(f"查看: {self.original_name}")
            if QMessageBox.question(self, "确认", "回滚将覆盖当前内容，是否继续？", QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
                self.storage.rollback_file(self.entry['id'], hist_path)
                self.file_data = self.storage.get_file_data(self.entry['id'])
                decoded, self._encoding, self._newline = _auto_decode_text(self.file_data)
                self.text_edit.setPlainText(decoded)
                QMessageBox.information(self, "成功", "已回滚。")

    def closeEvent(self, event):
        if self.is_editing:
            reply = QMessageBox.question(self, "提示", "有未保存的修改，是否放弃编辑？", QMessageBox.Yes|QMessageBox.No)
            if reply == QMessageBox.No: event.ignore(); return
        if self.player: self.player.stop()
        if self.tmp_path and os.path.exists(self.tmp_path):
            try: os.remove(self.tmp_path)
            except OSError: pass
        event.accept()