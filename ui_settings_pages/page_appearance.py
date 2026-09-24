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

        # ---------- 系统集成 ----------
        self.layout().addWidget(make_section_title("系统集成"))
        card2, c2 = make_card()

        self.context_menu_cb = QCheckBox("在文件上显示“加密该文件”")
        try:
            self.context_menu_cb.setChecked(is_context_menu_enabled())
        except Exception:
            self.context_menu_cb.setChecked(False)
        self.context_menu_cb.stateChanged.connect(self.on_context_menu_toggled)
        row2, _ = make_setting_row("资源管理器右键菜单", self.context_menu_cb)
        c2.addWidget(row2)
        c2.addWidget(make_hline())

        tip = QLabel("启用后，在 Windows 资源管理器中右键任意文件，\n"
                     "即可通过“加密该文件（SecureVault）”快速加密。")
        tip.setStyleSheet("color: #888; font-size: 9pt; padding: 8px 10px;")
        tip.setWordWrap(True)
        c2.addWidget(tip)

        self.layout().addWidget(card2)

        self.layout().addStretch()

    def on_theme(self, idx):
        theme = "暗黑" if idx == 1 else "明亮"
        self.settings_dialog.on_theme_changed(theme)

    def on_context_menu_toggled(self, state):
        enabled = (state == Qt.Checked)
        self.settings_dialog.toggle_context_menu(enabled)

    def retranslate(self):
        idx = self.theme_combo.currentIndex()
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        self.theme_combo.addItems([tr("appearance.theme_light"), tr("appearance.theme_dark")])
        self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.blockSignals(False)
