from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt
from i18n import tr
from constants import ABOUT_TEXT


class AboutPage(QWidget):
    def __init__(self, settings_dialog):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel(tr("about.title"))
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        layout.addWidget(title)

        text = QLabel(ABOUT_TEXT)
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text.setStyleSheet("font-size: 11pt; line-height: 150%; padding: 10px;")
        layout.addWidget(text)
        layout.addStretch()

    def retranslate(self):
        pass
