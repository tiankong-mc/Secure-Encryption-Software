import os
import json
import ctypes
from ctypes import wintypes

class DPAPI:
    """Windows DPAPI 加密/解密（当前用户上下文）"""
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
    CONFIG_DIR = os.path.join(os.environ['APPDATA'], 'SecureVault')
    CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.dat')
    MASTER_KEY_PATH = os.path.join(CONFIG_DIR, 'master.key')

    def __init__(self):
        self.dpapi = DPAPI()
        os.makedirs(self.CONFIG_DIR, exist_ok=True)

    def get_master_key(self):
        if os.path.exists(self.MASTER_KEY_PATH):
            with open(self.MASTER_KEY_PATH, 'rb') as f:
                encrypted = f.read()
            return self.dpapi.unprotect(encrypted)
        else:
            key = os.urandom(32)
            encrypted = self.dpapi.protect(key)
            with open(self.MASTER_KEY_PATH, 'wb') as f:
                f.write(encrypted)
            return key

    def load_settings(self):
        if os.path.exists(self.CONFIG_PATH):
            with open(self.CONFIG_PATH, 'rb') as f:
                encrypted = f.read()
            try:
                data = self.dpapi.unprotect(encrypted)
                return json.loads(data.decode('utf-8'))
            except:
                return {}
        return {}

    def save_settings(self, settings_dict):
        data = json.dumps(settings_dict).encode('utf-8')
        encrypted = self.dpapi.protect(data)
        with open(self.CONFIG_PATH, 'wb') as f:
            f.write(encrypted)
