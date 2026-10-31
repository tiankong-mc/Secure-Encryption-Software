"""单实例管理：主实例监听本地命名管道，第二实例通过管道转发请求。"""
import os

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = 'SecureVault_SingleInstance_v1'


class SingleInstanceServer(QObject):
    encrypt_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            QLocalServer.removeServer(SERVER_NAME)
        except Exception:
            pass
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_new_connection)
        if not self.server.listen(SERVER_NAME):
            try:
                reason = self.server.errorString()
            except Exception:
                reason = "未知原因"
            print(f"⚠️ 单实例管道监听失败: {reason}")
            print("  → 双击启动时可能无法阻止第二个实例，右键菜单转发也将失效")

    def _on_new_connection(self):
        sock = self.server.nextPendingConnection()
        if not sock:
            return
        sock._sv_buffer = b''  # 累积缓冲区，处理分片
        sock.readyRead.connect(lambda s=sock: self._on_ready_read(s))
        sock.disconnected.connect(sock.deleteLater)

    def _on_ready_read(self, sock):
        try:
            data = bytes(sock.readAll())
            sock._sv_buffer += data
            text = sock._sv_buffer.decode('utf-8', errors='replace')
        except Exception:
            text = ''
        stripped = text.strip()
        if stripped == 'ping':
            try:
                sock.disconnectFromServer()
            except Exception:
                pass
            return
        if stripped.startswith('encrypt:'):
            path = stripped[len('encrypt:'):].strip()
            if path and os.path.isfile(path):
                self.encrypt_requested.emit(path)
            try:
                sock.disconnectFromServer()
            except Exception:
                pass


def try_send_to_existing_instance(payload, timeout_ms=800):
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(timeout_ms):
        return False
    try:
        sock.write(payload.encode('utf-8'))
        sock.flush()
        sock.waitForBytesWritten(timeout_ms)
    finally:
        try:
            sock.disconnectFromServer()
        except Exception:
            pass
    return True