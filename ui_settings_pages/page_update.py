from PyQt5.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QProgressBar, QWidget, QMessageBox)
from PyQt5.QtCore import Qt
from i18n import tr
from constants import VERSION
from ui_settings_style import SettingsPage, make_page_title


def _fmt_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class UpdatePage(SettingsPage):
    def __init__(self, settings_dialog):
        super().__init__()
        self.settings_dialog = settings_dialog
        self._manager = None
        self._pending_release_data = None

        self.layout().addWidget(make_page_title(tr("update.title")))
        self.layout().addSpacing(40)

        self.current_label = QLabel(tr("update.current"))
        self.current_label.setStyleSheet("color: #888; font-size: 11pt;")
        self.current_label.setAlignment(Qt.AlignCenter)
        self.layout().addWidget(self.current_label)

        self.version_label = QLabel(VERSION)
        self.version_label.setStyleSheet("font-size: 40pt; font-weight: bold;")
        self.version_label.setAlignment(Qt.AlignCenter)
        self.layout().addWidget(self.version_label)

        self.layout().addSpacing(24)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.check_btn = QPushButton(tr("update.check"))
        self.check_btn.setFixedWidth(220)
        self.check_btn.setMinimumHeight(42)
        self.check_btn.clicked.connect(self.settings_dialog.check_update)
        btn_row.addWidget(self.check_btn)
        btn_row.addStretch()
        self.layout().addLayout(btn_row)

        self.result_label = QLabel("")
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("font-size: 11pt;")
        self.result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.layout().addWidget(self.result_label)

        self.prompt_area = self._build_prompt_area()
        self.layout().addWidget(self.prompt_area)
        self.prompt_area.setVisible(False)

        self.progress_area = self._build_progress_area()
        self.layout().addWidget(self.progress_area)
        self.progress_area.setVisible(False)

        self.layout().addStretch()

    def is_downloading(self):
        if self._manager is not None and self._manager.is_downloading():
            return True
        return False

    def _build_prompt_area(self):
        area = QWidget()
        layout = QVBoxLayout(area)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(12)

        self.prompt_label = QLabel("")
        self.prompt_label.setAlignment(Qt.AlignCenter)
        self.prompt_label.setWordWrap(True)
        self.prompt_label.setStyleSheet("font-size: 12pt; color: #5a8cbf;")
        layout.addWidget(self.prompt_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.download_confirm_btn = QPushButton(tr("update.download"))
        self.download_confirm_btn.setFixedWidth(180)
        self.download_confirm_btn.setMinimumHeight(38)
        self.download_confirm_btn.clicked.connect(self._on_download_confirm)
        btn_row.addWidget(self.download_confirm_btn)

        self.cancel_prompt_btn = QPushButton(tr("common.cancel"))
        self.cancel_prompt_btn.setFixedWidth(100)
        self.cancel_prompt_btn.setMinimumHeight(38)
        self.cancel_prompt_btn.clicked.connect(self._on_cancel_prompt)
        btn_row.addWidget(self.cancel_prompt_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)
        return area

    def _build_progress_area(self):
        area = QWidget()
        layout = QVBoxLayout(area)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(12)

        self.progress_label = QLabel("")
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setWordWrap(True)
        self.progress_label.setStyleSheet("font-size: 11pt; color: #888;")
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(20)
        self.progress_bar.setMinimumWidth(400)
        layout.addWidget(self.progress_bar, 0, Qt.AlignHCenter)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.cancel_download_btn = QPushButton(tr("common.cancel"))
        self.cancel_download_btn.setFixedWidth(120)
        self.cancel_download_btn.setMinimumHeight(36)
        self.cancel_download_btn.clicked.connect(self._on_cancel_download)
        btn_row.addWidget(self.cancel_download_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return area

    def attach_to_manager(self, manager):
        if self._manager is manager: return
        self.detach_from_manager()
        self._manager = manager
        try:
            manager.progress_changed.connect(self._on_manager_progress)
            manager.state_changed.connect(self._on_manager_state)
        except Exception:
            self._manager = None

    def detach_from_manager(self):
        if self._manager is not None:
            try: self._manager.progress_changed.disconnect(self._on_manager_progress)
            except (TypeError, RuntimeError): pass
            try: self._manager.state_changed.disconnect(self._on_manager_state)
            except (TypeError, RuntimeError): pass
        self._manager = None

    def sync_state(self):
        manager = self._manager
        if manager is not None and manager.is_downloading():
            self.prompt_area.setVisible(False)
            self.progress_area.setVisible(True)
            self.cancel_download_btn.setEnabled(True)
            self.cancel_download_btn.setText(tr("common.cancel"))
            done, total, source_name, speed = manager.get_last_progress()
            if done > 0 or total > 0:
                self._update_progress_display(done, total, source_name, speed)
            else:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
                self.progress_label.setText("正在准备下载...")
        elif self._pending_release_data is not None:
            self.progress_area.setVisible(False)
            self.prompt_area.setVisible(True)
        else:
            self.prompt_area.setVisible(False)
            self.progress_area.setVisible(False)

    def set_result(self, text, color=None):
        self.result_label.setText(text)
        if color: self.result_label.setStyleSheet(f"font-size: 11pt; color: {color};")
        else: self.result_label.setStyleSheet("font-size: 11pt;")

    def show_update_prompt(self, latest, release_data):
        self._pending_release_data = release_data
        self.prompt_label.setText(f"发现新版本：{latest}\n\n是否下载并更新？")
        self.prompt_area.setVisible(True)
        self.progress_area.setVisible(False)

    def hide_update_areas(self):
        self.prompt_area.setVisible(False)
        self.progress_area.setVisible(False)

    def _on_download_confirm(self):
        if self._pending_release_data is None: return
        manager = self._manager
        if manager is None:
            parent_main = getattr(self.settings_dialog, 'parent_main', None)
            if parent_main is not None:
                manager = getattr(parent_main, 'update_manager', None)
        if manager is None: return

        latest = self._pending_release_data.get('tag_name', '')
        if manager.start_download(self._pending_release_data, latest):
            self._pending_release_data = None
            self.prompt_area.setVisible(False)
            self.progress_area.setVisible(True)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_label.setText("正在准备下载...")
            self.cancel_download_btn.setEnabled(True)
            self.cancel_download_btn.setText(tr("common.cancel"))
        else:
            QMessageBox.warning(self, "更新", "无法开始下载更新，请稍后重试。")

    def _on_cancel_prompt(self):
        self._pending_release_data = None
        self.hide_update_areas()
        self.set_result(tr("update.up_to_date"), "#4caf50")

    def _on_cancel_download(self):
        self.cancel_download_btn.setEnabled(False)
        self.cancel_download_btn.setText("正在取消...")
        if self._manager is not None:
            self._manager.cancel()

    def _on_manager_progress(self, done, total, source_name, speed):
        if not self.progress_area.isVisible(): return
        self._update_progress_display(done, total, source_name, speed)

    def _on_manager_state(self, state):
        if state == 'idle':
            if self.progress_area.isVisible():
                self.progress_area.setVisible(False)
            self.cancel_download_btn.setEnabled(True)
            self.cancel_download_btn.setText(tr("common.cancel"))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_label.setText("")
            self._pending_release_data = None

    def _update_progress_display(self, done, total, source_name, speed):
        speed_str = f"{speed:.1f} KB/s" if speed > 0 else "计算中..."
        if total > 0:
            percent = int(done * 100 / total)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(percent)
            self.progress_label.setText(f"正在从 {source_name} 下载...\n{_fmt_size(done)} / {_fmt_size(total)}\n速度: {speed_str}")
        else:
            self.progress_bar.setRange(0, 0)
            self.progress_label.setText(f"正在从 {source_name} 下载...\n已下载: {_fmt_size(done)}\n速度: {speed_str}")

    def retranslate(self):
        self.current_label.setText(tr("update.current"))
        self.check_btn.setText(tr("update.check"))
        self.download_confirm_btn.setText(tr("update.download"))
        self.cancel_prompt_btn.setText(tr("common.cancel"))
        self.cancel_download_btn.setText(tr("common.cancel"))