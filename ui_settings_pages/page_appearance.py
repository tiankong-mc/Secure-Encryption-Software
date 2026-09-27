from PyQt5.QtWidgets import QComboBox, QCheckBox, QLabel
from PyQt5.QtCore import Qt
from i18n import tr
from ui_settings_style import (SettingsPage, make_page_title, make_section_title,
                                make_card, make_hline, make_setting_row)
from context_menu import is_context_menu_enabled


class AppearancePage(SettingsPage):
    def __init__(self, settings_dialog):
        super().__init__()
        self.settings_dialog = settings_dialog

        self.layout().addWidget(make_page_title(tr("appearance.title")))

        # ---------- 主题 ----------
        self.section_theme = make_section_title(tr("appearance.theme"))
        self.layout().addWidget(self.section_theme)
        card, c = make_card()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems([tr("appearance.theme_light"), tr("appearance.theme_dark")])
        if settings_dialog.auth.settings_dict.get('theme', '明亮') == "暗黑":
            self.theme_combo.setCurrentIndex(1)
        self.theme_combo.currentIndexChanged.connect(self.on_theme)
        self.row_theme, _ = make_setting_row(tr("appearance.theme"), self.theme_combo)
        c.addWidget(self.row_theme)
        self.layout().addWidget(card)

        # ---------- 系统集成 ----------
        self.section_integration = make_section_title(tr("appearance.section_integration"))
        self.layout().addWidget(self.section_integration)
        card2, c2 = make_card()

        self.context_menu_cb = QCheckBox(tr("appearance.context_menu_cb"))
        try:
            self.context_menu_cb.setChecked(is_context_menu_enabled())
        except Exception:
            self.context_menu_cb.setChecked(False)
        self.context_menu_cb.stateChanged.connect(self.on_context_menu_toggled)
        self.row_context_menu, _ = make_setting_row(
            tr("appearance.context_menu"), self.context_menu_cb)
        c2.addWidget(self.row_context_menu)
        c2.addWidget(make_hline())

        self.context_menu_tip = QLabel(tr("appearance.context_menu_tip"))
        self.context_menu_tip.setStyleSheet("color: #888; font-size: 9pt; padding: 8px 10px;")
        self.context_menu_tip.setWordWrap(True)
        c2.addWidget(self.context_menu_tip)

        self.layout().addWidget(card2)

        self.layout().addStretch()

    def on_theme(self, idx):
        theme = "暗黑" if idx == 1 else "明亮"
        self.settings_dialog.on_theme_changed(theme)

    def on_context_menu_toggled(self, state):
        enabled = (state == Qt.Checked)
        self.settings_dialog.toggle_context_menu(enabled)

    def retranslate(self):
        # 修复 #5：使用 findChildren(QLabel, "SettingLabel") 精确匹配 objectName，
        # 避免递归查找时误伤其他 QLabel。
        self.section_theme.setText(tr("appearance.theme"))
        self.section_integration.setText(tr("appearance.section_integration"))
        self.context_menu_cb.setText(tr("appearance.context_menu_cb"))
        self.context_menu_tip.setText(tr("appearance.context_menu_tip"))

        for child in self.row_theme.findChildren(QLabel, "SettingLabel"):
            child.setText(tr("appearance.theme"))
        for child in self.row_context_menu.findChildren(QLabel, "SettingLabel"):
            child.setText(tr("appearance.context_menu"))

        idx = self.theme_combo.currentIndex()
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        self.theme_combo.addItems([tr("appearance.theme_light"), tr("appearance.theme_dark")])
        self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.blockSignals(False)
