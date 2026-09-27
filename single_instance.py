"""单实例管理：主实例监听本地命名管道，第二实例通过管道转发请求。

工作流程：
- 每个进程启动时都会尝试连接本地命名管道 SERVER_NAME
- 连接成功：说明已有主实例在运行
  - 带 --encrypt 参数：把加密请求发给主实例后本进程退出
  - 不带参数：发送 "ping" 探测后本进程退出（避免双开）
- 连接失败：本进程成为主实例，监听命名管道，接收后续所有请求
"""

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = 'SecureVault_SingleInstance_v1'


class SingleInstanceServer(QObject):
    """主实例的本地服务器：接收第二实例发来的文件路径并转发信号。"""

    # 收到加密请求时发出：参数为要加密的文件绝对路径
    encrypt_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 清理可能残留的命名管道（异常退出时可能留下）
        try:
            QLocalServer.removeServer(SERVER_NAME)
        except Exception:
            pass
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_new_connection)
        # 修复 #2：检查 listen 返回值，失败时打印警告（避免静默失效）
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
        sock.readyRead.connect(lambda s=sock: self._on_ready_read(s))
        sock.disconnected.connect(sock.deleteLater)

    def _on_ready_read(self, sock):
        try:
            data = bytes(sock.readAll()).decode('utf-8', errors='replace').strip()
        except Exception:
            data = ''
        if data.startswith('encrypt:'):
            path = data[len('encrypt:'):].strip()
            if path:
                self.encrypt_requested.emit(path)
        # 纯 'ping' 只是探测，不处理
        try:
            sock.disconnectFromServer()
        except Exception:
            pass


def try_send_to_existing_instance(payload, timeout_ms=800):
    """尝试把 payload 发送给已运行的主实例。成功返回 True，否则 False。"""
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
