import os
import json
import shutil
import uuid
import pickle
import zipfile
import tempfile
from crypto import encrypt_data, decrypt_data, generate_key
from settings import SettingsManager
from backup import BackupManager

class StorageManager:
    SECRET_DIR = r'C:\ProgramData\SecureVault'
    INDEX_PATH = os.path.join(SECRET_DIR, 'index.enc')

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

    def _ensure_tags_list(self):
        # 确保每个条目有 tags 字段
        for entry in self.index:
            if 'tags' not in entry:
                entry['tags'] = []
        self._save_index()

    def _load_index(self):
        if os.path.exists(self.INDEX_PATH):
            with open(self.INDEX_PATH, 'rb') as f:
                encrypted = f.read()
            try:
                data = decrypt_data(encrypted, self.master_key)
                return json.loads(data.decode('utf-8'))
            except:
                return []
        return []

    def _save_index(self):
        data = json.dumps(self.index).encode('utf-8')
        encrypted = encrypt_data(data, self.master_key)
        with open(self.INDEX_PATH, 'wb') as f:
            f.write(encrypted)

    def add_file(self, local_path, user_dest=None, is_advanced=False, second_auth_methods=None, tags=None):
        with open(local_path, 'rb') as f:
            plain = f.read()
        file_key = generate_key()
        encrypted_content = encrypt_data(plain, file_key)
        encrypted_file_key = encrypt_data(file_key, self.master_key)
        data_pack = pickle.dumps((encrypted_file_key, encrypted_content))
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
                encrypted_file_key, encrypted_content = pickle.loads(data_pack)
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
        try:
            encrypted_file_key, encrypted_content = pickle.loads(data_pack)
            decrypt_data(encrypted_file_key, self.master_key)
        except:
            raise ValueError("无效的加密文件格式")
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
        """
        将整个保险库打包到一个文件中（包含加密文件、索引、配置）
        如果提供了密码，使用 AES 加密打包文件
        """
        import pyzipper
        temp_dir = tempfile.mkdtemp()
        try:
            # 复制所有 .vault 文件到临时目录
            vault_files = []
            for entry in self.index:
                src = entry['secret_path']
                if os.path.exists(src):
                    dest = os.path.join(temp_dir, os.path.basename(src))
                    shutil.copy2(src, dest)
                    vault_files.append(dest)
            # 复制索引文件
            shutil.copy2(self.INDEX_PATH, os.path.join(temp_dir, 'index.enc'))
            # 复制配置文件（master.key, config.dat）
            config_dir = self.settings.CONFIG_DIR
            shutil.copy2(os.path.join(config_dir, 'master.key'), os.path.join(temp_dir, 'master.key'))
            shutil.copy2(os.path.join(config_dir, 'config.dat'), os.path.join(temp_dir, 'config.dat'))
            # 创建元数据文件（记录版本等）
            meta = {
                'version': '1.0',
                'timestamp': __import__('datetime').datetime.now().isoformat(),
                'num_files': len(self.index)
            }
            with open(os.path.join(temp_dir, 'meta.json'), 'w') as f:
                json.dump(meta, f)
            # 打包
            with pyzipper.AESZipFile(export_path, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
                if password:
                    zf.setpassword(password.encode())
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        full_path = os.path.join(root, file)
                        arcname = os.path.relpath(full_path, temp_dir)
                        zf.write(full_path, arcname)
        finally:
            shutil.rmtree(temp_dir)

    def import_vault(self, import_path, password=None):
        """
        从备份包导入保险库，覆盖当前所有数据
        """
        import pyzipper
        temp_dir = tempfile.mkdtemp()
        try:
            with pyzipper.AESZipFile(import_path, 'r') as zf:
                if password:
                    zf.setpassword(password.encode())
                zf.extractall(temp_dir)
            # 检查元数据
            meta_path = os.path.join(temp_dir, 'meta.json')
            if not os.path.exists(meta_path):
                raise ValueError("无效的备份包：缺少 meta.json")
            # 停止当前服务（没有服务，直接覆盖）
            # 覆盖 .vault 文件到 SECRET_DIR
            for file in os.listdir(temp_dir):
                if file.endswith('.vault'):
                    shutil.copy2(os.path.join(temp_dir, file), self.SECRET_DIR)
            # 覆盖索引
            shutil.copy2(os.path.join(temp_dir, 'index.enc'), self.INDEX_PATH)
            # 覆盖配置
            config_dir = self.settings.CONFIG_DIR
            shutil.copy2(os.path.join(temp_dir, 'master.key'), config_dir)
            shutil.copy2(os.path.join(temp_dir, 'config.dat'), config_dir)
            # 重新加载索引
            self.index = self._load_index()
        finally:
            shutil.rmtree(temp_dir)
        return True
