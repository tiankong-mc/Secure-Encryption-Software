from PyQt5.QtWidgets import (QComboBox, QCheckBox, QLabel, QPushButton,
                              QSizePolicy)
from PyQt5.QtCore import Qt
from i18n import tr
from ui_settings_style import (SettingsPage, make_page_title, make_section_title,
                                make_card, make_hline, make_setting_row)
from context_menu import is_context_menu_enabled


def _fmt_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ('B', 'KB', 'MB', 'GB', 'TB', 'PB'):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} EB"


class TipLabel(QLabel):
    """自适应高度的多行提示 label（同 page_security.py）。"""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setStyleSheet("color: #888; font-size: 9pt; padding: 4px 10px 8px 10px;")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)

    def _recalc_height(self):
        w = self.width()
        if w <= 0:
            return
        inner_width = max(80, w - 24)
        fm = self.fontMetrics()
        rect = fm.boundingRect(
            0, 0, inner_width, 100000,
            Qt.TextWordWrap | Qt.TextExpandTabs,
            self.text())
        needed = rect.height() + 16
        self.setMinimumHeight(needed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recalc_height()

    def showEvent(self, event):
        super().showEvent(event)
        self._recalc_height()

    def setText(self, text):
        super().setText(text)
        self._recalc_height()


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

        self.context_menu_tip = TipLabel(tr("appearance.context_menu_tip"))
        c2.addWidget(self.context_menu_tip)

        self.layout().addWidget(card2)

        # ---------- 存储统计 ----------
        self.section_storage = make_section_title(tr("appearance.section_storage"))
        self.layout().addWidget(self.section_storage)
        card3, c3 = make_card()

        self.storage_stats_label = QLabel("")
        self.storage_stats_label.setWordWrap(True)
        self.storage_stats_label.setStyleSheet("padding: 10px 12px; font-size: 10pt;")
        self.storage_stats_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.storage_stats_label.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        self.storage_stats_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        c3.addWidget(self.storage_stats_label)
        c3.addWidget(make_hline())

        self.refresh_stats_btn = QPushButton(tr("appearance.storage_refresh"))
        self.refresh_stats_btn.setMinimumWidth(80)
        self.refresh_stats_btn.clicked.connect(self.refresh_storage_stats)
        self.row_refresh_stats, _ = make_setting_row("", self.refresh_stats_btn)
        c3.addWidget(self.row_refresh_stats)

        self.layout().addWidget(card3)

        self.layout().addStretch()

        self.refresh_storage_stats()

    def on_theme(self, idx):
        theme = "暗黑" if idx == 1 else "明亮"
        self.settings_dialog.on_theme_changed(theme)

    def on_context_menu_toggled(self, state):
        enabled = (state == Qt.Checked)
        self.settings_dialog.toggle_context_menu(enabled)

    def refresh_storage_stats(self):
        try:
            stats = self.settings_dialog.storage.get_storage_statistics()
        except Exception as e:
            self.storage_stats_label.setText(f"{tr('common.error')}: {e}")
            return

        lines = []
        lines.append(f"{tr('appearance.stats_files')}: {stats['file_count']}")
        lines.append(f"{tr('appearance.stats_total_size')}: {_fmt_size(stats['total_size'])}")
        lines.append(f"{tr('appearance.stats_dir_size')}: {_fmt_size(stats['directory_size'])}")

        recent_text = str(stats['recent_30d'])
        if stats.get('estimated_time'):
            recent_text += f"  ({tr('appearance.stats_estimated')}: {stats['estimated_time']})"
        lines.append(f"{tr('appearance.stats_recent_30d')}: {recent_text}")

        tag_dist = stats.get('tag_distribution') or {}
        lines.append("")
        if tag_dist:
            lines.append(tr('appearance.stats_tags') + ":")
            for tag, count in list(tag_dist.items())[:5]:
                lines.append(f"  · {tag}: {count}")
            if len(tag_dist) > 5:
                lines.append(f"  … {tr('appearance.stats_more_tags').format(n=len(tag_dist) - 5)}")
        else:
            lines.append(tr('appearance.stats_no_tags'))

        self.storage_stats_label.setText("\n".join(lines))

    def retranslate(self):
        self.section_theme.setText(tr("appearance.theme"))
        self.section_integration.setText(tr("appearance.section_integration"))
        self.section_storage.setText(tr("appearance.section_storage"))
        self.context_menu_cb.setText(tr("appearance.context_menu_cb"))
        self.refresh_stats_btn.setText(tr("appearance.storage_refresh"))
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

        self.refresh_storage_stats()
