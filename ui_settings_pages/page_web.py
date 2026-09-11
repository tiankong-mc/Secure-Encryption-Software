import os, socket, threading
from io import BytesIO
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
import qrcode
from i18n import tr
from constants import WEB_PORT
from ui_web import start_web_server, stop_web_server, is_web_running


class WebPage(QWidget):
    def __init__(self, settings_dialog):
        super().__init__()
        self.settings_dialog = settings_dialog
        layout = QVBoxLayout(self)
        title = QLabel(tr("web.title"))
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        layout.addWidget(title)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.toggle_btn = QPushButton("")
        self.toggle_btn.clicked.connect(self.toggle_server)
        btn_row.addWidget(self.toggle_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.warning_label = QLabel(tr("web.http_warning"))
        self.warning_label.setStyleSheet("color: #ff4444;")
        self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.qr_label)

        self.url_label = QLabel("")
        self.url_label.setAlignment(Qt.AlignCenter)
        self.url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.url_label)

        layout.addStretch()
        self.refresh_state()

    def _get_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0)
            s.connect(('8.8.8.8', 1))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return '127.0.0.1'

    def toggle_server(self):
        if is_web_running():
            stop_web_server()
            self.settings_dialog.storage.log("停止移动端Web服务")
        else:
            start_web_server(self.settings_dialog.storage, self.settings_dialog.auth)
            self.settings_dialog.storage.log("启动移动端Web服务")
            QTimer.singleShot(800, self.refresh_state)
        self.refresh_state()

    def refresh_state(self):
        running = is_web_running()
        if running:
            self.status_label.setText(tr("web.status") + tr("web.status_running"))
            self.status_label.setStyleSheet("color: green;")
            self.toggle_btn.setText(tr("web.stop"))
            ip = self._get_ip()
            url = f"http://{ip}:{WEB_PORT}"
            qr = qrcode.make(url)
            buf = BytesIO(); qr.save(buf, format='PNG')
            pixmap = QPixmap(); pixmap.loadFromData(buf.getvalue())
            self.qr_label.setPixmap(pixmap.scaled(220, 220, Qt.KeepAspectRatio))
            self.url_label.setText(tr("web.url") + url)
            self.qr_label.setStyleSheet("")
            self.url_label.setStyleSheet("")
        else:
            self.status_label.setText(tr("web.status") + tr("web.status_stopped"))
            self.status_label.setStyleSheet("color: gray;")
            self.toggle_btn.setText(tr("web.start"))
            self.qr_label.clear()
            self.qr_label.setStyleSheet("background:#333;")
            self.url_label.setText(tr("web.url") + tr("web.url_none"))
            self.url_label.setStyleSheet("color: #666;")

    def retranslate(self):
        self.status_label.setText(tr("web.status") + (tr("web.status_running") if is_web_running() else tr("web.status_stopped")))
        self.toggle_btn.setText(tr("web.stop") if is_web_running() else tr("web.start"))
        self.warning_label.setText(tr("web.http_warning"))
