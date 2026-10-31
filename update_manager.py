import os
import sys
import hashlib
import subprocess
import threading

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import QMessageBox, QApplication
from crypto import encrypt_data, decrypt_data

class _DownloadWorker(QThread):
    progress = pyqtSignal(int, int, str, float)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url, dest_path, parent=None):
        super().__init__(parent)
        self.url, self.dest_path = url, dest_path
        self._cancel_event = threading.Event()

    def cancel(self): self._cancel_event.set()

    def run(self):
        import updater
        try:
            def on_progress(done, total, src, spd):
                if not self._cancel_event.is_set(): self.progress.emit(int(done), int(total), src, float(spd))
            updater.download_file(self.url, self.dest_path, progress_callback=on_progress, cancel_event=self._cancel_event)
            if self._cancel_event.is_set(): self.failed.emit("__cancelled__")
            else: self.finished_ok.emit(self.dest_path)
        except KeyboardInterrupt: self.failed.emit("__cancelled__")
        except Exception as e: self.failed.emit(str(e))

class UpdateManager(QObject):
    progress_changed = pyqtSignal(int, int, str, float)
    state_changed = pyqtSignal(str)

    STATE_IDLE = 'idle'
    STATE_DOWNLOADING = 'downloading'
    STATE_VERIFYING = 'verifying'

    def __init__(self, parent_main):
        super().__init__(parent_main)
        self._parent_main = parent_main
        self._worker = None
        self._state = self.STATE_IDLE
        self._latest = ''; self._release_data = None; self._expected_sha = None; self._dest_path = ''
        self._last_progress = (0, 0, '', 0.0)

    def get_state(self): return self._state
    def is_downloading(self): return self._state in (self.STATE_DOWNLOADING, self.STATE_VERIFYING)
    def get_last_progress(self): return self._last_progress

    def _set_state(self, state):
        self._state = state
        try: self.state_changed.emit(state)
        except RuntimeError: pass

    def start_download(self, release_data, latest):
        if self.is_downloading(): return False
        import updater
        storage = getattr(self._parent_main, 'storage', None)
        auth = getattr(self._parent_main, 'auth', None)
        if not storage or not auth: return False

        try:
            asset = updater.find_exe_asset(release_data)
            if not asset: return False
            url = asset['browser_download_url']
            self._latest = latest; self._release_data = release_data; self._expected_sha = updater.extract_sha256(release_data)
            
            url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:8]
            temp_dir = os.path.join(auth.settings.CONFIG_DIR, 'updates')
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = os.path.join(temp_dir, f"SecureVault_update_{url_hash}.exe")
            
            for name in os.listdir(temp_dir):
                if name.startswith("SecureVault_update_") and name.endswith(".exe") and name != os.path.basename(temp_path):
                    try: os.remove(os.path.join(temp_dir, name))
                    except OSError: pass

            self._dest_path = temp_path; self._last_progress = (0, 0, '', 0.0)
            self._worker = _DownloadWorker(url, temp_path, self)
            self._worker.progress.connect(self._on_progress)
            self._worker.finished_ok.connect(self._on_download_finished)
            self._worker.failed.connect(self._on_download_failed)
            self._worker.finished.connect(self._worker.deleteLater)
            self._set_state(self.STATE_DOWNLOADING)
            self._worker.start()
            return True
        except Exception as e:
            QMessageBox.critical(self._parent_main, "错误", f"启动失败: {e}")
            self._set_state(self.STATE_IDLE)
            return False

    def cancel(self):
        if self._worker: self._worker.cancel()

    def shutdown(self, wait_ms=5000):
        """退出程序前调用：取消下载并等待线程结束，避免 QThread 被析构导致崩溃。"""
        worker = self._worker
        if worker is not None:
            try: worker.cancel()
            except Exception: pass
            try: worker.wait(wait_ms)
            except Exception: pass

    def _on_progress(self, done, total, src, spd):
        self._last_progress = (done, total, src, spd)
        try: self.progress_changed.emit(done, total, src, spd)
        except RuntimeError: pass

    def _on_download_finished(self, path):
        # ★J：整体包裹 try...except
        try:
            import updater
            self._set_state(self.STATE_VERIFYING)
            parent = self._parent_main

            # 先做 Ed25519 签名校验（权威），再参考 Release 正文里的 SHA-256。
            # 正文哈希只作提示，不能因为正文写错而拒绝一个签名合法的更新包。
            expected_sha = None
            if updater.SIGNING_PUBLIC_KEY:
                sig = updater.find_signature_asset(self._release_data)
                if not sig:
                    QMessageBox.critical(parent, "错误", "缺少签名文件")
                    self._cleanup_failed(); return
                try:
                    sig_bytes = updater.download_signature(sig['browser_download_url'], timeout=15)
                    digest = updater.verified_update_sha256(path, sig_bytes)
                except Exception as e:
                    QMessageBox.critical(parent, "错误", f"验签失败: {e}")
                    self._cleanup_failed(); return
                if not digest:
                    QMessageBox.critical(parent, "错误", "签名验证失败")
                    self._cleanup_failed(); return
                expected_sha = digest
                if self._expected_sha and self._expected_sha.lower() != digest.lower():
                    try:
                        auth = getattr(parent, 'auth', None)
                        if auth:
                            getattr(parent, 'storage', None) and parent.storage.log(
                                "更新包正文 SHA-256 与签名结果不一致，已按签名结果继续")
                    except Exception:
                        pass
            else:
                QMessageBox.critical(parent, "错误", "未配置公钥，拒绝自动安装。")
                self._cleanup_failed(); return

            QMessageBox.information(parent, "更新完成", f"新版本已下载，请手动关闭程序以准备替换。")
            
            exe_dir = os.path.dirname(sys.executable)
            # ★P0-6：源码运行防覆盖 python.exe
            if not getattr(sys, 'frozen', False) or os.path.basename(sys.executable).lower() not in ('encryption.exe', 'securevault.exe'):
                QMessageBox.critical(parent, "安全限制", "仅在正式打包版中支持自动替换。请手动复制。")
                self._set_state(self.STATE_IDLE); return

            try:
                bat = updater.write_update_bat(exe_dir, path, sys.executable, expected_sha)
                subprocess.Popen([bat], creationflags=subprocess.CREATE_NEW_CONSOLE)
            except Exception as e:
                # ★I：仅重置状态，绝不调用 _cleanup_failed 删除文件
                QMessageBox.warning(parent, "错误", f"无法启动替换脚本: {e}\n请手动将 {path} 复制到 {sys.executable}")
                self._set_state(self.STATE_IDLE); return

            self._set_state(self.STATE_IDLE)
            self._worker = None
            QApplication.quit()
        except Exception as e:
            QMessageBox.critical(self._parent_main, "致命错误", f"校验时发生错误: {e}")
            self._cleanup_failed()

    def _on_download_failed(self, err):
        if err == "__cancelled__": QMessageBox.information(self._parent_main, "提示", "已取消下载")
        else: QMessageBox.critical(self._parent_main, "错误", f"更新失败: {err}")
        self._cleanup_failed()

    def _cleanup_failed(self):
        if self._dest_path and os.path.exists(self._dest_path):
            try: os.remove(self._dest_path)
            except OSError: pass
        self._dest_path = ''
        self._set_state(self.STATE_IDLE)
        self._worker = None