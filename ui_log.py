from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QTextEdit, QDialogButtonBox, QMessageBox,
                              QFileDialog)
from PyQt5.QtGui import QFont


class LogDialog(QDialog):
    def __init__(self, parent, storage):
        super().__init__(parent)
        self.storage = storage
        self.setWindowTitle("日志")
        self.setModal(False)  # 非模态
        self.resize(700, 500)
        layout = QVBoxLayout()
        info_layout = QHBoxLayout()
        size = self.storage.get_log_size()
        self.size_label = QLabel(f"日志文件大小：{size} MB")
        info_layout.addWidget(self.size_label)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_log)
        info_layout.addWidget(self.refresh_btn)
        self.export_btn = QPushButton("导出为 .txt")
        self.export_btn.clicked.connect(self.export_log)
        info_layout.addWidget(self.export_btn)
        self.clear_btn = QPushButton("清空日志")
        self.clear_btn.clicked.connect(self.clear_log)
        info_layout.addWidget(self.clear_btn)
        layout.addLayout(info_layout)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_text)
        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        self.setLayout(layout)
        self.refresh_log()

    def refresh_log(self):
        content = self.storage.get_log_content()
        self.log_text.setPlainText(content)
        self.size_label.setText(f"日志文件大小：{self.storage.get_log_size()} MB")

    def export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出日志", "securevault_log.txt", "Text Files (*.txt)")
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.toPlainText())
                QMessageBox.information(self, "成功", f"日志已导出到：{path}")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"导出失败: {e}")

    def clear_log(self):
        reply = QMessageBox.question(self, "确认清空", "确定要清空所有日志吗？", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.storage.clear_log()
            self.refresh_log()
            QMessageBox.information(self, "提示", "日志已清空")
