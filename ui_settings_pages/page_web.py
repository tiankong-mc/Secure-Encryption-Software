import os, socket
from io import BytesIO
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QMessageBox, QCheckBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
import qrcode
from i18n import tr
from constants import WEB_PORT
from ui_web import (start_web_server, stop_web_server, is_web_running,
                    is_https_enabled)
from ui_settings_style import (SettingsPage, make_page_title, make_section_title,
                                make_card, make_hline)


class WebPage(SettingsPage):
    def __init__(self, settings_dialog):
        super().__init__()
        self.settings_dialog = settings_dialog

        self.layout().addWidget(make_page_title(tr("web.title")))

        # ---- 状态卡片 ----
        self.section_status = make_section_title(tr("web.section_status"))
        self.layout().addWidget(self.section_status)
        card, c = make_card()

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 10, 10, 10)
        self.status_label = QLabel("")
        rl.addWidget(self.status_label)
        rl.addStretch()
        self.toggle_btn = QPushButton("")
        self.toggle_btn.setMinimumWidth(100)
        self.toggle_btn.setMinimumHeight(34)
        self.toggle_btn.clicked.connect(self.toggle_server)
        rl.addWidget(self.toggle_btn)
        c.addWidget(row)
        c.addWidget(make_hline())

        # HTTPS 复选框（在服务未运行时才能切换）
        self.https_cb = QCheckBox(tr("web.https_cb"))
        self.https_cb.setChecked(
            self.settings_dialog.auth.settings_dict.get('web_https_enabled', True))
        self.https_cb.stateChanged.connect(self.on_https_toggled)
        https_row = QWidget()
        h_lay = QHBoxLayout(https_row)
        h_lay.setContentsMargins(10, 8, 10, 8)
        h_lay.addWidget(self.https_cb)
        h_lay.addStretch()
        c.addWidget(https_row)

        self.https_tip = QLabel(tr("web.https_tip"))
        self.https_tip.setStyleSheet("color: #888; font-size: 9pt; padding: 4px 10px;")
        self.https_tip.setWordWrap(True)
        c.addWidget(self.https_tip)
        c.addWidget(make_hline())

        self.warning_label = QLabel(tr("web.http_warning"))
        self.warning_label.setStyleSheet("color: #ff6666; padding: 8px 10px;")
        self.warning_label.setWordWrap(True)
        c.addWidget(self.warning_label)
        self.layout().addWidget(card)

        # ---- 二维码卡片 ----
        self.section_qr = make_section_title(tr("web.qr_hint"))
        self.layout().addWidget(self.section_qr)
        self.qr_card, qc = make_card()

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setMinimumSize(260, 260)
        qc.addWidget(self.qr_label, 0, Qt.AlignHCenter)

        self.url_label = QLabel("")
        self.url_label.setAlignment(Qt.AlignCenter)
        self.url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.url_label.setStyleSheet("padding: 8px;")
        self.url_label.setWordWrap(True)
        qc.addWidget(self.url_label)

        self.loopback_warning = QLabel("")
        self.loopback_warning.setAlignment(Qt.AlignCenter)
        self.loopback_warning.setStyleSheet(
            "color: #ffaa00; padding: 4px 10px; font-size: 9pt;")
        self.loopback_warning.setWordWrap(True)
        self.loopback_warning.setVisible(False)
        qc.addWidget(self.loopback_warning)

        self.layout().addWidget(self.qr_card)
        self.layout().addStretch()

        self.refresh_state()

    def _get_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0)
            s.connect(('10.255.255.255', 1))
            ip = s.getsockname()[0]
            s.close()
            return ip, False
        except Exception:
            return '127.0.0.1', True

    def _make_qr_pixmap(self, url):
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=7,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format='PNG')
        pixmap = QPixmap()
        pixmap.loadFromData(buf.getvalue())
        return pixmap

    def on_https_toggled(self, state):
        """保存 HTTPS 首选项。运行时不允许切换。"""
        if is_web_running():
            # 服务运行中不允许切换
            self.https_cb.blockSignals(True)
            self.https_cb.setChecked(is_https_enabled())
            self.https_cb.blockSignals(False)
            QMessageBox.information(
                self, tr("common.info"),
                "请先停止 Web 服务，再修改 HTTPS 设置。")
            return
        enabled = (state == Qt.Checked)
        self.settings_dialog.auth.settings_dict['web_https_enabled'] = enabled
        self.settings_dialog.auth._save()
        self.settings_dialog.storage.log(
            f"Web HTTPS: {'启用' if enabled else '禁用'}")
        self.refresh_state()

    def toggle_server(self):
        if is_web_running():
            stop_web_server()
            self.settings_dialog.storage.log("停止移动端Web服务")
        else:
            enable_https = self.https_cb.isChecked()
            if start_web_server(self.settings_dialog.storage,
                                self.settings_dialog.auth,
                                enable_https=enable_https):
                self.settings_dialog.storage.log(
                    f"启动移动端Web服务 (HTTPS={'on' if enable_https else 'off'})")
            else:
                QMessageBox.warning(
                    self, tr("common.error"),
                    f"无法启动 Web 服务，请检查端口 {WEB_PORT} 是否被占用。")
            QTimer.singleShot(800, self.refresh_state)
        self.refresh_state()

    def refresh_state(self):
        running = is_web_running()
        if running:
            https_on = is_https_enabled()
            self.status_label.setText(tr("web.status") + tr("web.status_running"))
            self.status_label.setStyleSheet("color: #4caf50; font-size: 11pt;")
            self.toggle_btn.setText(tr("web.stop"))
            # 服务运行中不允许修改 HTTPS 开关
            self.https_cb.setEnabled(False)

            ip, is_loopback = self._get_ip()
            scheme = 'https' if https_on else 'http'
            url = f"{scheme}://{ip}:{WEB_PORT}"
            pixmap = self._make_qr_pixmap(url)
            self.qr_label.setPixmap(pixmap)
            self.url_label.setText(url)

            if is_loopback:
                self.url_label.setStyleSheet("padding: 8px; color: #ffaa00;")
                self.loopback_warning.setText(tr("web.loopback_warning"))
                self.loopback_warning.setVisible(True)
            else:
                self.url_label.setStyleSheet("padding: 8px; color: #5a8cbf;")
                self.loopback_warning.setVisible(False)

            # 更新提示：HTTPS 下的浏览器警告
            if https_on:
                self.warning_label.setText(tr("web.https_warning"))
                self.warning_label.setStyleSheet("color: #5a8cbf; padding: 8px 10px;")
            else:
                self.warning_label.setText(tr("web.http_warning"))
                self.warning_label.setStyleSheet("color: #ff6666; padding: 8px 10px;")
        else:
            self.status_label.setText(tr("web.status") + tr("web.status_stopped"))
            self.status_label.setStyleSheet("color: #888; font-size: 11pt;")
            self.toggle_btn.setText(tr("web.start"))
            self.https_cb.setEnabled(True)
            self.qr_label.clear()
            self.qr_label.setText(tr("web.status_stopped"))
            self.qr_label.setStyleSheet("color: #666; font-size: 12pt;")
            self.url_label.setText(tr("web.url") + tr("web.url_none"))
            self.url_label.setStyleSheet("padding: 8px; color: #666;")
            self.loopback_warning.setVisible(False)
            self.warning_label.setText(tr("web.http_warning"))
            self.warning_label.setStyleSheet("color: #ff6666; padding: 8px 10px;")

    def retranslate(self):
        self.section_status.setText(tr("web.section_status"))
        self.section_qr.setText(tr("web.qr_hint"))
        self.https_tip.setText(tr("web.https_tip"))
        self.https_cb.setText(tr("web.https_cb"))
        self.refresh_state()
