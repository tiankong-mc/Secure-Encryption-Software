from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt
from i18n import tr
from constants import VERSION
from ui_settings_style import SettingsPage, make_page_title


class UpdatePage(SettingsPage):
    def __init__(self, settings_dialog):
        super().__init__()
        self.settings_dialog = settings_dialog

        self.layout().addWidget(make_page_title(tr("update.title")))

        self.layout().addSpacing(40)

        self.current_label = QLabel(tr("update.current"))
        self.current_label.setStyleSheet("color: #888; font-size: 11pt;")
        self.current_label.setAlignment(Qt.AlignCenter)
        self.layout().addWidget(self.current_label)

        self.version_label = QLabel(VERSION)
        self.version_label.setStyleSheet("font-size: 40pt; font-weight: bold;")
        self.version_label.setAlignment(Qt.AlignCenter)
        self.layout().addWidget(self.version_label)

        self.layout().addSpacing(24)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.check_btn = QPushButton(tr("update.check"))
        self.check_btn.setFixedWidth(220)
        self.check_btn.setMinimumHeight(42)
        self.check_btn.clicked.connect(self.settings_dialog.check_update)
        btn_row.addWidget(self.check_btn)
        btn_row.addStretch()
        self.layout().addLayout(btn_row)

        self.result_label = QLabel("")
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("font-size: 11pt;")
        self.result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.layout().addWidget(self.result_label)

        self.layout().addStretch()

    def set_result(self, text, color=None):
        self.result_label.setText(text)
        if color:
            self.result_label.setStyleSheet(f"font-size: 11pt; color: {color};")
        else:
            self.result_label.setStyleSheet("font-size: 11pt;")

    def retranslate(self):
        self.current_label.setText(tr("update.current"))
        self.check_btn.setText(tr("update.check"))
