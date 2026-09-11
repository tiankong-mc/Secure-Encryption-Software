from PyQt5.QtWidgets import (QVBoxLayout, QLabel, QScrollArea, QFrame,
                              QSizePolicy, QWidget)
from PyQt5.QtCore import Qt
from i18n import tr
from constants import ABOUT_TEXT
from ui_settings_style import SettingsPage, make_page_title


class AboutPage(SettingsPage):
    def __init__(self, settings_dialog):
        super().__init__()

        self.layout().addWidget(make_page_title(tr("about.title")))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)

        self.text_label = QLabel(ABOUT_TEXT)
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.text_label.setStyleSheet("font-size: 11pt; line-height: 170%;")
        self.text_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        cl.addWidget(self.text_label)
        cl.addStretch()

        scroll.setWidget(container)
        self.layout().addWidget(scroll, 1)

    def retranslate(self):
        self.text_label.setText(ABOUT_TEXT)
