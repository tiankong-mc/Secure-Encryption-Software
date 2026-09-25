import os, json, re

# 语言包体积上限，避免超大的恶意 JSON 造成内存耗尽
MAX_LANG_PACK_SIZE = 10 * 1024 * 1024  # 10 MB
# 翻译条目数上限，避免构造大量 key 消耗内存
MAX_TRANSLATIONS = 10000


class I18nManager:
    def __init__(self, lang_dir):
        self.lang_dir = lang_dir
        appdata = os.environ.get('APPDATA')
        self.user_lang_dir = (os.path.join(appdata, 'SecureVault', 'lang')
                              if appdata else lang_dir)
        self.current_code = "zh_CN"
        self.translations = {}
        self.available = {}
        self.paths = {}
        os.makedirs(self.user_lang_dir, exist_ok=True)
        self.scan()
        self.load("zh_CN")

    def scan(self):
        self.available = {}
        self.paths = {}
        directories = [self.lang_dir]
        if os.path.normcase(self.user_lang_dir) != os.path.normcase(self.lang_dir):
            directories.append(self.user_lang_dir)
        for directory in directories:
            if not os.path.isdir(directory):
                continue
            for f in os.listdir(directory):
                if f.endswith('.json'):
                    try:
                        path = os.path.join(directory, f)
                        if os.path.getsize(path) > MAX_LANG_PACK_SIZE:
                            continue
                        with open(path, 'r', encoding='utf-8') as fp:
                            data = json.load(fp)
                        code = data.get('language_code', os.path.splitext(f)[0])
                        name = data.get('language_name', code)
                        if not self._valid_pack(data):
                            continue
                        self.available[code] = name
                        self.paths[code] = path
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        pass

    def load(self, code):
        path = self.paths.get(code)
        if not path or not os.path.exists(path):
            return False
        with open(path, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        self.translations = data.get('translations', {})
        self.current_code = code
        return True

    def import_pack(self, src_path):
        try:
            size = os.path.getsize(src_path)
        except OSError as e:
            raise ValueError(f"无法读取文件：{e}")
        if size > MAX_LANG_PACK_SIZE:
            raise ValueError(
                f"语言包文件过大（{size} 字节，上限 {MAX_LANG_PACK_SIZE} 字节）")
        with open(src_path, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        if not self._valid_pack(data):
            raise ValueError("语言包格式无效")
        code = data['language_code']
        dest = os.path.join(self.user_lang_dir, f"{code}.json")
        temp_path = dest + '.tmp'
        try:
            with open(temp_path, 'w', encoding='utf-8') as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(temp_path, dest)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        self.scan()
        return code, data.get('language_name', code)

    @staticmethod
    def _valid_pack(data):
        if not isinstance(data, dict):
            return False
        code = data.get('language_code')
        name = data.get('language_name')
        translations = data.get('translations')
        if not (isinstance(code, str)
                and re.fullmatch(r'[A-Za-z0-9_-]{2,32}', code) is not None):
            return False
        if not (isinstance(name, str) and 0 < len(name) <= 100):
            return False
        if not isinstance(translations, dict):
            return False
        # 限制翻译条目数量，防止构造大量 key 消耗内存
        if len(translations) > MAX_TRANSLATIONS:
            return False
        return all(isinstance(k, str) and isinstance(v, str)
                   for k, v in translations.items())

    def tr(self, key, default=None):
        if key in self.translations:
            return self.translations[key]
        return default if default is not None else key


_manager = None

def init_i18n(lang_dir):
    global _manager
    _manager = I18nManager(lang_dir)
    return _manager

def tr(key, default=None):
    if _manager is None:
        return default if default is not None else key
    return _manager.tr(key, default)

def get_manager():
    return _manager
