"""全局更新管理器。

生命周期独立于 SettingsDialog，即使用户关闭设置窗口或切换页面，
下载线程依然在后台运行，完成后自动弹窗提示。
"""

import os
import sys
import hashlib
import subprocess
import threading

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import QMessageBox, QApplication


class _DownloadWorker(QThread):
    """后台下载线程。"""

    progress = pyqtSignal(int, int, str, float)  # (done, total, source, speed)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url, dest_path, parent=None):
        super().__init__(parent)
        self.url = url
        self.dest_path = dest_path
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        import updater
        try:
            def on_progress(done, total, source_name, speed_kbps):
                if self._cancel_event.is_set():
                    return
                try:
                    self.progress.emit(int(done), int(total),
                                       str(source_name), float(speed_kbps))
                except RuntimeError:
                    pass

            updater.download_file(
                self.url, self.dest_path,
                progress_callback=on_progress,
                cancel_event=self._cancel_event)
            if self._cancel_event.is_set():
                self.failed.emit("__cancelled__")
            else:
                self.finished_ok.emit(self.dest_path)
        except KeyboardInterrupt:
            self.failed.emit("__cancelled__")
        except Exception as e:
            try:
                self.failed.emit(str(e))
            except RuntimeError:
                pass


class UpdateManager(QObject):
    """全局更新管理器，独立于 SettingsDialog 生命周期。"""

    # 状态信号
    progress_changed = pyqtSignal(int, int, str, float)
    state_changed = pyqtSignal(str)  # 'idle', 'downloading', 'verifying'

    STATE_IDLE = 'idle'
    STATE_DOWNLOADING = 'downloading'
    STATE_VERIFYING = 'verifying'

    def __init__(self, parent_main):
        super().__init__(parent_main)
        self._parent_main = parent_main
        self._worker = None
        self._state = self.STATE_IDLE
        self._latest = ''
        self._release_data = None
        self._expected_sha = None
        self._dest_path = ''
        self._last_progress = (0, 0, '', 0.0)

    # ---------- 状态查询 ----------
    def get_state(self):
        return self._state

    def is_downloading(self):
        return self._state in (self.STATE_DOWNLOADING, self.STATE_VERIFYING)

    def get_last_progress(self):
        return self._last_progress

    def _set_state(self, state):
        self._state = state
        try:
            self.state_changed.emit(state)
        except RuntimeError:
            pass

    # ---------- 下载控制 ----------
    def start_download(self, release_data, latest):
        """开始下载更新。成功启动返回 True。"""
        if self.is_downloading():
            return False
        import updater

        parent_main = self._parent_main
        storage = getattr(parent_main, 'storage', None)
        auth = getattr(parent_main, 'auth', None)
        if storage is None or auth is None:
            return False

        try:
            asset = updater.find_exe_asset(release_data)
            if not asset:
                QMessageBox.warning(parent_main, "错误", "未找到可执行文件")
                return False
            url = asset['browser_download_url']
            expected_sha = updater.extract_sha256(release_data)

            self._latest = latest
            self._release_data = release_data
            self._expected_sha = expected_sha
            storage.log(f"开始下载更新: {latest}")

            # 用 URL 哈希做临时文件唯一标识，避免旧版本残留污染断点续传
            url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:8]
            temp_dir = os.path.join(auth.settings.CONFIG_DIR, 'updates')
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = os.path.join(temp_dir, f"SecureVault_update_{url_hash}.exe")

            # 清理旧的下载文件
            try:
                for name in os.listdir(temp_dir):
                    if (name.startswith("SecureVault_update_")
                            and name.endswith(".exe")):
                        old_path = os.path.join(temp_dir, name)
                        if os.path.normcase(old_path) != os.path.normcase(temp_path):
                            try:
                                os.remove(old_path)
                            except OSError:
                                pass
            except OSError:
                pass

            self._dest_path = temp_path
            self._last_progress = (0, 0, '', 0.0)
            self._worker = _DownloadWorker(url, temp_path, self)
            self._worker.progress.connect(self._on_progress)
            self._worker.finished_ok.connect(self._on_download_finished)
            self._worker.failed.connect(self._on_download_failed)
            self._set_state(self.STATE_DOWNLOADING)
            self._worker.start()
            return True
        except Exception as e:
            QMessageBox.critical(parent_main, "错误", f"更新失败: {e}")
            self._set_state(self.STATE_IDLE)
            return False

    def cancel(self):
        """取消当前下载。"""
        if self._worker is not None:
            try:
                self._worker.cancel()
            except Exception:
                pass

    # ---------- 内部回调 ----------
    def _on_progress(self, done, total, source_name, speed):
        self._last_progress = (done, total, source_name, speed)
        try:
            self.progress_changed.emit(done, total, source_name, speed)
        except RuntimeError:
            pass

    def _on_download_finished(self, path):
        import updater
        self._set_state(self.STATE_VERIFYING)
        parent_widget = self._parent_main
        storage = getattr(parent_widget, 'storage', None)

        # ---------- 1. SHA-256 校验 ----------
        if self._expected_sha:
            if not updater.verify_sha256(path, self._expected_sha):
                QMessageBox.critical(parent_widget, "错误", "SHA-256 校验失败")
                self._cleanup_failed()
                return
        else:
            if QMessageBox.question(
                    parent_widget, "警告",
                    "未提供 SHA-256，继续？",
                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                self._cleanup_failed()
                return

        # ---------- 2. Ed25519 签名校验 ----------
        if updater.SIGNING_PUBLIC_KEY:
            sig_asset = updater.find_signature_asset(self._release_data)
            if not sig_asset:
                QMessageBox.critical(
                    parent_widget, "错误",
                    "当前版本已配置签名公钥，但此 Release 未提供 .sig 签名文件。\n\n"
                    "出于安全考虑，拒绝安装未签名的更新。\n"
                    "请联系发布者重新发布带签名的版本。")
                self._cleanup_failed()
                return

            try:
                sig_bytes = updater.download_signature(
                    sig_asset['browser_download_url'], timeout=15)
                verified_digest = updater.verified_update_sha256(path, sig_bytes)
            except Exception as e:
                QMessageBox.critical(
                    parent_widget, "错误",
                    f"签名校验过程出错：{e}\n\n出于安全考虑，拒绝安装。")
                self._cleanup_failed()
                return

            if not verified_digest:
                QMessageBox.critical(
                    parent_widget, "错误",
                    "Ed25519 签名校验失败。\n\n"
                    "此文件可能被篡改或伪造，已拒绝安装。\n"
                    "请从官方渠道重新下载。")
                self._cleanup_failed()
                return

            expected_sha = verified_digest
        else:
            QMessageBox.critical(parent_widget, "错误",
                "未配置发布者签名公钥，已拒绝自动安装。")
            self._cleanup_failed()
            return

        # ---------- 3. 提示完成 ----------
        QMessageBox.information(
            parent_widget, "更新完成",
            f"新版本 {self._latest} 已下载并准备替换。\n\n"
            "请手动关闭本程序，然后双击运行 SecureVault.exe 启动新版本。")

        # ---------- 4. 启动替换脚本 ----------
        exe_dir = os.path.dirname(sys.executable)
        try:
            bat_path = updater.write_update_bat(
                exe_dir, path, sys.executable, expected_sha256=expected_sha)
            subprocess.Popen([bat_path], creationflags=subprocess.CREATE_NEW_CONSOLE)
            if storage:
                storage.log("更新替换完成，用户手动启动")
        except Exception as e:
            if storage:
                storage.log(f"启动替换脚本失败: {e}")
            QMessageBox.warning(
                parent_widget, "警告",
                f"启动替换脚本失败：{e}\n\n"
                f"新版本已下载到：\n{path}\n"
                f"请手动将文件复制到：\n{sys.executable}")
            self._cleanup_failed()
            return

        self._set_state(self.STATE_IDLE)
        self._worker = None
        self._dest_path = ''
        QApplication.quit()

    def _on_download_failed(self, err):
        parent_widget = self._parent_main
        if err == "__cancelled__":
            try:
                QMessageBox.information(parent_widget, "提示", "已取消下载")
            except RuntimeError:
                pass
        else:
            try:
                QMessageBox.critical(parent_widget, "错误", f"更新失败: {err}")
            except RuntimeError:
                pass
        self._cleanup_failed()

    def _cleanup_failed(self):
        """清理失败的下载文件，重置状态。"""
        if self._dest_path:
            try:
                if os.path.exists(self._dest_path):
                    os.remove(self._dest_path)
            except OSError:
                pass
            self._dest_path = ''
        self._set_state(self.STATE_IDLE)
        self._worker = None
