from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QScrollArea,
                              QFrame, QSizePolicy)
from PyQt5.QtCore import Qt
from i18n import tr
from constants import ABOUT_TEXT


class AboutPage(QWidget):
    def __init__(self, settings_dialog):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel(tr("about.title"))
        title.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 12px 12px 0 12px;")
        layout.addWidget(title)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(12, 12, 12, 12)

        self.text_label = QLabel(ABOUT_TEXT)
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.text_label.setStyleSheet("font-size: 11pt; line-height: 160%;")
        self.text_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        container_layout.addWidget(self.text_label)
        container_layout.addStretch()

        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

    def retranslate(self):
        # 内容来自 constants.ABOUT_TEXT，语言切换时若想动态更新可在此处理
        self.text_label.setText(ABOUT_TEXT)
