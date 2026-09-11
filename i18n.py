import os, json, shutil

class I18nManager:
    def __init__(self, lang_dir):
        self.lang_dir = lang_dir
        self.current_code = "zh_CN"
        self.translations = {}
        self.available = {}
        os.makedirs(lang_dir, exist_ok=True)
        self.scan()
        self.load("zh_CN")

    def scan(self):
        self.available = {}
        for f in os.listdir(self.lang_dir):
            if f.endswith('.json'):
                try:
                    with open(os.path.join(self.lang_dir, f), 'r', encoding='utf-8') as fp:
                        data = json.load(fp)
                    code = data.get('language_code', os.path.splitext(f)[0])
                    name = data.get('language_name', code)
                    self.available[code] = name
                except Exception:
                    pass

    def load(self, code):
        path = os.path.join(self.lang_dir, f"{code}.json")
        if not os.path.exists(path):
            return False
        with open(path, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        self.translations = data.get('translations', {})
        self.current_code = code
        return True

    def import_pack(self, src_path):
        with open(src_path, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        code = data.get('language_code')
        if not code:
            raise ValueError("语言包缺少 language_code 字段")
        dest = os.path.join(self.lang_dir, f"{code}.json")
        shutil.copy2(src_path, dest)
        self.scan()
        return code, data.get('language_name', code)

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
