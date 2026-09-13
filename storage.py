import os, json, shutil, uuid, zipfile, tempfile, struct, time, hashlib, stat
from pathlib import PurePosixPath
from crypto import encrypt_data, decrypt_data, generate_key
from settings import SettingsManager, DEFAULT_SECRET_DIR

MAGIC = b'SVLT'
VAULT_VERSION = 1
ENCRYPTED_FILE_KEY_SIZE = 12 + 32 + 16
MIN_ENCRYPTED_DATA_SIZE = 12 + 16
BACKUP_KEY_MAGIC = b'SVBK1'


class StorageManager:
    def __init__(self, settings_manager=None):
        self.settings = settings_manager or SettingsManager()
        self.master_key = self.settings.get_master_key()

        # 路径从 settings 动态读取（可在设置中修改）
        self.SECRET_DIR = self.settings.get_secret_dir()
        self.INDEX_PATH = os.path.join(self.SECRET_DIR, 'index.enc')
        self.INDEX_BACKUP_PATH = os.path.join(self.SECRET_DIR, 'index.enc.bak')
        self.LOG_PATH = os.path.join(self.SECRET_DIR, 'securevault.log')

        os.makedirs(self.SECRET_DIR, exist_ok=True)
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(self.SECRET_DIR, 2)
        except:
            pass
        self.index_recovered = False
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

    @staticmethod
    def _validate_index(index):
        if not isinstance(index, list):
            raise ValueError("索引根节点必须是列表")
        required = ('id', 'original_name', 'secret_path')
        seen_ids = set()
        for entry in index:
            if not isinstance(entry, dict):
                raise ValueError("索引包含无效记录")
            if any(not isinstance(entry.get(key), str) or not entry[key]
                   for key in required):
                raise ValueError("索引记录缺少必要字段")
            if not isinstance(entry.get('tags', []), list):
                raise ValueError("索引标签格式无效")
            if not isinstance(entry.get('second_auth_methods', []), list):
                raise ValueError("索引验证方式格式无效")
            if entry['id'] in seen_ids:
                raise ValueError("索引包含重复文件 ID")
            seen_ids.add(entry['id'])
        return index

    def _load_index(self):
        if os.path.exists(self.INDEX_PATH):
            try:
                return self._read_index_file(self.INDEX_PATH)
            except Exception as primary_error:
                if os.path.exists(self.INDEX_BACKUP_PATH):
                    try:
                        index = self._read_index_file(self.INDEX_BACKUP_PATH)
                        shutil.copy2(self.INDEX_BACKUP_PATH, self.INDEX_PATH)
                        self.index_recovered = True
                        return index
                    except Exception as backup_error:
                        raise RuntimeError(
                            f"保险库索引及其备份均损坏。主索引错误: {primary_error}; "
                            f"备份错误: {backup_error}") from backup_error
                raise RuntimeError(f"保险库索引损坏，无法加载。错误: {primary_error}") from primary_error
        return []

    def _read_index_file(self, path):
        with open(path, 'rb') as f:
            encrypted = f.read()
        data = decrypt_data(encrypted, self.master_key)
        return self._validate_index(json.loads(data.decode('utf-8')))

    def _save_index(self):
        data = json.dumps(self.index).encode('utf-8')
        encrypted = encrypt_data(data, self.master_key)
        temp_path = self.INDEX_PATH + '.tmp'
        try:
            with open(temp_path, 'wb') as f:
                f.write(encrypted)
                f.flush()
                os.fsync(f.fileno())
            if os.path.exists(self.INDEX_PATH):
                shutil.copy2(self.INDEX_PATH, self.INDEX_BACKUP_PATH)
            os.replace(temp_path, self.INDEX_PATH)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    # ---------- 序列化 ----------
    def _serialize_vault(self, encrypted_file_key, encrypted_content):
        return MAGIC + struct.pack('B', VAULT_VERSION) + struct.pack('>I', len(encrypted_file_key)) + encrypted_file_key + encrypted_content

    def _deserialize_vault(self, data):
        if len(data) < 9 + ENCRYPTED_FILE_KEY_SIZE + MIN_ENCRYPTED_DATA_SIZE:
            raise ValueError("数据太短，不是有效的新格式")
        magic = data[:4]
        if magic != MAGIC:
            raise ValueError("无效的魔术字")
        ver = data[4]
        if ver != VAULT_VERSION:
            raise ValueError(f"不支持的版本: {ver}")
        key_len = struct.unpack('>I', data[5:9])[0]
        if key_len != ENCRYPTED_FILE_KEY_SIZE:
            raise ValueError("加密文件密钥长度无效")
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
        temp_secret_path = secret_path + '.tmp'
        user_path = None
        temp_user_path = None
        try:
            with open(temp_secret_path, 'wb') as f:
                f.write(data_pack)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_secret_path, secret_path)
            if user_dest:
                os.makedirs(user_dest, exist_ok=True)
                user_path = self._unique_user_path(
                    user_dest, os.path.basename(local_path) + '.vault')
                temp_user_path = user_path + f'.{uid}.tmp'
                shutil.copy2(secret_path, temp_user_path)
                os.replace(temp_user_path, user_path)
            ext = os.path.splitext(local_path)[1].lower()
            entry = {
                'id': uid,
                'original_name': os.path.basename(local_path),
                'secret_path': secret_path,
                'user_path': user_path,
                'is_advanced': bool(is_advanced),
                'second_auth_methods': list(second_auth_methods or []),
                'type': self._get_file_type(ext),
                'ext': ext,
                'tags': list(tags or [])
            }
            self.index.append(entry)
            self._save_index()
        except Exception:
            if self.index and self.index[-1].get('id') == uid:
                self.index.pop()
            for path in (temp_secret_path, secret_path, user_path, temp_user_path):
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            raise
        return uid

    @staticmethod
    def _unique_user_path(directory, filename):
        candidate = os.path.join(directory, filename)
        if not os.path.exists(candidate):
            return candidate
        stem, ext = os.path.splitext(filename)
        counter = 1
        while True:
            candidate = os.path.join(directory, f"{stem} ({counter}){ext}")
            if not os.path.exists(candidate):
                return candidate
            counter += 1

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
                user_path = entry.get('user_path')
                if not os.path.exists(path) and user_path and os.path.exists(user_path):
                    path = user_path
                if not os.path.exists(path):
                    raise FileNotFoundError(f"文件不存在: {path}")
                with open(path, 'rb') as f:
                    data_pack = f.read()
                encrypted_file_key, encrypted_content = self._deserialize_vault(data_pack)
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
                moved = []
                try:
                    for p in dict.fromkeys((entry['secret_path'], entry.get('user_path'))):
                        if p and os.path.exists(p):
                            staged = p + f'.delete-{uuid.uuid4().hex}'
                            os.replace(p, staged)
                            moved.append((p, staged))
                    del self.index[i]
                    self._save_index()
                except Exception:
                    if entry not in self.index:
                        self.index.insert(i, entry)
                    for original, staged in reversed(moved):
                        if os.path.exists(staged):
                            os.replace(staged, original)
                    raise
                for _, staged in moved:
                    try:
                        if destroy:
                            size = os.path.getsize(staged)
                            with open(staged, 'r+b') as f:
                                for _ in range(3):
                                    f.seek(0)
                                    f.write(os.urandom(size))
                                    f.flush()
                                    os.fsync(f.fileno())
                        os.remove(staged)
                    except OSError as e:
                        self.log(f"删除暂存文件失败: {staged} ({e})")
                return True
        return False

    def import_vault_file(self, vault_path, original_name=None, is_advanced=False, second_auth_methods=None, tags=None):
        if not os.path.exists(vault_path):
            raise FileNotFoundError("文件不存在")
        with open(vault_path, 'rb') as f:
            data_pack = f.read()
        try:
            encrypted_file_key, encrypted_content = self._deserialize_vault(data_pack)
        except ValueError:
            raise ValueError("不安全格式：旧 pickle 格式已被禁用。请用旧版解密后，再用当前版本重新加密。")
        try:
            file_key = decrypt_data(encrypted_file_key, self.master_key)
            decrypt_data(encrypted_content, file_key)
        except Exception as e:
            raise ValueError(f"无效的加密文件: {e}")
        uid = str(uuid.uuid4())
        secret_filename = uid + '.vault'
        secret_path = os.path.join(self.SECRET_DIR, secret_filename)
        temp_path = secret_path + '.tmp'
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
        try:
            shutil.copy2(vault_path, temp_path)
            os.replace(temp_path, secret_path)
            self.index.append(entry)
            self._save_index()
        except Exception:
            if self.index and self.index[-1].get('id') == uid:
                self.index.pop()
            for path in (temp_path, secret_path):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            raise
        return uid

    def get_all_vault_paths_with_names(self):
        result = []
        for entry in self.index:
            vault_path = entry['secret_path']
            user_path = entry.get('user_path')
            if not os.path.exists(vault_path) and user_path and os.path.exists(user_path):
                vault_path = user_path
            if os.path.exists(vault_path):
                result.append((vault_path, entry['original_name'] + '.vault'))
        return result

    # ---------- 标签 ----------
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

    # ---------- 保险库备份 ----------
    def export_vault(self, export_path, password=None):
        temp_dir = tempfile.mkdtemp()
        try:
            backup_index = []
            for entry in self.index:
                src = entry['secret_path']
                if not os.path.exists(src) and entry.get('user_path') and os.path.exists(entry['user_path']):
                    src = entry['user_path']
                if not os.path.exists(src):
                    raise FileNotFoundError(f"备份失败，文件不存在: {entry['original_name']}")
                archive_name = entry['id'] + '.vault'
                shutil.copy2(src, os.path.join(temp_dir, archive_name))
                backup_entry = dict(entry)
                backup_entry['secret_path'] = archive_name
                backup_entry['user_path'] = None
                backup_index.append(backup_entry)
            index_data = json.dumps(backup_index, ensure_ascii=False).encode('utf-8')
            with open(os.path.join(temp_dir, 'index.enc'), 'wb') as f:
                f.write(encrypt_data(index_data, self.master_key))
            meta = {
                'version': '2.1',
                'timestamp': __import__('datetime').datetime.now().isoformat(),
                'portable': bool(password),
            }
            with open(os.path.join(temp_dir, 'meta.json'), 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False)
            if password:
                salt = os.urandom(16)
                backup_key = hashlib.scrypt(password.encode('utf-8'), salt=salt,
                                            n=2 ** 14, r=8, p=1, dklen=32)
                wrapped = BACKUP_KEY_MAGIC + salt + encrypt_data(self.master_key, backup_key)
                with open(os.path.join(temp_dir, 'migration.key'), 'wb') as f:
                    f.write(wrapped)
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

    @staticmethod
    def _validate_backup_members(zf):
        seen = set()
        if len(zf.infolist()) > 100000:
            raise ValueError("备份包文件数量异常")
        for info in zf.infolist():
            name = info.filename
            path = PurePosixPath(name)
            mode = (info.external_attr >> 16) & 0xFFFF
            if (not name or '\\' in name or ':' in name or path.is_absolute()
                    or '..' in path.parts or len(path.parts) != 1 or stat.S_ISLNK(mode)):
                raise ValueError(f"备份包包含不安全路径: {name}")
            if name not in ('meta.json', 'index.enc', 'migration.key') and not name.endswith('.vault'):
                raise ValueError(f"备份包包含未知文件: {name}")
            if info.file_size > max(10 * 1024 * 1024, info.compress_size * 100):
                raise ValueError(f"备份包中的文件压缩比例异常: {name}")
            if name in seen:
                raise ValueError(f"备份包包含重复文件: {name}")
            seen.add(name)

    @staticmethod
    def _read_migration_key(path, password):
        with open(path, 'rb') as f:
            wrapped = f.read()
        if not password:
            raise ValueError("此跨设备备份需要密码")
        if len(wrapped) < len(BACKUP_KEY_MAGIC) + 16 + MIN_ENCRYPTED_DATA_SIZE:
            raise ValueError("迁移密钥已损坏")
        if not wrapped.startswith(BACKUP_KEY_MAGIC):
            raise ValueError("迁移密钥格式无效")
        start = len(BACKUP_KEY_MAGIC)
        salt = wrapped[start:start + 16]
        backup_key = hashlib.scrypt(password.encode('utf-8'), salt=salt,
                                    n=2 ** 14, r=8, p=1, dklen=32)
        return decrypt_data(wrapped[start + 16:], backup_key)

    def import_vault(self, import_path, password=None):
        temp_dir = tempfile.mkdtemp()
        created_paths = []
        old_index = list(self.index)
        try:
            try:
                import pyzipper
                with pyzipper.AESZipFile(import_path, 'r') as zf:
                    self._validate_backup_members(zf)
                    if password:
                        zf.setpassword(password.encode())
                    zf.extractall(temp_dir)
            except (RuntimeError, ValueError, zipfile.BadZipFile) as e:
                raise ValueError(f"无法打开备份包，请检查文件和密码: {e}") from e
            meta_path = os.path.join(temp_dir, 'meta.json')
            if not os.path.exists(meta_path):
                raise ValueError("无效的备份包：缺少 meta.json")
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            index_path = os.path.join(temp_dir, 'index.enc')
            if not os.path.exists(index_path):
                raise ValueError("无效的备份包：缺少 index.enc")
            backup_master_key = self.master_key
            migration_key_path = os.path.join(temp_dir, 'migration.key')
            if os.path.exists(migration_key_path):
                try:
                    backup_master_key = self._read_migration_key(migration_key_path, password)
                except Exception as e:
                    raise ValueError("备份密码错误或迁移密钥已损坏") from e
            elif meta.get('portable'):
                raise ValueError("跨设备备份缺少迁移密钥")
            with open(index_path, 'rb') as f:
                try:
                    entries = json.loads(decrypt_data(f.read(), backup_master_key).decode('utf-8'))
                except Exception as e:
                    raise ValueError("无法解密备份索引；无密码备份只能由原 Windows 用户账户恢复") from e
            if not isinstance(entries, list):
                raise ValueError("备份索引格式无效")

            imported_entries = []
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get('original_name'), str):
                    raise ValueError("备份索引包含无效记录")
                archive_name = os.path.basename(str(entry.get('secret_path', '')))
                if not archive_name.endswith('.vault'):
                    raise ValueError("备份索引中的文件名无效")
                source_path = os.path.join(temp_dir, archive_name)
                if not os.path.isfile(source_path):
                    raise ValueError(f"备份包缺少文件: {archive_name}")
                with open(source_path, 'rb') as f:
                    encrypted_file_key, encrypted_content = self._deserialize_vault(f.read())
                file_key = decrypt_data(encrypted_file_key, backup_master_key)
                decrypt_data(encrypted_content, file_key)
                if backup_master_key != self.master_key:
                    data_pack = self._serialize_vault(
                        encrypt_data(file_key, self.master_key), encrypted_content)
                else:
                    with open(source_path, 'rb') as f:
                        data_pack = f.read()
                new_id = str(uuid.uuid4())
                dest_path = os.path.join(self.SECRET_DIR, new_id + '.vault')
                temp_path = dest_path + '.tmp'
                with open(temp_path, 'wb') as f:
                    f.write(data_pack)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, dest_path)
                created_paths.append(dest_path)
                original_name = entry['original_name'].replace('\\', '/').split('/')[-1]
                if not original_name or '\x00' in original_name or len(original_name) > 255:
                    raise ValueError("备份索引中的原文件名无效")
                methods = entry.get('second_auth_methods', [])
                tags = entry.get('tags', [])
                if not isinstance(methods, list) or not isinstance(tags, list):
                    raise ValueError("备份索引中的验证方式或标签格式无效")
                methods = [m for m in methods
                           if m in ('password', 'question', 'totp', 'email')]
                tags = [tag for tag in tags if isinstance(tag, str) and len(tag) <= 100]
                imported = dict(entry)
                imported.update({
                    'id': new_id,
                    'original_name': original_name,
                    'secret_path': dest_path,
                    'user_path': None,
                    'is_advanced': bool(entry.get('is_advanced', False)),
                    'second_auth_methods': methods,
                    'tags': tags,
                })
                imported['ext'] = os.path.splitext(imported['original_name'])[1].lower()
                imported['type'] = self._get_file_type(imported['ext'])
                imported_entries.append(imported)
            self.index.extend(imported_entries)
            self._save_index()
        except Exception:
            self.index = old_index
            for path in created_paths:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            raise
        finally:
            shutil.rmtree(temp_dir)
        return True
