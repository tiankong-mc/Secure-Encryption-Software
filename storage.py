import os, json, shutil, uuid, zipfile, tempfile, struct, time, hashlib, stat, re, datetime, hmac
from io import BytesIO
from collections import Counter
from crypto import encrypt_data, decrypt_data, generate_key
from settings import SettingsManager, DEFAULT_SECRET_DIR

MAGIC = b'SVLT'
VAULT_VERSION = 1
ENCRYPTED_FILE_KEY_SIZE = 12 + 32 + 16
MIN_ENCRYPTED_DATA_SIZE = 12 + 16
BACKUP_KEY_MAGIC = b'SVBK1'
BACKUP_MEMBER_ALLOWLIST = ('meta.json', 'index.enc', 'migration.key', 'auth.enc')
MAX_BACKUP_MEMBERS = 10000
MAX_BACKUP_BYTES = 8 * 1024 ** 3
MAX_BACKUP_FILE_BYTES = 1024 ** 3
MAX_BACKUP_METADATA_BYTES = 16 * 1024 ** 2
BACKUP_VAULT_NAME = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\.vault\Z')
DESTROY_CHUNK_SIZE = 1024 * 1024

class StorageManager:
    def __init__(self, settings_manager=None, master_key=None):
        self.settings = settings_manager or SettingsManager()
        self.master_key = master_key if master_key else self.settings.get_master_key()
        self.SECRET_DIR = self.settings.get_secret_dir()
        self.INDEX_PATH = os.path.join(self.SECRET_DIR, 'index.enc')
        self.INDEX_BACKUP_PATH = os.path.join(self.SECRET_DIR, 'index.enc.bak')
        self.LOG_PATH = os.path.join(self.SECRET_DIR, 'securevault.log')
        self.HISTORY_DIR = os.path.join(self.SECRET_DIR, 'history')
        os.makedirs(self.SECRET_DIR, exist_ok=True)
        os.makedirs(self.HISTORY_DIR, exist_ok=True)
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(self.SECRET_DIR, 2)
        except Exception:
            pass
        self.index_recovered = False
        self.index = []
        self.folders = {}
        self._load_index()
        self._ensure_tags_list()
        self._cleanup_history()

    def log(self, message):
        try:
            if not self.settings.load_settings().get('log_enabled', True):
                return
            with open(self.LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
        except Exception:
            pass

    def get_log_content(self):
        if os.path.exists(self.LOG_PATH):
            with open(self.LOG_PATH, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    def get_log_size(self):
        if os.path.exists(self.LOG_PATH):
            return round(os.path.getsize(self.LOG_PATH) / (1024 * 1024), 2)
        return 0

    def clear_log(self):
        if os.path.exists(self.LOG_PATH):
            os.remove(self.LOG_PATH)

    def _ensure_tags_list(self):
        modified = False
        for entry in self.index:
            if 'folder_path' not in entry:
                entry['folder_path'] = ""
                modified = True
            if 'is_advanced' not in entry:
                entry['is_advanced'] = False
                modified = True
            if 'is_editable' not in entry:
                entry['is_editable'] = False
                modified = True
            if 'type' not in entry:
                ext = (entry.get('ext') or '').lower()
                entry['type'] = self._get_file_type(ext)
                modified = True
            if 'second_auth_methods' not in entry:
                entry['second_auth_methods'] = []
                modified = True
        if modified:
            self._save_index()

    def _load_index(self):
        if os.path.exists(self.INDEX_PATH):
            try:
                with open(self.INDEX_PATH, 'rb') as f:
                    data = decrypt_data(f.read(), self.master_key)
                    parsed = json.loads(data.decode('utf-8'))
                    if isinstance(parsed, dict):
                        self.index = parsed.get('files', [])
                        self.folders = parsed.get('folders', {})
                    else:
                        self.index = parsed
                        self.folders = {}
            except Exception:
                if os.path.exists(self.INDEX_BACKUP_PATH):
                    try:
                        with open(self.INDEX_BACKUP_PATH, 'rb') as f:
                            data = decrypt_data(f.read(), self.master_key)
                            parsed = json.loads(data.decode('utf-8'))
                            self.index = parsed.get('files', []) if isinstance(parsed, dict) else parsed
                            self.folders = parsed.get('folders', {}) if isinstance(parsed, dict) else {}
                            shutil.copy2(self.INDEX_BACKUP_PATH, self.INDEX_PATH)
                            self.index_recovered = True
                    except Exception as e:
                        raise RuntimeError(f"保险库索引及备份均损坏: {e}")
                else:
                    raise RuntimeError("保险库索引损坏，且无可用备份。")

    def _save_index(self):
        data = json.dumps({'files': self.index, 'folders': self.folders}).encode('utf-8')
        encrypted = encrypt_data(data, self.master_key)
        temp_path = self.INDEX_PATH + '.tmp'
        try:
            with open(temp_path, 'wb') as f:
                f.write(encrypted)
                f.flush()
                os.fsync(f.fileno())
            if os.path.exists(self.INDEX_PATH):
                try:
                    shutil.copy2(self.INDEX_PATH, self.INDEX_BACKUP_PATH)
                except OSError:
                    pass
            os.replace(temp_path, self.INDEX_PATH)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _serialize_vault(self, encrypted_file_key, encrypted_content):
        return MAGIC + struct.pack('B', VAULT_VERSION) + struct.pack('>I', len(encrypted_file_key)) + encrypted_file_key + encrypted_content

    def _deserialize_vault(self, data):
        if len(data) < 9 + ENCRYPTED_FILE_KEY_SIZE + MIN_ENCRYPTED_DATA_SIZE:
            raise ValueError("数据太短")
        if data[:4] != MAGIC or data[4] != VAULT_VERSION:
            raise ValueError("无效格式")
        key_len = struct.unpack('>I', data[5:9])[0]
        if key_len != ENCRYPTED_FILE_KEY_SIZE:
            raise ValueError("密钥长度错误")
        return data[9:9+key_len], data[9+key_len:]

    def _get_file_type(self, ext):
        if ext in ['.txt', '.md', '.py', '.json', '.xml', '.html', '.css', '.js', '.csv', '.log']:
            return 'text'
        elif ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico', '.webp']:
            return 'image'
        elif ext in ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v']:
            return 'video'
        elif ext in ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma']:
            return 'audio'
        elif ext in ['.docx', '.doc', '.pdf', '.odt', '.rtf']:
            return 'document'
        return 'other'

    def is_text_file(self, filename):
        return self._get_file_type(os.path.splitext(filename)[1].lower()) == 'text'

    def create_folder(self, path, is_advanced=False, second_auth_methods=None):
        if not path or path in self.folders:
            return False
        self.folders[path] = {
            'is_advanced': is_advanced,
            'second_auth_methods': second_auth_methods or [],
            'created_at': datetime.datetime.now().isoformat()
        }
        self._save_index()
        return True

    def delete_folder(self, path, destroy=False):
        for entry in [e for e in self.index if e.get('folder_path') == path or e.get('folder_path', '').startswith(path + '/')]:
            self.remove_entry(entry['id'], destroy=destroy)
        for f in [f for f in self.folders if f == path or f.startswith(path + '/')]:
            del self.folders[f]
        self._save_index()

    def rename_folder(self, old_path, new_path):
        if old_path not in self.folders or new_path in self.folders:
            return False
        self.folders[new_path] = self.folders.pop(old_path)
        for f in list(self.folders.keys()):
            if f.startswith(old_path + '/'):
                self.folders[f.replace(old_path, new_path, 1)] = self.folders.pop(f)
        for entry in self.index:
            if entry.get('folder_path') == old_path:
                entry['folder_path'] = new_path
            elif entry.get('folder_path', '').startswith(old_path + '/'):
                entry['folder_path'] = entry['folder_path'].replace(old_path, new_path, 1)
        self._save_index()
        return True

    def move_file_to_folder(self, entry_id, target_folder_path):
        for entry in self.index:
            if entry['id'] == entry_id:
                entry['folder_path'] = target_folder_path
                self._save_index()
                return True
        return False

    def add_file(self, local_path, folder_path="", user_dest=None, is_advanced=False, is_editable=False, second_auth_methods=None, delete_source=False):
        if os.path.getsize(local_path) > 2 * 1024 * 1024 * 1024:
            raise ValueError("文件过大，暂不支持超过 2GB 的文件")
        with open(local_path, 'rb') as f:
            plain = f.read()
        file_key = generate_key()
        data_pack = self._serialize_vault(encrypt_data(file_key, self.master_key), encrypt_data(plain, file_key))
        uid = str(uuid.uuid4())
        secret_path = os.path.join(self.SECRET_DIR, uid + '.vault')
        try:
            with open(secret_path + '.tmp', 'wb') as f:
                f.write(data_pack)
                f.flush()
                os.fsync(f.fileno())
            os.replace(secret_path + '.tmp', secret_path)
            ext = os.path.splitext(local_path)[1].lower()
            self.index.append({
                'id': uid,
                'original_name': os.path.basename(local_path),
                'secret_path': secret_path,
                'user_path': None,
                'folder_path': folder_path,
                'is_advanced': bool(is_advanced),
                'is_editable': bool(is_editable),
                'second_auth_methods': list(second_auth_methods or []),
                'type': self._get_file_type(ext),
                'ext': ext,
                'created_at': datetime.datetime.now().isoformat(timespec='seconds'),
            })
            self._save_index()
        except Exception:
            if os.path.exists(secret_path):
                os.remove(secret_path)
            raise
        delete_error = None
        if delete_source:
            try:
                os.remove(local_path)
            except OSError as e:
                delete_error = str(e)
        return {'uid': uid, 'delete_error': delete_error}

    def get_file_data(self, entry_id):
        for entry in self.index:
            if entry['id'] == entry_id:
                with open(entry['secret_path'], 'rb') as f:
                    encrypted_file_key, encrypted_content = self._deserialize_vault(f.read())
                return decrypt_data(encrypted_content, decrypt_data(encrypted_file_key, self.master_key))
        raise KeyError("记录不存在")

    def get_all_entries(self):
        return self.index

    def get_entry_by_id(self, entry_id):
        for entry in self.index:
            if entry['id'] == entry_id:
                return entry
        return None

    def remove_entry(self, entry_id, destroy=False):
        target_entry = self.get_entry_by_id(entry_id)
        if not target_entry:
            return False
        self.index = [e for e in self.index if e['id'] != entry_id]
        try:
            self._save_index()
        except Exception:
            self.index.append(target_entry)
            raise
        try:
            if os.path.exists(target_entry['secret_path']):
                if destroy:
                    size = os.path.getsize(target_entry['secret_path'])
                    with open(target_entry['secret_path'], 'r+b') as f:
                        for _ in range(3):
                            f.seek(0)
                            remaining = size
                            while remaining > 0:
                                n = min(DESTROY_CHUNK_SIZE, remaining)
                                f.write(os.urandom(n))
                                remaining -= n
                            f.flush()
                            os.fsync(f.fileno())
                os.remove(target_entry['secret_path'])
        except OSError as e:
            self.log(f"文件物理删除失败: {e}")
        return True

    def update_file_content(self, entry_id, new_data):
        entry = self.get_entry_by_id(entry_id)
        if not entry or not entry.get('is_editable'):
            raise ValueError("该文件不允许编辑")
        hist_path = os.path.join(self.HISTORY_DIR, f"{entry['id']}_{int(time.time()*1000)}.vault")
        try:
            shutil.copy2(entry['secret_path'], hist_path)
        except Exception:
            pass
        file_key = generate_key()
        data_pack = self._serialize_vault(encrypt_data(file_key, self.master_key), encrypt_data(new_data, file_key))
        with open(entry['secret_path'] + '.tmp', 'wb') as f:
            f.write(data_pack)
            f.flush()
            os.fsync(f.fileno())
        os.replace(entry['secret_path'] + '.tmp', entry['secret_path'])
        self._cleanup_history()

    def get_file_history(self, entry_id):
        now = time.time()
        history = []
        for name in os.listdir(self.HISTORY_DIR):
            if name.startswith(entry_id + "_"):
                try:
                    ts = int(name.split('_')[1].split('.')[0]) / 1000
                    if now - ts <= 3 * 86400:
                        history.append((ts, os.path.join(self.HISTORY_DIR, name)))
                except Exception:
                    pass
        return sorted(history, reverse=True)

    def rollback_file(self, entry_id, hist_path):
        entry = self.get_entry_by_id(entry_id)
        if not entry or not os.path.exists(hist_path):
            raise ValueError("备份不存在")
        shutil.copy2(hist_path, entry['secret_path'])

    def _cleanup_history(self):
        now = time.time()
        for name in os.listdir(self.HISTORY_DIR):
            try:
                if now - (int(name.split('_')[1].split('.')[0]) / 1000) > 3 * 86400:
                    os.remove(os.path.join(self.HISTORY_DIR, name))
            except Exception:
                pass

    def export_folder_as_zip(self, folder_path, zip_path):
        folder_name = os.path.basename(folder_path) or "Root_Folder"
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for entry in self.index:
                    e_path = entry.get('folder_path', '')
                    if e_path == folder_path or e_path.startswith(folder_path + '/'):
                        rel = os.path.relpath(e_path, folder_path).replace('\\', '/')
                        if rel == '.':
                            rel = ""
                        arcname = f"{folder_name}/{rel}/{entry['original_name']}.vault" if rel else f"{folder_name}/{entry['original_name']}.vault"
                        zf.write(entry['secret_path'], arcname)
                for f_path in self.folders:
                    if f_path.startswith(folder_path + '/'):
                        rel = os.path.relpath(f_path, folder_path).replace('\\', '/')
                        zf.writestr(f"{folder_name}/{rel}/.keep", "")
        except Exception as e:
            if os.path.exists(zip_path):
                os.remove(zip_path)
            raise e

    def import_zip_folder(self, zip_path, original_name="Imported_Folder"):
        with zipfile.ZipFile(zip_path, 'r') as zf:
            if sum(i.file_size for i in zf.infolist()) > MAX_BACKUP_BYTES or len(zf.infolist()) > MAX_BACKUP_MEMBERS:
                raise ValueError("压缩包过大")
            temp_dir = tempfile.mkdtemp()
            try:
                zf.extractall(temp_dir)
                for root, dirs, files in os.walk(temp_dir):
                    rel_path = os.path.relpath(root, temp_dir).replace('\\', '/')
                    if rel_path == '.':
                        rel_path = ""
                    current_folder = f"{original_name}/{rel_path}".strip('/') if rel_path else original_name
                    self.create_folder(current_folder)
                    for f in files:
                        if f.endswith('.vault'):
                            self.import_vault_file(os.path.join(root, f), f[:-6], target_folder=current_folder)
            finally:
                shutil.rmtree(temp_dir)

    def import_vault_file(self, vault_path, original_name=None, target_folder="", is_advanced=False, second_auth_methods=None):
        with open(vault_path, 'rb') as f:
            data_pack = f.read()
        encrypted_file_key, encrypted_content = self._deserialize_vault(data_pack)
        decrypt_data(encrypted_content, decrypt_data(encrypted_file_key, self.master_key))
        uid = str(uuid.uuid4())
        secret_path = os.path.join(self.SECRET_DIR, uid + '.vault')
        shutil.copy2(vault_path, secret_path)
        if original_name is None:
            original_name = os.path.basename(vault_path).replace('.vault', '')
        ext = os.path.splitext(original_name)[1].lower()
        self.index.append({
            'id': uid,
            'original_name': original_name,
            'secret_path': secret_path,
            'folder_path': target_folder,
            'is_advanced': is_advanced,
            'is_editable': False,
            'second_auth_methods': second_auth_methods or [],
            'type': self._get_file_type(ext),
            'ext': ext,
            'created_at': datetime.datetime.now().isoformat(timespec='seconds'),
        })
        self._save_index()
        return uid

    def get_storage_statistics(self):
        file_count = len(self.index)
        total_size = 0
        recent_30d = 0
        cutoff = datetime.datetime.now() - datetime.timedelta(days=30)
        for entry in self.index:
            if os.path.exists(entry['secret_path']):
                try:
                    total_size += os.path.getsize(entry['secret_path'])
                except OSError:
                    pass
            try:
                if datetime.datetime.fromisoformat(entry.get('created_at')) >= cutoff:
                    recent_30d += 1
            except Exception:
                pass
        directory_size = 0
        try:
            for name in os.listdir(self.SECRET_DIR):
                full = os.path.join(self.SECRET_DIR, name)
                if os.path.isfile(full):
                    directory_size += os.path.getsize(full)
        except OSError:
            pass
        return {
            'file_count': file_count,
            'total_size': total_size,
            'directory_size': directory_size,
            'recent_30d': recent_30d
        }

    def migrate_dir(self, new_dir):
        old_dir = self.SECRET_DIR
        new_dir = os.path.abspath(new_dir)
        if os.path.normcase(old_dir) == os.path.normcase(new_dir):
            return True
        os.makedirs(new_dir, exist_ok=True)
        tasks = []
        for entry in self.index:
            for key in ('secret_path', 'user_path'):
                old_path = entry.get(key)
                if not old_path or not os.path.exists(old_path):
                    continue
                if os.path.normcase(os.path.dirname(old_path)) == os.path.normcase(new_dir):
                    continue
                base = os.path.basename(old_path)
                new_path = os.path.join(new_dir, base)
                if os.path.exists(new_path):
                    stem, ext = os.path.splitext(base)
                    counter = 1
                    while os.path.exists(new_path):
                        new_path = os.path.join(new_dir, f"{stem}_{counter}{ext}")
                        counter += 1
                tasks.append((old_path, new_path, entry, key))
        orig_entry_paths = [(e, k, e.get(k)) for e in self.index for k in ('secret_path', 'user_path')]
        copied = []
        copied_aux = []
        failed_cleanup = []
        try:
            for old_path, new_path, entry, key in tasks:
                shutil.copy2(old_path, new_path)
                copied.append((old_path, new_path, entry, key))
            new_hist = os.path.join(new_dir, 'history')
            if os.path.exists(self.HISTORY_DIR):
                shutil.copytree(self.HISTORY_DIR, new_hist, dirs_exist_ok=True)
                copied_aux.append(new_hist)
            for name in ('index.enc', 'index.enc.bak', 'securevault.log'):
                src = os.path.join(old_dir, name)
                dst = os.path.join(new_dir, name)
                if os.path.exists(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
                    copied_aux.append(dst)
            for _, new_path, entry, key in copied:
                entry[key] = new_path
            self.SECRET_DIR = new_dir
            self.INDEX_PATH = os.path.join(new_dir, 'index.enc')
            self.INDEX_BACKUP_PATH = os.path.join(new_dir, 'index.enc.bak')
            self.LOG_PATH = os.path.join(new_dir, 'securevault.log')
            self.HISTORY_DIR = new_hist
            self._save_index()
            self.settings.set_secret_dir(new_dir)
        except Exception as e:
            self.SECRET_DIR = old_dir
            self.INDEX_PATH = os.path.join(old_dir, 'index.enc')
            self.INDEX_BACKUP_PATH = os.path.join(old_dir, 'index.enc.bak')
            self.LOG_PATH = os.path.join(old_dir, 'securevault.log')
            self.HISTORY_DIR = os.path.join(old_dir, 'history')
            for entry, key, val in orig_entry_paths:
                entry[key] = val
            for _, new_path, _, _ in copied:
                try:
                    if os.path.exists(new_path):
                        os.remove(new_path)
                except OSError as ce:
                    failed_cleanup.append((new_path, str(ce)))
            for dst in copied_aux:
                try:
                    if os.path.isdir(dst):
                        shutil.rmtree(dst, ignore_errors=True)
                    elif os.path.exists(dst):
                        os.remove(dst)
                except OSError as ce:
                    failed_cleanup.append((dst, str(ce)))
            raise RuntimeError(f"迁移失败: {e}\n残留文件: {len(failed_cleanup)}")
        for old_path, _, _, _ in copied:
            try:
                if os.path.normcase(os.path.dirname(old_path)) != os.path.normcase(new_dir):
                    os.remove(old_path)
            except OSError:
                pass
        for name in ('index.enc', 'index.enc.bak', 'securevault.log'):
            p = os.path.join(old_dir, name)
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        return True

    @staticmethod
    def _validate_backup_members(zf):
        seen = set(); total = 0
        if len(zf.infolist()) > MAX_BACKUP_MEMBERS: raise ValueError("文件数量异常")
        for info in zf.infolist():
            name = info.filename
            if (name not in BACKUP_MEMBER_ALLOWLIST and not BACKUP_VAULT_NAME.fullmatch(name)) or stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF) or info.is_dir():
                raise ValueError("包含不安全文件")
            limit = MAX_BACKUP_METADATA_BYTES if name in BACKUP_MEMBER_ALLOWLIST else MAX_BACKUP_FILE_BYTES
            if info.file_size < 0 or info.file_size > limit: raise ValueError("文件超过限制")
            total += info.file_size
            if total > MAX_BACKUP_BYTES: raise ValueError("解压总大小超过限制")
            if name.casefold() in seen: raise ValueError("重复文件")
            seen.add(name.casefold())
        if not {'meta.json', 'index.enc'}.issubset(seen): raise ValueError("缺少必要文件")

    def export_vault(self, export_path, password, auth_settings=None):
        if len(password) < 8: raise ValueError("备份密码至少 8 位")
        temp_dir = tempfile.mkdtemp()
        try:
            backup_index = []
            for entry in self.index:
                if not re.fullmatch(r'[0-9a-f\-]{36}', entry['id']): raise ValueError("ID 格式错误")
                archive_name = entry['id'] + '.vault'
                shutil.copy2(entry['secret_path'], os.path.join(temp_dir, archive_name))
                be = dict(entry); be['secret_path'] = archive_name; be['user_path'] = None
                backup_index.append(be)
            with open(os.path.join(temp_dir, 'index.enc'), 'wb') as f:
                f.write(encrypt_data(json.dumps({'files': backup_index, 'folders': self.folders}).encode('utf-8'), self.master_key))
            if auth_settings:
                with open(os.path.join(temp_dir, 'auth.enc'), 'wb') as f:
                    f.write(encrypt_data(json.dumps(auth_settings, ensure_ascii=False).encode('utf-8'), self.master_key))
            with open(os.path.join(temp_dir, 'meta.json'), 'w', encoding='utf-8') as f:
                json.dump({'version': '2.7', 'portable': True}, f)
            salt = os.urandom(16)
            backup_key = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
            with open(os.path.join(temp_dir, 'migration.key'), 'wb') as f:
                f.write(BACKUP_KEY_MAGIC); f.write(salt); f.write(encrypt_data(self.master_key, backup_key))
            import pyzipper
            with pyzipper.AESZipFile(export_path, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
                zf.setpassword(password.encode())
                for root, _, files in os.walk(temp_dir):
                    for name in files:
                        full = os.path.join(root, name)
                        zf.write(full, os.path.relpath(full, temp_dir))
        finally:
            shutil.rmtree(temp_dir)

    def import_vault(self, import_path, password=None):
        if not password: raise ValueError("备份密码不能为空")
        temp_dir = tempfile.mkdtemp()
        created_paths = []
        old_index = list(self.index); old_folders = dict(self.folders)
        auth_settings = None; imported = []
        try:
            import pyzipper
            try:
                with pyzipper.AESZipFile(import_path, 'r') as zf:
                    self._validate_backup_members(zf)
                    zf.setpassword(password.encode())
                    zf.extractall(temp_dir)
            except ValueError:
                raise
            except Exception as e:
                raise ValueError("备份密码错误或备份文件损坏") from e

            mk_path = os.path.join(temp_dir, 'migration.key')
            if not os.path.exists(mk_path): raise ValueError("缺少密码校验文件")
            with open(mk_path, 'rb') as f: wrapped = f.read()
            n = len(BACKUP_KEY_MAGIC)
            if not wrapped.startswith(BACKUP_KEY_MAGIC) or len(wrapped) < n + 16 + 12 + 16:
                raise ValueError("密码校验文件无效")
            salt = wrapped[n:n + 16]
            bk = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
            try:
                backup_master_key = decrypt_data(wrapped[n + 16:], bk)
            except Exception as e:
                raise ValueError("备份密码错误") from e
            if len(backup_master_key) != 32: raise ValueError("备份主密钥无效")

            index_path = os.path.join(temp_dir, 'index.enc')
            with open(index_path, 'rb') as f:
                parsed = json.loads(decrypt_data(f.read(), backup_master_key).decode('utf-8'))
            entries = parsed.get('files', []) if isinstance(parsed, dict) else parsed
            folders = parsed.get('folders', {}) if isinstance(parsed, dict) else {}

            auth_path = os.path.join(temp_dir, 'auth.enc')
            if os.path.exists(auth_path):
                with open(auth_path, 'rb') as f:
                    auth_settings = json.loads(decrypt_data(f.read(), backup_master_key).decode('utf-8'))

            for entry in entries:
                original_name = entry.get('original_name', '')
                if not isinstance(original_name, str) or '\x00' in original_name:
                    raise ValueError("备份索引中的原文件名无效")
                vault_name = entry.get('secret_path', '')
                if not BACKUP_VAULT_NAME.fullmatch(vault_name): raise ValueError("备份索引中的文件路径无效")
                src = os.path.join(temp_dir, vault_name)
                if not os.path.isfile(src): raise ValueError("备份缺少文件")
                with open(src, 'rb') as f: data_pack = f.read()
                enc_k, enc_c = self._deserialize_vault(data_pack)
                fk = decrypt_data(enc_k, backup_master_key)
                decrypt_data(enc_c, fk)
                new_id = str(uuid.uuid4())
                dest = os.path.join(self.SECRET_DIR, new_id + '.vault')
                created_paths.append(dest)
                if backup_master_key != self.master_key:
                    data_pack = self._serialize_vault(encrypt_data(fk, self.master_key), enc_c)
                with open(dest, 'wb') as f:
                    f.write(data_pack); f.flush(); os.fsync(f.fileno())
                entry.update({'id': new_id, 'secret_path': dest, 'user_path': None})
                imported.append(entry)

            self.index.extend(imported)
            for fp in folders: self.folders[fp] = folders[fp]
            self._save_index()
            return {'imported_count': len(imported), 'auth_settings': auth_settings}
        except Exception:
            self.index = old_index
            self.folders = old_folders
            for p in created_paths:
                try:
                    if os.path.exists(p): os.remove(p)
                except OSError: pass
            raise
        finally:
            shutil.rmtree(temp_dir)
