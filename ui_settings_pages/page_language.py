from PyQt5.QtWidgets import QComboBox, QPushButton, QFileDialog, QMessageBox
from i18n import tr, get_manager
from ui_settings_style import (SettingsPage, make_page_title, make_section_title,
                                make_card, make_hline, make_setting_row)


class LanguagePage(SettingsPage):
    def __init__(self, settings_dialog):
        super().__init__()
        self.settings_dialog = settings_dialog
        self._codes = []

        self.layout().addWidget(make_page_title(tr("language.title")))

        self.layout().addWidget(make_section_title(tr("language.select")))
        card, c = make_card()

        self.lang_combo = QComboBox()
        self._reload_languages()
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)
        row, _ = make_setting_row(tr("language.select"), self.lang_combo)
        c.addWidget(row)
        c.addWidget(make_hline())

        self.import_btn = QPushButton(tr("language.import"))
        self.import_btn.clicked.connect(self.import_pack)
        row2, _ = make_setting_row(tr("language.import"), self.import_btn)
        c.addWidget(row2)

        self.layout().addWidget(card)
        self.layout().addStretch()

    def _reload_languages(self):
        m = get_manager()
        self.lang_combo.blockSignals(True)
        self.lang_combo.clear()
        self._codes = []
        if m:
            for code, name in m.available.items():
                self.lang_combo.addItem(name)
                self._codes.append(code)
            if m.current_code in self._codes:
                self.lang_combo.setCurrentIndex(self._codes.index(m.current_code))
        self.lang_combo.blockSignals(False)

    def on_language_changed(self, idx):
        if idx < 0 or idx >= len(self._codes):
            return
        code = self._codes[idx]
        m = get_manager()
        if m and code != m.current_code:
            m.load(code)
            self.settings_dialog.storage.log(f"切换语言为: {code}")
            QMessageBox.information(self, tr("common.info"), tr("language.restart_tip"))
            self.settings_dialog.retranslate_all()

    def import_pack(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("language.import"), "", "JSON (*.json)")
        if not path:
            return
        try:
            m = get_manager()
            code, name = m.import_pack(path)
            self.settings_dialog.storage.log(f"导入语言包: {code}")
            QMessageBox.information(self, tr("common.success"), tr("language.import_success") + name)
            self._reload_languages()
        except Exception as e:
            QMessageBox.warning(self, tr("common.error"), tr("language.import_failed") + str(e))

    def retranslate(self):
        self._reload_languages()
