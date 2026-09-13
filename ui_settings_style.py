"""设置界面统一样式和辅助控件。"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QFrame, QSizePolicy, QStackedWidget)
from PyQt5.QtCore import Qt


# ============ 侧边栏 ============
SIDEBAR_QSS_DARK = """
QListWidget {
    border: none;
    background: #1a1a1a;
    color: #c8c8c8;
    padding: 12px 8px;
    outline: none;
    font-size: 10pt;
}
QListWidget::item {
    padding: 10px 14px;
    margin: 3px 0;
    border-radius: 8px;
    color: #c8c8c8;
}
QListWidget::item:hover {
    background: #2a2a2a;
    color: #f0f0f0;
}
QListWidget::item:selected {
    background: #3a3a3a;
    color: #ffffff;
}
"""

SIDEBAR_QSS_LIGHT = """
QListWidget {
    border: none;
    background: #f0f0f0;
    color: #333333;
    padding: 12px 8px;
    outline: none;
    font-size: 10pt;
}
QListWidget::item {
    padding: 10px 14px;
    margin: 3px 0;
    border-radius: 8px;
    color: #333333;
}
QListWidget::item:hover {
    background: #e3e3e3;
    color: #000000;
}
QListWidget::item:selected {
    background: #d5d5d5;
    color: #000000;
}
"""


def get_sidebar_qss(theme):
    return SIDEBAR_QSS_DARK if theme == "暗黑" else SIDEBAR_QSS_LIGHT


# ============ 内容区 ============
CONTENT_QSS_DARK = """
QWidget#SettingsPage { background: #232323; }
QLabel#PageTitle {
    font-size: 16pt;
    font-weight: bold;
    color: #f0f0f0;
}
QLabel#SectionTitle {
    font-size: 10pt;
    font-weight: bold;
    color: #a8a8a8;
}
QWidget#Card { background: #2c2c2c; border-radius: 10px; }
QLabel#SettingLabel { color: #e0e0e0; font-size: 10pt; }
QLabel#ValueLabel { color: #e0e0e0; font-size: 10pt; }
QFrame#HLine { background: #383838; border: none; }
QPushButton#ActionBtn {
    background: transparent;
    color: #e0e0e0;
    text-align: left;
    padding: 10px 14px;
    border: none;
    border-radius: 6px;
    font-size: 10pt;
}
QPushButton#ActionBtn:hover { background: #3a3a3a; }
QCheckBox { color: #e0e0e0; font-size: 10pt; }
QComboBox {
    background: #3a3a3a;
    color: #f0f0f0;
    border: 1px solid #4a4a4a;
    border-radius: 6px;
    padding: 5px 10px;
    min-width: 120px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background: #3a3a3a;
    color: #f0f0f0;
    selection-background-color: #4a4a4a;
}
"""

CONTENT_QSS_LIGHT = """
QWidget#SettingsPage { background: #ffffff; }
QLabel#PageTitle {
    font-size: 16pt;
    font-weight: bold;
    color: #1a1a1a;
}
QLabel#SectionTitle {
    font-size: 10pt;
    font-weight: bold;
    color: #666666;
}
QWidget#Card { background: #f6f6f6; border-radius: 10px; }
QLabel#SettingLabel { color: #333333; font-size: 10pt; }
QLabel#ValueLabel { color: #333333; font-size: 10pt; }
QFrame#HLine { background: #e5e5e5; border: none; }
QPushButton#ActionBtn {
    background: transparent;
    color: #333333;
    text-align: left;
    padding: 10px 14px;
    border: none;
    border-radius: 6px;
    font-size: 10pt;
}
QPushButton#ActionBtn:hover { background: #e5e5e5; }
QCheckBox { color: #333333; font-size: 10pt; }
QComboBox {
    background: #ffffff;
    color: #1a1a1a;
    border: 1px solid #cccccc;
    border-radius: 6px;
    padding: 5px 10px;
    min-width: 120px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background: #ffffff;
    color: #1a1a1a;
    selection-background-color: #e0e0e0;
}
"""


def get_content_qss(theme):
    return CONTENT_QSS_DARK if theme == "暗黑" else CONTENT_QSS_LIGHT


# ============ 辅助控件 ============

class SettingsPage(QWidget):
    """所有设置页面的基类：统一背景、边距、间距。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(28, 22, 28, 22)
        self._layout.setSpacing(14)

    def layout(self):
        return self._layout


def make_page_title(text):
    label = QLabel(text)
    label.setObjectName("PageTitle")
    return label


def make_section_title(text):
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def make_card():
    """返回 (card_widget, card_layout)"""
    card = QWidget()
    card.setObjectName("Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(0)
    return card, layout


def make_hline():
    line = QFrame()
    line.setObjectName("HLine")
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Plain)
    line.setFixedHeight(1)
    return line


def make_setting_row(label_text, control_widget=None):
    """
    一行设置：左边文字，右边控件。
    返回 (row_widget, row_layout)。
    如果 control_widget 为 None，可以自己往 row_layout 里添加。
    """
    row = QWidget()
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(10, 8, 10, 8)
    row_layout.setSpacing(10)

    label = QLabel(label_text)
    label.setObjectName("SettingLabel")
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    row_layout.addWidget(label)

    if control_widget is not None:
        row_layout.addWidget(control_widget, 0, Qt.AlignRight)
    return row, row_layout


def make_action_button(text):
    btn = QPushButton(text)
    btn.setObjectName("ActionBtn")
    btn.setCursor(Qt.PointingHandCursor)
    return btn


# 需要从 PyQt5.QtWidgets 导入 QPushButton
from PyQt5.QtWidgets import QPushButton
