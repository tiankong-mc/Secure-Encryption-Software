from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox
from i18n import tr


class AppearancePage(QWidget):
    def __init__(self, settings_dialog):
        super().__init__()
        self.settings_dialog = settings_dialog
        layout = QVBoxLayout(self)
        title = QLabel(tr("appearance.title"))
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        layout.addWidget(title)

        row = QHBoxLayout()
        self.theme_label = QLabel(tr("appearance.theme"))
        row.addWidget(self.theme_label)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems([tr("appearance.theme_light"), tr("appearance.theme_dark")])
        cur = settings_dialog.auth.settings_dict.get('theme', '明亮')
        if cur == "暗黑":
            self.theme_combo.setCurrentIndex(1)
        self.theme_combo.currentIndexChanged.connect(self.on_theme)
        row.addWidget(self.theme_combo)
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()

    def on_theme(self, idx):
        theme = "暗黑" if idx == 1 else "明亮"
        self.settings_dialog.on_theme_changed(theme)

    def retranslate(self):
        self.theme_label.setText(tr("appearance.theme"))
        cur_idx = self.theme_combo.currentIndex()
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        self.theme_combo.addItems([tr("appearance.theme_light"), tr("appearance.theme_dark")])
        self.theme_combo.setCurrentIndex(cur_idx)
        self.theme_combo.blockSignals(False)
