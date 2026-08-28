import os, json, shutil, uuid, pickle, zipfile, tempfile, struct, time
from crypto import encrypt_data, decrypt_data, generate_key
from settings import SettingsManager
from backup import BackupManager

MAGIC = b'SVLT'
VAULT_VERSION = 1

class StorageManager:
    SECRET_DIR = r'C:\ProgramData\SecureVault'
    INDEX_PATH = os.path.join(SECRET_DIR, 'index.enc')
    INDEX_BACKUP_PATH = os.path.join(SECRET_DIR, 'index.enc.bak')
    LOG_PATH = os.path.join(SECRET_DIR, 'securevault.log')

    def __init__(self):
        self.settings = SettingsManager()
        self.master_key = self.settings.get_master_key()
        os.makedirs(self.SECRET_DIR, exist_ok=True)
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(self.SECRET_DIR, 2)
        except:
            pass
        self.index = self._load_index()
        self._ensure_tags_list()

    # ---------- 日志 ----------
    def log(self, message):
        if not self.settings.load_settings().get('log_enabled', True):
            return
        try:
            with open(self.LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
        except:
            pass

    def get_log_content(self):
        if os.path.exists(self.LOG_PATH):
            with open(self.LOG_PATH, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    def get_log_size(self):
        if os.path.exists(self.LOG_PATH):
            size = os.path.getsize(self.LOG_PATH)
            return round(size / (1024 * 1024), 2)
        return 0

    def clear_log(self):
        if os.path.exists(self.LOG_PATH):
            os.remove(self.LOG_PATH)

    # ---------- 索引管理 ----------
    def _ensure_tags_list(self):
        modified = False
        for entry in self.index:
            if 'tags' not in entry:
                entry['tags'] = []
                modified = True
        if modified:
            self._save_index()

    def _load_index(self):
        if os.path.exists(self.INDEX_PATH):
            try:
                with open(self.INDEX_PATH, 'rb') as f:
                    encrypted = f.read()
                data = decrypt_data(encrypted, self.master_key)
                return json.loads(data.decode('utf-8'))
            except Exception as e:
                if os.path.exists(self.INDEX_BACKUP_PATH):
                    raise RuntimeError(f"索引文件损坏，但存在备份文件，请手动恢复或联系开发者。原始错误: {e}")
                else:
                    raise RuntimeError(f"保险库索引损坏，无法加载。错误: {e}")
        return []

    def _save_index(self):
        data = json.dumps(self.index).encode('utf-8')
        encrypted = encrypt_data(data, self.master_key)
        temp_path = self.INDEX_PATH + '.tmp'
        with open(temp_path, 'wb') as f:
            f.write(encrypted)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(self.INDEX_PATH):
            shutil.copy2(self.INDEX_PATH, self.INDEX_BACKUP_PATH)
        os.replace(temp_path, self.INDEX_PATH)

    # ---------- 序列化/反序列化加密文件 ----------
    def _serialize_vault(self, encrypted_file_key, encrypted_content):
        return MAGIC + struct.pack('B', VAULT_VERSION) + struct.pack('>I', len(encrypted_file_key)) + encrypted_file_key + encrypted_content

    def _deserialize_vault(self, data):
        if len(data) < 4 + 1 + 4:
            raise ValueError("数据太短，不是有效的新格式")
        magic = data[:4]
        if magic != MAGIC:
            raise ValueError("无效的魔术字")
        ver = data[4]
        if ver != 1:
            raise ValueError(f"不支持的版本: {ver}")
        key_len = struct.unpack('>I', data[5:9])[0]
        if len(data) < 9 + key_len:
            raise ValueError("数据截断")
        encrypted_file_key = data[9:9+key_len]
        encrypted_content = data[9+key_len:]
        return encrypted_file_key, encrypted_content

    # ---------- 文件管理 ----------
    def add_file(self, local_path, user_dest=None, is_advanced=False, second_auth_methods=None, tags=None):
        with open(local_path, 'rb') as f:
            plain = f.read()
        file_key = generate_key()
        encrypted_content = encrypt_data(plain, file_key)
        encrypted_file_key = encrypt_data(file_key, self.master_key)
        data_pack = self._serialize_vault(encrypted_file_key, encrypted_content)
        uid = str(uuid.uuid4())
        secret_filename = uid + '.vault'
        secret_path = os.path.join(self.SECRET_DIR, secret_filename)
        with open(secret_path, 'wb') as f:
            f.write(data_pack)
        user_path = None
        if user_dest:
            os.makedirs(user_dest, exist_ok=True)
            user_path = os.path.join(user_dest, os.path.basename(local_path) + '.vault')
            shutil.copy2(secret_path, user_path)
        ext = os.path.splitext(local_path)[1].lower()
        ftype = self._get_file_type(ext)
        entry = {
            'id': uid,
            'original_name': os.path.basename(local_path),
            'secret_path': secret_path,
            'user_path': user_path,
            'is_advanced': is_advanced,
            'second_auth_methods': second_auth_methods or [],
            'type': ftype,
            'ext': ext,
            'tags': tags or []
        }
        self.index.append(entry)
        self._save_index()
        return uid

    def _get_file_type(self, ext):
        if ext in ['.txt', '.md', '.py', '.json', '.xml', '.html', '.css', '.js', '.csv']:
            return 'text'
        elif ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico', '.webp']:
            return 'image'
        elif ext in ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v']:
            return 'video'
        elif ext in ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma']:
            return 'audio'
        elif ext in ['.docx', '.doc', '.pdf', '.odt', '.rtf']:
            return 'document'
        else:
            return 'other'

    def get_file_data(self, entry_id):
        for entry in self.index:
            if entry['id'] == entry_id:
                path = entry['secret_path']
                if not os.path.exists(path) and entry['user_path'] and os.path.exists(entry['user_path']):
                    path = entry['user_path']
                if not os.path.exists(path):
                    raise FileNotFoundError(f"文件不存在: {path}")
                with open(path, 'rb') as f:
                    data_pack = f.read()
                try:
                    encrypted_file_key, encrypted_content = self._deserialize_vault(data_pack)
                except ValueError:
                    # 回退旧 pickle 格式
                    try:
                        encrypted_file_key, encrypted_content = pickle.loads(data_pack)
                    except Exception as e:
                        raise RuntimeError(f"无法解析文件 {path}: {e}")
                file_key = decrypt_data(encrypted_file_key, self.master_key)
                plain = decrypt_data(encrypted_content, file_key)
                return plain
        raise KeyError("记录不存在")

    def get_all_entries(self):
        return self.index

    def get_entry_by_id(self, entry_id):
        for entry in self.index:
            if entry['id'] == entry_id:
                return entry
        return None

    def remove_entry(self, entry_id, destroy=False):
        for i, entry in enumerate(self.index):
            if entry['id'] == entry_id:
                if destroy:
                    for p in [entry['secret_path'], entry['user_path']]:
                        if p and os.path.exists(p):
                            size = os.path.getsize(p)
                            with open(p, 'wb') as f:
                                for _ in range(3):
                                    f.seek(0)
                                    f.write(os.urandom(size))
                            os.remove(p)
                else:
                    for p in [entry['secret_path'], entry['user_path']]:
                        if p and os.path.exists(p):
                            os.remove(p)
                del self.index[i]
                self._save_index()
                return True
        return False

    def import_vault_file(self, vault_path, original_name=None, is_advanced=False, second_auth_methods=None, tags=None):
        if not os.path.exists(vault_path):
            raise FileNotFoundError("文件不存在")
        with open(vault_path, 'rb') as f:
            data_pack = f.read()
        # 强制新格式
        try:
            encrypted_file_key, encrypted_content = self._deserialize_vault(data_pack)
        except ValueError:
            raise ValueError("不安全格式：此 .vault 文件为旧 pickle 格式，已被禁用。请使用迁移工具转换或重新加密。")
        try:
            decrypt_data(encrypted_file_key, self.master_key)
        except Exception as e:
            raise ValueError(f"无效的加密文件: {e}")
        uid = str(uuid.uuid4())
        secret_filename = uid + '.vault'
        secret_path = os.path.join(self.SECRET_DIR, secret_filename)
        shutil.copy2(vault_path, secret_path)
        if original_name is None:
            base = os.path.basename(vault_path)
            if base.endswith('.vault'):
                base = base[:-6]
            if not base:
                base = "unknown"
            original_name = base
        ext = os.path.splitext(original_name)[1].lower()
        ftype = self._get_file_type(ext)
        entry = {
            'id': uid,
            'original_name': original_name,
            'secret_path': secret_path,
            'user_path': None,
            'is_advanced': is_advanced,
            'second_auth_methods': second_auth_methods or [],
            'type': ftype,
            'ext': ext,
            'tags': tags or []
        }
        self.index.append(entry)
        self._save_index()
        return uid

    def get_all_vault_paths_with_names(self):
        result = []
        for entry in self.index:
            vault_path = entry['secret_path']
            if not os.path.exists(vault_path) and entry['user_path'] and os.path.exists(entry['user_path']):
                vault_path = entry['user_path']
            if os.path.exists(vault_path):
                display_name = entry['original_name'] + '.vault'
                result.append((vault_path, display_name))
        return result

    # ---------- 标签管理 ----------
    def get_all_tags(self):
        tags = set()
        for entry in self.index:
            tags.update(entry.get('tags', []))
        return sorted(tags)

    def add_tag_to_entry(self, entry_id, tag):
        entry = self.get_entry_by_id(entry_id)
        if entry and tag not in entry['tags']:
            entry['tags'].append(tag)
            self._save_index()
            return True
        return False

    def remove_tag_from_entry(self, entry_id, tag):
        entry = self.get_entry_by_id(entry_id)
        if entry and tag in entry['tags']:
            entry['tags'].remove(tag)
            self._save_index()
            return True
        return False

    def get_entries_by_tag(self, tag):
        return [entry for entry in self.index if tag in entry.get('tags', [])]

    # ---------- 保险库迁移 ----------
    def export_vault(self, export_path, password=None):
        temp_dir = tempfile.mkdtemp()
        try:
            for entry in self.index:
                src = entry['secret_path']
                if os.path.exists(src):
                    dest = os.path.join(temp_dir, os.path.basename(src))
                    shutil.copy2(src, dest)
            shutil.copy2(self.INDEX_PATH, os.path.join(temp_dir, 'index.enc'))
            meta = {'version': '2.0', 'timestamp': __import__('datetime').datetime.now().isoformat()}
            with open(os.path.join(temp_dir, 'meta.json'), 'w') as f:
                json.dump(meta, f)
            if password:
                import pyzipper
                with pyzipper.AESZipFile(export_path, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
                    zf.setpassword(password.encode())
                    for root, _, files in os.walk(temp_dir):
                        for file in files:
                            full_path = os.path.join(root, file)
                            arcname = os.path.relpath(full_path, temp_dir)
                            zf.write(full_path, arcname)
            else:
                import zipfile
                with zipfile.ZipFile(export_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                    for root, _, files in os.walk(temp_dir):
                        for file in files:
                            full_path = os.path.join(root, file)
                            arcname = os.path.relpath(full_path, temp_dir)
                            zf.write(full_path, arcname)
        finally:
            shutil.rmtree(temp_dir)

    def import_vault(self, import_path, password=None):
        temp_dir = tempfile.mkdtemp()
        try:
            try:
                import pyzipper
                with pyzipper.AESZipFile(import_path, 'r') as zf:
                    if password:
                        zf.setpassword(password.encode())
                    zf.extractall(temp_dir)
            except (RuntimeError, TypeError, pyzipper.BadPassword):
                import zipfile
                with zipfile.ZipFile(import_path, 'r') as zf:
                    zf.extractall(temp_dir)
            meta_path = os.path.join(temp_dir, 'meta.json')
            if not os.path.exists(meta_path):
                raise ValueError("无效的备份包：缺少 meta.json")
            for file in os.listdir(temp_dir):
                if file.endswith('.vault'):
                    shutil.copy2(os.path.join(temp_dir, file), self.SECRET_DIR)
            shutil.copy2(os.path.join(temp_dir, 'index.enc'), self.INDEX_PATH)
            self.index = self._load_index()
            self._ensure_tags_list()
        finally:
            shutil.rmtree(temp_dir)
        return True
