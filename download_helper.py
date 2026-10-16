"""邮箱配置助手下载工具。

从 Gitee Releases 下载邮箱配置助手，支持用户选择保存路径，
下载过程中显示进度、速度，完成后询问是否立即启动。

未来更新助手版本时，只需修改下面的 GITEE_TAG 与 GITEE_FILENAME。
"""

import os
import time
import threading
import traceback
from urllib.parse import quote

from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtWidgets import (QFileDialog, QMessageBox, QApplication,
                              QProgressDialog)

import requests


# ==================== Gitee Release 配置 ====================
# 仓库信息
GITEE_OWNER = "tiankong_mc"
GITEE_REPO = "mail-helper"

# Release 版本与附件文件名（更新助手版本时修改这两项）
GITEE_TAG = "v1.0.0"
GITEE_FILENAME = "邮箱授权码获取助手.exe"

# 拼装下载直链（对文件名做 URL 编码以兼容中文）
GITEE_DOWNLOAD_URL = (
    f"https://gitee.com/{GITEE_OWNER}/{GITEE_REPO}/releases/download/"
    f"{GITEE_TAG}/{quote(GITEE_FILENAME)}"
)

# Release 页面 URL（下载失败时提示用户手动访问）
GITEE_RELEASE_PAGE = (
    f"https://gitee.com/{GITEE_OWNER}/{GITEE_REPO}/releases/tag/{GITEE_TAG}"
)

# 下载超时配置
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 60
CHUNK_SIZE = 256 * 1024

# 通用请求头
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
       'AppleWebKit/537.36 (KHTML, like Gecko) '
       'Chrome/120.0.0.0 Safari/537.36')


def _fmt_size(bytes_count):
    """把字节数格式化为人类可读的大小。"""
    try:
        n = float(bytes_count)
    except (TypeError, ValueError):
        return "?"
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class _DownloadWorker(QThread):
    """后台下载线程。"""

    # (已下载字节, 总字节, 速度字节/秒)
    progress = pyqtSignal(int, int, float)
    finished_ok = pyqtSignal(str)    # 保存路径
    failed = pyqtSignal(str)         # 错误信息

    def __init__(self, url, save_path, parent=None):
        super().__init__(parent)
        self.url = url
        self.save_path = save_path
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            session = requests.Session()
            session.headers.update({
                'User-Agent': _UA,
                'Referer': 'https://gitee.com/',
            })

            start_time = time.monotonic()

            resp = session.get(
                self.url,
                stream=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                allow_redirects=True,
            )
            resp.raise_for_status()

            # 防御性检查：避免把 HTML 错误页当作 EXE 下载
            content_type = resp.headers.get('content-type', '').lower()
            if 'text/html' in content_type:
                raise RuntimeError(
                    "服务器返回的是网页而不是安装包，"
                    "直链可能已失效。")

            total = int(resp.headers.get('content-length', 0))
            downloaded = 0
            last_emit_time = 0.0

            with open(self.save_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if self._cancel_event.is_set():
                        self.failed.emit("__cancelled__")
                        return
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)

                    # 计算瞬时平均速度
                    now = time.monotonic()
                    elapsed = max(now - start_time, 0.001)
                    speed = downloaded / elapsed

                    # 每 0.2 秒发一次信号，避免高频刷新拖慢 UI
                    if now - last_emit_time >= 0.2:
                        last_emit_time = now
                        self.progress.emit(downloaded, total, speed)

            # 下载完成时再发一次，确保进度条走到 100%
            elapsed = max(time.monotonic() - start_time, 0.001)
            speed = downloaded / elapsed
            self.progress.emit(downloaded, total or downloaded, speed)

            if downloaded == 0:
                raise RuntimeError("下载内容为空")

            self.finished_ok.emit(self.save_path)

        except requests.RequestException as e:
            self.failed.emit(f"下载失败：{e}")
        except OSError as e:
            self.failed.emit(f"文件写入失败：{e}")
        except Exception as e:
            self.failed.emit(f"{e}")


class EmailConfigHelperDownloader:
    """
    邮箱配置助手下载器。

    用法：
        downloader = EmailConfigHelperDownloader(parent_widget)
        downloader.start()
    """

    def __init__(self, parent=None):
        self.parent = parent
        self._worker = None
        self._progress_dialog = None
        self._save_path = None
        self._cancelled = False

    def start(self):
        """开始下载流程：选择保存路径 → 后台下载（带进度条） → 询问是否启动。"""
        default_name = GITEE_FILENAME
        save_path, _ = QFileDialog.getSaveFileName(
            self.parent,
            "保存邮箱配置助手",
            default_name,
            "可执行文件 (*.exe);;所有文件 (*.*)",
        )
        if not save_path:
            return

        # 确保以 .exe 结尾（用户可能忘记后缀）
        if not save_path.lower().endswith('.exe'):
            save_path += '.exe'

        self._save_path = save_path
        self._cancelled = False

        # 创建进度对话框
        self._progress_dialog = QProgressDialog(
            "正在准备下载...",
            "取消",
            0, 100,
            self.parent,
        )
        self._progress_dialog.setWindowTitle("下载邮箱配置助手")
        self._progress_dialog.setWindowModality(Qt.WindowModal)
        self._progress_dialog.setMinimumDuration(0)
        self._progress_dialog.setAutoClose(False)
        self._progress_dialog.setAutoReset(False)
        self._progress_dialog.setValue(0)
        self._progress_dialog.canceled.connect(self._on_cancel_clicked)

        # 启动后台下载
        self._worker = _DownloadWorker(GITEE_DOWNLOAD_URL, save_path, self.parent)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.progress.connect(self._on_progress)
        self._worker.start()

        self._progress_dialog.show()

    def _on_cancel_clicked(self):
        """用户点击了"取消"按钮。"""
        self._cancelled = True
        if self._worker is not None:
            self._worker.cancel()

    def _on_progress(self, done, total, speed):
        """更新进度条显示。"""
        if self._progress_dialog is None:
            return
        try:
            speed_str = f"{_fmt_size(speed)}/s" if speed > 0 else "计算中..."
            if total > 0:
                percent = int(done * 100 / total)
                self._progress_dialog.setValue(percent)
                self._progress_dialog.setLabelText(
                    f"正在下载邮箱配置助手...\n"
                    f"{_fmt_size(done)} / {_fmt_size(total)}\n"
                    f"速度：{speed_str}"
                )
            else:
                # 服务器未返回内容长度 → 不确定模式
                self._progress_dialog.setRange(0, 0)
                self._progress_dialog.setLabelText(
                    f"正在下载邮箱配置助手...\n"
                    f"已下载：{_fmt_size(done)}\n"
                    f"速度：{speed_str}"
                )
        except RuntimeError:
            # 对话框可能已被销毁
            pass

    def _close_progress_dialog(self):
        """安全关闭进度对话框。"""
        dlg = self._progress_dialog
        self._progress_dialog = None
        if dlg is not None:
            try:
                dlg.blockSignals(True)
                dlg.close()
                dlg.deleteLater()
            except Exception:
                pass

    def _on_finished(self, save_path):
        """下载完成，询问用户是否启动。"""
        self._close_progress_dialog()

        reply = QMessageBox.question(
            self.parent,
            "下载完成",
            f"邮箱配置助手已下载到：\n{save_path}\n\n是否立即启动？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            try:
                os.startfile(save_path)
            except Exception as e:
                QMessageBox.warning(
                    self.parent, "启动失败",
                    f"无法启动程序：\n{e}\n\n"
                    f"请手动打开：\n{save_path}")
        self._cleanup(remove_file=False)

    def _on_failed(self, err):
        """下载失败或用户取消。"""
        self._close_progress_dialog()

        if err == "__cancelled__" or self._cancelled:
            # 用户取消 → 删除不完整的文件
            self._cleanup(remove_file=True)
            QMessageBox.information(self.parent, "已取消", "下载已取消。")
            return

        # 真实失败 → 删除不完整的文件
        self._cleanup(remove_file=True)
        QMessageBox.critical(
            self.parent, "下载失败",
            f"下载邮箱配置助手失败：\n{err}\n\n"
            f"你可以在浏览器中手动下载：\n{GITEE_RELEASE_PAGE}")

    def _cleanup(self, remove_file=False):
        """清理后台线程与临时文件。"""
        worker = self._worker
        self._worker = None
        if worker is not None:
            try:
                worker.cancel()
                if worker.isRunning():
                    worker.wait(3000)
            except Exception:
                pass

        if remove_file and self._save_path:
            try:
                if os.path.exists(self._save_path):
                    # 只有文件确实不完整时才删（下载完成的情况下不会调用此分支）
                    os.remove(self._save_path)
            except OSError:
                pass

        self._save_path = None


def create_download_button(parent, tooltip="下载邮箱配置助手"):
    """
    创建一个"下载配置助手"按钮，返回按钮对象。

    调用方需要自行将按钮添加到布局中，并连接 clicked 信号到 downloader.start()。
    """
    from PyQt5.QtWidgets import QPushButton
    btn = QPushButton("📥 下载配置助手")
    btn.setToolTip(tooltip)
    btn.setMinimumWidth(120)
    return btn
