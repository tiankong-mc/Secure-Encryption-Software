"""邮箱配置助手下载工具。"""
import os, time, threading, traceback
from urllib.parse import quote
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QApplication, QProgressDialog
import requests

GITEE_OWNER = "tiankong_mc"
GITEE_REPO = "mail-helper"
GITEE_TAG = "v1.0.0"
GITEE_FILENAME = "邮箱授权码获取助手.exe"
GITEE_DOWNLOAD_URL = (f"https://gitee.com/{GITEE_OWNER}/{GITEE_REPO}/releases/download/"
                      f"{GITEE_TAG}/{quote(GITEE_FILENAME)}")
GITEE_RELEASE_PAGE = f"https://gitee.com/{GITEE_OWNER}/{GITEE_REPO}/releases/tag/{GITEE_TAG}"
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 60
CHUNK_SIZE = 256 * 1024
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

def _fmt_size(bytes_count):
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
    progress = pyqtSignal(int, int, float)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url, save_path, parent=None):
        super().__init__(parent)
        self.url = url
        self.save_path = save_path
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        part_path = self.save_path + '.part'
        try:
            session = requests.Session()
            session.headers.update({'User-Agent': _UA, 'Referer': 'https://gitee.com/'})
            start_time = time.monotonic()
            resp = session.get(self.url, stream=True, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), allow_redirects=True)
            resp.raise_for_status()
            if 'text/html' in resp.headers.get('content-type', '').lower():
                raise RuntimeError("服务器返回网页而不是安装包，直链可能已失效。")
            total = int(resp.headers.get('content-length', 0))
            downloaded = 0
            last_emit_time = 0.0
            with open(part_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if self._cancel_event.is_set():
                        self.failed.emit("__cancelled__"); return
                    if not chunk: continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if now - last_emit_time >= 0.2:
                        last_emit_time = now
                        self.progress.emit(downloaded, total, downloaded / max(now - start_time, 0.001))
            if downloaded == 0:
                raise RuntimeError("下载内容为空")
            # 直接覆盖，不先删除用户已有文件，避免 replace 失败导致原文件丢失
            os.replace(part_path, self.save_path)
            self.progress.emit(downloaded, total or downloaded, 0.0)
            self.finished_ok.emit(self.save_path)
        except requests.RequestException as e:
            self.failed.emit(f"下载失败：{e}")
        except Exception as e:
            self.failed.emit(f"{e}")
        finally:
            if os.path.exists(part_path):
                try: os.remove(part_path)
                except OSError: pass

class EmailConfigHelperDownloader:
    def __init__(self, parent=None):
        self.parent = parent
        self._worker = None
        self._progress_dialog = None
        self._save_path = None
        self._cancelled = False

    def start(self):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self.parent, "提示", "下载已在进行中。"); return
        default_name = GITEE_FILENAME
        save_path, _ = QFileDialog.getSaveFileName(
            self.parent, "保存邮箱配置助手", default_name, "可执行文件 (*.exe);;所有文件 (*.*)")
        if not save_path: return
        if not save_path.lower().endswith('.exe'): save_path += '.exe'
        self._save_path = save_path
        self._cancelled = False
        self._progress_dialog = QProgressDialog("正在准备下载...", "取消", 0, 100, self.parent)
        self._progress_dialog.setWindowTitle("下载邮箱配置助手")
        self._progress_dialog.setWindowModality(Qt.WindowModal)
        self._progress_dialog.setMinimumDuration(0)
        self._progress_dialog.setAutoClose(False)
        self._progress_dialog.setAutoReset(False)
        self._progress_dialog.setValue(0)
        self._progress_dialog.canceled.connect(self._on_cancel_clicked)
        self._worker = _DownloadWorker(GITEE_DOWNLOAD_URL, save_path, QApplication.instance())
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.progress.connect(self._on_progress)
        self._worker.start()
        self._progress_dialog.show()

    def _on_cancel_clicked(self):
        self._cancelled = True
        if self._worker is not None: self._worker.cancel()

    def _on_progress(self, done, total, speed):
        if self._progress_dialog is None: return
        try:
            speed_str = f"{_fmt_size(speed)}/s" if speed > 0 else "计算中..."
            if total > 0:
                percent = int(done * 100 / total)
                self._progress_dialog.setValue(percent)
                self._progress_dialog.setLabelText(f"正在下载邮箱配置助手...\n{_fmt_size(done)} / {_fmt_size(total)}\n速度：{speed_str}")
            else:
                self._progress_dialog.setRange(0, 0)
                self._progress_dialog.setLabelText(f"正在下载邮箱配置助手...\n已下载：{_fmt_size(done)}\n速度：{speed_str}")
        except RuntimeError: pass

    def _close_progress_dialog(self):
        dlg = self._progress_dialog; self._progress_dialog = None
        if dlg is not None:
            try:
                dlg.blockSignals(True); dlg.close(); dlg.deleteLater()
            except Exception: pass

    def _on_finished(self, save_path):
        self._close_progress_dialog()
        reply = QMessageBox.question(
            self.parent, "下载完成",
            f"邮箱配置助手已下载到：\n{save_path}\n\n是否立即启动？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            try: os.startfile(save_path)
            except Exception as e:
                QMessageBox.warning(self.parent, "启动失败", f"无法启动程序：\n{e}\n\n请手动打开：\n{save_path}")

    def _on_failed(self, err):
        self._close_progress_dialog()
        if err == "__cancelled__" or self._cancelled:
            QMessageBox.information(self.parent, "已取消", "下载已取消。"); return
        QMessageBox.critical(self.parent, "下载失败",
            f"下载邮箱配置助手失败：\n{err}\n\n你可以在浏览器中手动下载：\n{GITEE_RELEASE_PAGE}")

def create_download_button(parent, tooltip="下载邮箱配置助手"):
    from PyQt5.QtWidgets import QPushButton
    btn = QPushButton("📥 下载配置助手")
    btn.setToolTip(tooltip)
    btn.setMinimumWidth(120)
    return btn