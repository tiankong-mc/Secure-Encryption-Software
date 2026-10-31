"""匿名崩溃报告。"""
import os, re, sys, glob, platform, datetime, traceback, threading

MAX_REPORTS = 10

_WIN_PATH_RE = re.compile(r'[A-Za-z]:[\\/](?:[^\s\'"<>|?*:]+[\\/])*[^\s\'"<>|?*:]*', re.UNICODE)
_UNIX_PATH_RE = re.compile(r'/(?:home|Users|tmp|var|opt|root|mnt|private|Library)(?:/[^\s\'"<>|?*:]+)+', re.UNICODE)
_UNC_PATH_RE = re.compile(r'\\\\[^\s\'"<>|?*]+\\[^\s\'"<>|?*]+', re.UNICODE)

def _collect_sensitive_strings():
    result = set()
    for var in ('USERNAME', 'USER', 'HOME', 'USERPROFILE', 'LOGNAME', 'HOMEPATH'):
        v = os.environ.get(var)
        if not v: continue
        v = v.strip()
        if not v: continue
        result.add(v)
        base = os.path.basename(v.rstrip('\\/'))
        if base: result.add(base)
    try:
        import getpass
        u = getpass.getuser()
        if u: result.add(u)
    except Exception: pass
    return result

def sanitize_text(text):
    if not text: return text
    if not isinstance(text, str): text = str(text)
    for s in _collect_sensitive_strings():
        if len(s) >= 5: text = text.replace(s, '<USER>')
    text = _UNC_PATH_RE.sub('<PATH>', text)
    text = _WIN_PATH_RE.sub('<PATH>', text)
    text = _UNIX_PATH_RE.sub('<PATH>', text)
    return text

def get_crash_dir():
    appdata = os.environ.get('APPDATA')
    if not appdata: appdata = os.path.expanduser('~')
    crash_dir = os.path.join(appdata, 'SecureVault', 'crashes')
    try: os.makedirs(crash_dir, exist_ok=True)
    except OSError: pass
    return crash_dir

def _collect_env_info():
    try:
        from constants import VERSION
    except Exception:
        VERSION = "unknown"
    try:
        os_desc = f"{platform.system()} {platform.release()} ({platform.version()})"
    except Exception:
        os_desc = "unknown"
    try:
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    except Exception:
        py_ver = "unknown"
    bits = 64 if sys.maxsize > 2**32 else 32
    return {'version': VERSION, 'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'os': os_desc, 'python': f"{py_ver} ({bits}-bit)",
            'frozen': bool(getattr(sys, 'frozen', False))}

def _trim_reports(crash_dir):
    try:
        reports = sorted(glob.glob(os.path.join(crash_dir, 'crash_*.log')))
    except Exception:
        return
    if len(reports) <= MAX_REPORTS: return
    for old in reports[:-MAX_REPORTS]:
        try: os.remove(old)
        except OSError: pass

def write_crash_report(exc_type, exc_value, exc_tb, extra_lines=None):
    try:
        env = _collect_env_info()
        tb_text = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        tb_text = sanitize_text(tb_text)
        exc_msg = sanitize_text(str(exc_value))
        lines = ["========== SecureVault Crash Report =========="]
        lines.append(f"Time:     {env['time']}")
        lines.append(f"Version:  {env['version']}")
        lines.append(f"OS:       {env['os']}")
        lines.append(f"Python:   {env['python']}")
        lines.append(f"Frozen:   {env['frozen']}")
        lines.append("--- Traceback (sanitized) ---")
        lines.append(tb_text.rstrip())
        lines.append("--- Exception ---")
        lines.append(f"Type:    {exc_type.__name__ if exc_type else 'Unknown'}")
        lines.append(f"Message: {exc_msg}")
        if extra_lines:
            lines.append("--- Extra ---")
            for l in extra_lines: lines.append(sanitize_text(str(l)))
        lines.append("========== End of Report ==========")
        content = "\n".join(lines) + "\n"
        crash_dir = get_crash_dir()
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
        path = os.path.join(crash_dir, f"crash_{ts}.log")
        with open(path, 'w', encoding='utf-8') as f: f.write(content)
        _trim_reports(crash_dir)
        return path
    except Exception:
        return None

def is_crash_report_enabled(settings_manager):
    try:
        s = settings_manager.load_settings()
        return bool(s.get('crash_report_enabled', False))
    except Exception:
        return False

def install_excepthook(settings_getter=None):
    def _is_enabled():
        if settings_getter is None: return False
        try:
            sm = settings_getter()
            if sm is None: return False
            return is_crash_report_enabled(sm)
        except Exception: return False

    def handle_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb); return
        report_path = None
        try:
            if _is_enabled(): report_path = write_crash_report(exc_type, exc_value, exc_tb)
        except Exception: pass
        # 只有主线程才弹窗，非主线程只写日志
        if threading.current_thread() is threading.main_thread():
            try:
                from PyQt5.QtWidgets import QApplication
                app = QApplication.instance()
                if app is not None and report_path:
                    _show_crash_dialog(report_path, exc_type, exc_value)
            except Exception: pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handle_exception
    try:
        def thread_hook(args):
            handle_exception(args.exc_type, args.exc_value, args.exc_traceback)
        threading.excepthook = thread_hook
    except Exception: pass

def _show_crash_dialog(report_path, exc_type, exc_value):
    try:
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                      QPushButton, QTextEdit, QApplication)
    except Exception: return
    try:
        with open(report_path, 'r', encoding='utf-8') as f: content = f.read()
    except Exception:
        content = f"{exc_type.__name__}: {exc_value}"
    dlg = QDialog(); dlg.setWindowTitle("SecureVault 崩溃报告"); dlg.resize(680, 500)
    layout = QVBoxLayout()
    intro = QLabel("程序意外崩溃了。\n\n如果方便，可以把这份报告发到 GitHub Issues，帮助定位问题。\n报告已脱敏，不包含您的文件路径和用户名。")
    intro.setWordWrap(True); layout.addWidget(intro)
    text = QTextEdit(); text.setReadOnly(True); text.setPlainText(content); text.setLineWrapMode(QTextEdit.NoWrap)
    layout.addWidget(text)
    btn_row = QHBoxLayout()
    copy_btn = QPushButton("复制到剪贴板"); open_folder_btn = QPushButton("打开日志文件夹")
    github_btn = QPushButton("打开 GitHub Issues"); close_btn = QPushButton("关闭")
    def on_copy():
        try: QApplication.clipboard().setText(content)
        except Exception: pass
    def on_open_folder():
        try:
            folder = os.path.dirname(report_path)
            if os.name == 'nt': os.startfile(folder)
            else:
                import webbrowser; webbrowser.open('file://' + folder)
        except Exception: pass
    def on_github():
        try: QApplication.clipboard().setText(content)
        except Exception: pass
        try:
            import webbrowser
            webbrowser.open("https://github.com/tiankong-mc/Secure-Encryption-Software/issues/new")
        except Exception: pass
    copy_btn.clicked.connect(on_copy); open_folder_btn.clicked.connect(on_open_folder)
    github_btn.clicked.connect(on_github); close_btn.clicked.connect(dlg.accept)
    btn_row.addWidget(copy_btn); btn_row.addWidget(open_folder_btn); btn_row.addWidget(github_btn)
    btn_row.addStretch(); btn_row.addWidget(close_btn)
    layout.addLayout(btn_row); dlg.setLayout(layout); dlg.exec_()