import os
import json
import ctypes
import tempfile
import hashlib
import struct
from ctypes import wintypes
from crypto import encrypt_data, decrypt_data

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
    CONFIG_DIR = os.path.join(os.environ['APPDATA'], 'SecureVault')
    CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.dat')
    MASTER_KEY_PATH = os.path.join(CONFIG_DIR, 'master.key')
    MASTER_KEY_LOCKED_PATH = os.path.join(CONFIG_DIR, 'master.key.locked')

    LOCKED_MAGIC = b'SVHS'

    def __init__(self):
        self.dpapi = DPAPI()
        os.makedirs(self.CONFIG_DIR, exist_ok=True)
        self._settings_cache = None

    def is_high_security_enabled(self):
        return os.path.exists(self.MASTER_KEY_LOCKED_PATH)

    def get_master_key(self, password=None, recovery_code=None):
        if self.is_high_security_enabled():
            if not password and not recovery_code: raise ValueError("高安全模式已启用，需提供密码")
            return self.unlock_master_key(password, recovery_code)
        
        if os.path.exists(self.MASTER_KEY_PATH):
            with open(self.MASTER_KEY_PATH, 'rb') as f:
                return self.dpapi.unprotect(f.read())
        else:
            if os.path.exists(self.CONFIG_PATH) and self.load_settings().get('initialized'):
                raise RuntimeError("主密钥丢失或损坏，拒绝创建新密钥以保护数据安全。")
            if not os.path.exists(self.CONFIG_PATH): self.save_settings(self.load_settings())
            key = os.urandom(32)
            self._atomic_write(self.MASTER_KEY_PATH, self.dpapi.protect(key))
            return key

    def _create_locked_blob(self, master_key, password, recovery_code):
        salt = os.urandom(16)
        kek_pwd = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)
        kek_rec = hashlib.scrypt(recovery_code.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)
        enc_by_pwd = encrypt_data(master_key, kek_pwd)
        enc_by_rec = encrypt_data(master_key, kek_rec)
        return self.LOCKED_MAGIC + salt + struct.pack('>H', len(enc_by_pwd)) + enc_by_pwd + enc_by_rec

    def enable_high_security(self, password, recovery_code):
        if self.is_high_security_enabled(): return True
        if not os.path.exists(self.MASTER_KEY_PATH): raise ValueError("主密钥不存在")
        master_key = self.dpapi.unprotect(open(self.MASTER_KEY_PATH, 'rb').read())
        
        blob = self._create_locked_blob(master_key, password, recovery_code)
        
        test_pwd = self._unlock_blob(blob, password=password)
        test_rec = self._unlock_blob(blob, recovery_code=recovery_code)
        if test_pwd != master_key or test_rec != master_key:
            raise ValueError("高安全配置自检失败，未启用。")

        self._atomic_write(self.MASTER_KEY_LOCKED_PATH, blob)
        os.remove(self.MASTER_KEY_PATH)
        
        s = self.load_settings()
        if 'recovery_code_encrypted_b64' in s:
            del s['recovery_code_encrypted_b64']
            self.save_settings(s)
        return True

    def update_high_security_password(self, master_key, new_pwd, recovery_code):
        if not self.is_high_security_enabled(): return
        blob = self._create_locked_blob(master_key, new_pwd, recovery_code)
        self._atomic_write(self.MASTER_KEY_LOCKED_PATH, blob)
        
        # 核心修复 R2：重封成功后立即从 config.dat 中删除恢复码，杜绝 DPAPI 后门
        s = self.load_settings()
        if 'recovery_code_encrypted_b64' in s:
            del s['recovery_code_encrypted_b64']
            self.save_settings(s)

    def unlock_master_key(self, password=None, recovery_code=None):
        if not os.path.exists(self.MASTER_KEY_LOCKED_PATH): raise ValueError("未启用")
        blob = open(self.MASTER_KEY_LOCKED_PATH, 'rb').read()
        return self._unlock_blob(blob, password, recovery_code)

    def _unlock_blob(self, blob, password=None, recovery_code=None):
        salt = blob[4:20]
        pwd_len = struct.unpack('>H', blob[20:22])[0]
        enc_by_pwd = blob[22:22+pwd_len]
        enc_by_rec = blob[22+pwd_len:]
        
        if password:
            kek = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)
            try: return decrypt_data(enc_by_pwd, kek)
            except Exception: raise ValueError("主密码错误")
        if recovery_code:
            kek = hashlib.scrypt(recovery_code.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)
            try: return decrypt_data(enc_by_rec, kek)
            except Exception: raise ValueError("恢复代码无效")
        raise ValueError("解锁失败")

    def disable_high_security(self, master_key):
        if not self.is_high_security_enabled(): return True
        self._atomic_write(self.MASTER_KEY_PATH, self.dpapi.protect(master_key))
        os.remove(self.MASTER_KEY_LOCKED_PATH)
        return True

    @staticmethod
    def _atomic_write(path, data):
        fd, temp_path = tempfile.mkstemp(prefix='.sv-', dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                try: os.remove(temp_path)
                except OSError: pass

    def load_settings(self):
        if self._settings_cache is not None: return self._settings_cache
        if os.path.exists(self.CONFIG_PATH):
            try:
                data = self.dpapi.unprotect(open(self.CONFIG_PATH, 'rb').read())
                parsed = json.loads(data.decode('utf-8'))
                if not isinstance(parsed, dict): raise ValueError("配置根节点必须是对象")
                self._settings_cache = parsed
                return self._settings_cache
            except Exception as exc: raise RuntimeError("安全配置损坏。") from exc
        if os.path.exists(self.MASTER_KEY_PATH) or self.is_high_security_enabled():
            raise RuntimeError("检测到密钥但配置缺失。")
        self._settings_cache = {}
        return self._settings_cache

    def save_settings(self, settings_dict):
        self._atomic_write(self.CONFIG_PATH, self.dpapi.protect(json.dumps(settings_dict).encode('utf-8')))
        self._settings_cache = dict(settings_dict)

    def get_secret_dir(self):
        return os.path.abspath(self.load_settings().get('secret_dir') or DEFAULT_SECRET_DIR)

    def set_secret_dir(self, new_dir):
        s = dict(self.load_settings())
        s['secret_dir'] = os.path.abspath(new_dir)
        self.save_settings(s)