from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt
from i18n import tr
from constants import VERSION


class UpdatePage(QWidget):
    def __init__(self, settings_dialog):
        super().__init__()
        self.settings_dialog = settings_dialog
        layout = QVBoxLayout(self)
        title = QLabel(tr("update.title"))
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        layout.addWidget(title)

        layout.addSpacing(40)

        self.current_label = QLabel(tr("update.current"))
        self.current_label.setStyleSheet("color: #888;")
        self.current_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.current_label)

        self.version_label = QLabel(VERSION)
        self.version_label.setStyleSheet("font-size: 36pt; font-weight: bold;")
        self.version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.version_label)

        layout.addSpacing(30)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.check_btn = QPushButton(tr("update.check"))
        self.check_btn.setFixedWidth(200)
        self.check_btn.clicked.connect(self.settings_dialog.check_update)
        btn_row.addWidget(self.check_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 结果显示标签（放在按钮下方，页面内显示，不再弹窗）
        self.result_label = QLabel("")
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("font-size: 11pt;")
        self.result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.result_label)

        layout.addStretch()

    def set_result(self, text, color=None):
        """由 SettingsDialog.check_update 调用，显示检查结果。"""
        self.result_label.setText(text)
        if color:
            self.result_label.setStyleSheet(f"font-size: 11pt; color: {color};")
        else:
            self.result_label.setStyleSheet("font-size: 11pt;")

    def retranslate(self):
        self.current_label.setText(tr("update.current"))
        self.check_btn.setText(tr("update.check"))
