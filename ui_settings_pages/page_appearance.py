from PyQt5.QtWidgets import QComboBox
from i18n import tr
from ui_settings_style import (SettingsPage, make_page_title, make_section_title,
                                make_card, make_setting_row)


class AppearancePage(SettingsPage):
    def __init__(self, settings_dialog):
        super().__init__()
        self.settings_dialog = settings_dialog

        self.layout().addWidget(make_page_title(tr("appearance.title")))

        self.layout().addWidget(make_section_title(tr("appearance.theme")))
        card, c = make_card()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems([tr("appearance.theme_light"), tr("appearance.theme_dark")])
        if settings_dialog.auth.settings_dict.get('theme', '明亮') == "暗黑":
            self.theme_combo.setCurrentIndex(1)
        self.theme_combo.currentIndexChanged.connect(self.on_theme)
        row, _ = make_setting_row(tr("appearance.theme"), self.theme_combo)
        c.addWidget(row)
        self.layout().addWidget(card)

        self.layout().addStretch()

    def on_theme(self, idx):
        theme = "暗黑" if idx == 1 else "明亮"
        self.settings_dialog.on_theme_changed(theme)

    def retranslate(self):
        idx = self.theme_combo.currentIndex()
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        self.theme_combo.addItems([tr("appearance.theme_light"), tr("appearance.theme_dark")])
        self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.blockSignals(False)
