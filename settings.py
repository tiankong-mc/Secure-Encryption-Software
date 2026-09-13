import os
import json
import ctypes
from ctypes import wintypes

# 加密文件默认目录（首次运行使用，用户可在设置中修改）
DEFAULT_SECRET_DIR = r'C:\ProgramData\SecureVault'


class DPAPI:
    def __init__(self):
        self.crypt32 = ctypes.windll.crypt32
        self.kernel32 = ctypes.windll.kernel32

    def protect(self, data_bytes):
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        blob_in = DATA_BLOB(len(data_bytes), ctypes.cast(data_bytes, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not self.crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            raise ctypes.WinError()
        result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        self.kernel32.LocalFree(blob_out.pbData)
        return result

    def unprotect(self, encrypted_bytes):
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        blob_in = DATA_BLOB(len(encrypted_bytes), ctypes.cast(encrypted_bytes, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not self.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            raise ctypes.WinError()
        result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        self.kernel32.LocalFree(blob_out.pbData)
        return result


class SettingsManager:
    # 配置目录固定（安全考虑，不允许修改）
    CONFIG_DIR = os.path.join(os.environ['APPDATA'], 'SecureVault')
    CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.dat')
    MASTER_KEY_PATH = os.path.join(CONFIG_DIR, 'master.key')

    def __init__(self):
        self.dpapi = DPAPI()
        os.makedirs(self.CONFIG_DIR, exist_ok=True)
        self._settings_cache = None

    def get_master_key(self):
        if os.path.exists(self.MASTER_KEY_PATH):
            with open(self.MASTER_KEY_PATH, 'rb') as f:
                encrypted = f.read()
            key = self.dpapi.unprotect(encrypted)
            if len(key) != 32:
                raise ValueError("主密钥长度无效")
            return key
        else:
            key = os.urandom(32)
            encrypted = self.dpapi.protect(key)
            self._atomic_write(self.MASTER_KEY_PATH, encrypted)
            return key

    @staticmethod
    def _atomic_write(path, data):
        temp_path = path + '.tmp'
        try:
            with open(temp_path, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def load_settings(self):
        if self._settings_cache is not None:
            return self._settings_cache
        if os.path.exists(self.CONFIG_PATH):
            with open(self.CONFIG_PATH, 'rb') as f:
                encrypted = f.read()
            try:
                data = self.dpapi.unprotect(encrypted)
                self._settings_cache = json.loads(data.decode('utf-8'))
                return self._settings_cache
            except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                self._settings_cache = {}
                return self._settings_cache
        self._settings_cache = {}
        return self._settings_cache

    def save_settings(self, settings_dict):
        data = json.dumps(settings_dict).encode('utf-8')
        encrypted = self.dpapi.protect(data)
        self._atomic_write(self.CONFIG_PATH, encrypted)
        self._settings_cache = dict(settings_dict)

    # ---------- 加密文件目录 ----------
    def get_secret_dir(self):
        """返回加密文件目录，不存在时返回默认值。"""
        s = self.load_settings()
        path = s.get('secret_dir') or DEFAULT_SECRET_DIR
        return os.path.abspath(path)

    def set_secret_dir(self, new_dir):
        s = dict(self.load_settings())
        s['secret_dir'] = os.path.abspath(new_dir)
        self.save_settings(s)
