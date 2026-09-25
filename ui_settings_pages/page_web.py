import os, socket
from io import BytesIO
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QMessageBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
import qrcode
from i18n import tr
from constants import WEB_PORT
from ui_web import start_web_server, stop_web_server, is_web_running
from ui_settings_style import (SettingsPage, make_page_title, make_section_title,
                                make_card, make_hline)


class WebPage(SettingsPage):
    def __init__(self, settings_dialog):
        super().__init__()
        self.settings_dialog = settings_dialog

        self.layout().addWidget(make_page_title(tr("web.title")))

        # ---- 状态卡片 ----
        self.layout().addWidget(make_section_title("服务状态"))
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

        self.warning_label = QLabel(tr("web.http_warning"))
        self.warning_label.setStyleSheet("color: #ff6666; padding: 8px 10px;")
        self.warning_label.setWordWrap(True)
        c.addWidget(self.warning_label)
        self.layout().addWidget(card)

        # ---- 二维码卡片 ----
        self.layout().addWidget(make_section_title(tr("web.qr_hint")))
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

        # 无局域网 IP 时的额外警告
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
        """
        获取本机局域网 IP。
        返回 (ip, is_loopback)：
          - 正常情况：(局域网 IP, False)
          - 无可用局域网 IP：(127.0.0.1, True)，此时二维码对其他设备无效
        """
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

    def toggle_server(self):
        if is_web_running():
            stop_web_server()
            self.settings_dialog.storage.log("停止移动端Web服务")
        else:
            if start_web_server(self.settings_dialog.storage, self.settings_dialog.auth):
                self.settings_dialog.storage.log("启动移动端Web服务")
            else:
                QMessageBox.warning(self, tr("common.error"),
                                    f"无法启动 Web 服务，请检查端口 {WEB_PORT} 是否被占用。")
            QTimer.singleShot(800, self.refresh_state)
        self.refresh_state()

    def refresh_state(self):
        running = is_web_running()
        if running:
            self.status_label.setText(tr("web.status") + tr("web.status_running"))
            self.status_label.setStyleSheet("color: #4caf50; font-size: 11pt;")
            self.toggle_btn.setText(tr("web.stop"))

            ip, is_loopback = self._get_ip()
            url = f"http://{ip}:{WEB_PORT}"
            pixmap = self._make_qr_pixmap(url)
            self.qr_label.setPixmap(pixmap)
            self.url_label.setText(url)

            if is_loopback:
                # 修复 #4：无局域网 IP 时显式警告二维码对其他设备无效
                self.url_label.setStyleSheet("padding: 8px; color: #ffaa00;")
                self.loopback_warning.setText(
                    "⚠ 未检测到局域网 IP（当前为 127.0.0.1）。\n"
                    "其他设备扫码将无法访问，请确认本机已连接到局域网 / Wi-Fi。")
                self.loopback_warning.setVisible(True)
            else:
                self.url_label.setStyleSheet("padding: 8px; color: #5a8cbf;")
                self.loopback_warning.setVisible(False)
        else:
            self.status_label.setText(tr("web.status") + tr("web.status_stopped"))
            self.status_label.setStyleSheet("color: #888; font-size: 11pt;")
            self.toggle_btn.setText(tr("web.start"))
            self.qr_label.clear()
            self.qr_label.setText(tr("web.status_stopped"))
            self.qr_label.setStyleSheet("color: #666; font-size: 12pt;")
            self.url_label.setText(tr("web.url") + tr("web.url_none"))
            self.url_label.setStyleSheet("padding: 8px; color: #666;")
            self.loopback_warning.setVisible(False)

    def retranslate(self):
        self.warning_label.setText(tr("web.http_warning"))
        self.refresh_state()
