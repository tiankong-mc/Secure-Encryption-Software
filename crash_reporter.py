"""匿名崩溃报告。

设计目标：
  - 崩溃时生成脱敏的诊断报告（堆栈 + 版本 + OS）
  - 绝不包含文件路径、用户名、环境变量内容
  - 是否启用完全由用户控制（设置 → 安全 → 崩溃报告）
  - 报告只保存在本地，不会自动上传
  - 用户可手动复制到 GitHub Issues

默认关闭：用户未在设置中启用时，sys.excepthook 保持原样。
"""

import os
import re
import sys
import glob
import platform
import datetime
import traceback


# 最多保留的崩溃报告份数
MAX_REPORTS = 10


# ---------- 脱敏正则 ----------
# Windows 绝对路径：C:\xxx\yyy 或 C:/xxx/yyy
_WIN_PATH_RE = re.compile(
    r'[A-Za-z]:[\\/](?:[^\s\'"<>|?*:]+[\\/])*[^\s\'"<>|?*:]*',
    re.UNICODE)
# Unix 常见路径：/home/xxx 或 /Users/xxx 或 /tmp/xxx 等
_UNIX_PATH_RE = re.compile(
    r'/(?:home|Users|tmp|var|opt|root|mnt|private|Library)(?:/[^\s\'"<>|?*:]+)+',
    re.UNICODE)
# UNC 路径：\\server\share\path
_UNC_PATH_RE = re.compile(
    r'\\\\[^\s\'"<>|?*]+\\[^\s\'"<>|?*]+',
    re.UNICODE)


def _collect_sensitive_strings():
    """从环境变量收集需要脱敏的字符串（用户名、home 目录等）。"""
    result = set()
    for var in ('USERNAME', 'USER', 'HOME', 'USERPROFILE', 'LOGNAME', 'HOMEPATH'):
        v = os.environ.get(var)
        if not v:
            continue
        v = v.strip()
        if not v:
            continue
        result.add(v)
        base = os.path.basename(v.rstrip('\\/'))
        if base:
            result.add(base)
    try:
        import getpass
        u = getpass.getuser()
        if u:
            result.add(u)
    except Exception:
        pass
    return result


def sanitize_text(text):
    """对文本做脱敏，去除路径、用户名。"""
    if not text:
        return text
    if not isinstance(text, str):
        text = str(text)

    # 1. 先替换环境变量里的具体字符串（长度 >= 3 避免误伤）
    for s in _collect_sensitive_strings():
        if len(s) >= 3:
            text = text.replace(s, '<USER>')

    # 2. 替换 UNC 路径
    text = _UNC_PATH_RE.sub('<PATH>', text)
    # 3. 替换 Windows 路径
    text = _WIN_PATH_RE.sub('<PATH>', text)
    # 4. 替换 Unix 路径
    text = _UNIX_PATH_RE.sub('<PATH>', text)

    return text


def get_crash_dir():
    """返回崩溃报告目录，不存在则创建。"""
    appdata = os.environ.get('APPDATA')
    if not appdata:
        appdata = os.path.expanduser('~')
    crash_dir = os.path.join(appdata, 'SecureVault', 'crashes')
    try:
        os.makedirs(crash_dir, exist_ok=True)
    except OSError:
        pass
    return crash_dir


def _collect_env_info():
    """收集环境信息（不含隐私）。"""
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
    return {
        'version': VERSION,
        'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'os': os_desc,
        'python': f"{py_ver} ({bits}-bit)",
        'frozen': bool(getattr(sys, 'frozen', False)),
    }


def _trim_reports(crash_dir):
    """最多保留 MAX_REPORTS 份报告，删除最旧的。"""
    try:
        reports = sorted(glob.glob(os.path.join(crash_dir, 'crash_*.log')))
    except Exception:
        return
    if len(reports) <= MAX_REPORTS:
        return
    for old in reports[:-MAX_REPORTS]:
        try:
            os.remove(old)
        except OSError:
            pass


def write_crash_report(exc_type, exc_value, exc_tb, extra_lines=None):
    """把崩溃报告写到磁盘，返回文件路径（失败返回 None）。"""
    try:
        env = _collect_env_info()

        tb_text = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        tb_text = sanitize_text(tb_text)

        exc_msg = sanitize_text(str(exc_value))

        lines = []
        lines.append("========== SecureVault Crash Report ==========")
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
            for l in extra_lines:
                lines.append(sanitize_text(str(l)))
        lines.append("========== End of Report ==========")
        content = "\n".join(lines) + "\n"

        crash_dir = get_crash_dir()
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
        path = os.path.join(crash_dir, f"crash_{ts}.log")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

        _trim_reports(crash_dir)
        return path
    except Exception:
        return None


def is_crash_report_enabled(settings_manager):
    """检查用户是否开启了崩溃报告。"""
    try:
        s = settings_manager.load_settings()
        return bool(s.get('crash_report_enabled', False))
    except Exception:
        return False


def install_excepthook(settings_getter=None):
    """
    安装全局异常处理器。

    参数：
      settings_getter - 可选的 callable，返回 SettingsManager 实例或 None。
                        每次崩溃时调用，用于延迟读取"是否启用崩溃报告"设置。
                        传 None 表示始终不生成报告。

    - 只处理未捕获的异常，不干扰正常流程
    - 用户未开启时什么都不做
    - 用户开启时写脱敏报告 + 弹窗（如果 Qt 可用）
    """
    def _is_enabled():
        if settings_getter is None:
            return False
        try:
            sm = settings_getter()
            if sm is None:
                return False
            return is_crash_report_enabled(sm)
        except Exception:
            return False

    def handle_exception(exc_type, exc_value, exc_tb):
        # 忽略 Ctrl+C
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        report_path = None
        try:
            if _is_enabled():
                report_path = write_crash_report(exc_type, exc_value, exc_tb)
        except Exception:
            pass

        # 弹窗（需要 Qt 已初始化）
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None and report_path:
                _show_crash_dialog(report_path, exc_type, exc_value)
        except Exception:
            pass

        # 仍然把原始 traceback 打印到 stderr
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handle_exception

    # Python 3.8+：给非主线程也装一个
    try:
        import threading
        def thread_hook(args):
            handle_exception(args.exc_type, args.exc_value, args.exc_traceback)
        threading.excepthook = thread_hook
    except Exception:
        pass


def _show_crash_dialog(report_path, exc_type, exc_value):
    """显示崩溃报告对话框，允许用户复制 / 打开 Issues。"""
    try:
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                      QPushButton, QTextEdit, QApplication)
    except Exception:
        return

    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        content = f"{exc_type.__name__}: {exc_value}"

    dlg = QDialog()
    dlg.setWindowTitle("SecureVault 崩溃报告")
    dlg.resize(680, 500)

    layout = QVBoxLayout()
    intro = QLabel(
        "程序意外崩溃了。\n\n"
        "如果方便，可以把这份报告发到 GitHub Issues，帮助定位问题。\n"
        "报告已脱敏，不包含您的文件路径和用户名。")
    intro.setWordWrap(True)
    layout.addWidget(intro)

    text = QTextEdit()
    text.setReadOnly(True)
    text.setPlainText(content)
    text.setLineWrapMode(QTextEdit.NoWrap)
    layout.addWidget(text)

    btn_row = QHBoxLayout()

    copy_btn = QPushButton("复制到剪贴板")
    open_folder_btn = QPushButton("打开日志文件夹")
    github_btn = QPushButton("打开 GitHub Issues")
    close_btn = QPushButton("关闭")

    def on_copy():
        try:
            QApplication.clipboard().setText(content)
        except Exception:
            pass

    def on_open_folder():
        try:
            folder = os.path.dirname(report_path)
            if os.name == 'nt':
                os.startfile(folder)
            else:
                import webbrowser
                webbrowser.open('file://' + folder)
        except Exception:
            pass

    def on_github():
        try:
            QApplication.clipboard().setText(content)
        except Exception:
            pass
        try:
            import webbrowser
            webbrowser.open(
                "https://github.com/tiankong-mc/Secure-Encryption-Software/issues/new")
        except Exception:
            pass

    copy_btn.clicked.connect(on_copy)
    open_folder_btn.clicked.connect(on_open_folder)
    github_btn.clicked.connect(on_github)
    close_btn.clicked.connect(dlg.accept)

    btn_row.addWidget(copy_btn)
    btn_row.addWidget(open_folder_btn)
    btn_row.addWidget(github_btn)
    btn_row.addStretch()
    btn_row.addWidget(close_btn)
    layout.addLayout(btn_row)

    dlg.setLayout(layout)
    dlg.exec_()
