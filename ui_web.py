import os, secrets, smtplib, threading, time, ipaddress
from datetime import datetime
from email.mime.text import MIMEText
from io import BytesIO
from flask import Flask, request, render_template_string, session, redirect, url_for, jsonify, send_file
from werkzeug.serving import make_server
from constants import VERSION, WEB_PORT

flask_app = Flask(__name__)
flask_app.secret_key = os.urandom(24)
flask_app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)
web_storage = None
web_auth = None
_server = None
_server_thread = None
EMAIL_CODE_TTL = 300
EMAIL_CODE_COOLDOWN = 60
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 60
MAX_RATE_ENTRIES = 1000
_rate_lock = threading.Lock()
_login_rates = {}
_email_rates = {}


def _cleanup_rates_locked(rates, ttl_seconds):
    """
    在持有 _rate_lock 的情况下调用。
    当字典条目数超过上限时，清理过期条目，避免无限增长。

    修复 #5：删除"清理一半就 break"的提前退出条件。
    清理函数只在字典超限时被调用，遍历 1000 条数据的开销可以接受，
    提前退出反而可能因为迭代顺序导致部分过期条目没被清理。
    """
    if len(rates) <= MAX_RATE_ENTRIES:
        return
    now = time.time()
    to_remove = []
    for k, v in list(rates.items()):
        if isinstance(v, dict):
            # _login_rates 条目
            lock_until = v.get('lock_until', 0)
            failures = v.get('failures', 0)
            last_seen = v.get('last_seen', 0)
            # 条件一：锁定已过期且已无失败计数
            if lock_until and lock_until < now and failures == 0:
                to_remove.append(k)
                continue
            # 条件二：last_seen 超过 ttl 秒前
            if last_seen and now - last_seen > ttl_seconds:
                to_remove.append(k)
        else:
            # _email_rates 条目
            if now - v > ttl_seconds:
                to_remove.append(k)
    for k in to_remove:
        rates.pop(k, None)


@flask_app.before_request
def restrict_to_local_network():
    """即使端口被意外暴露，也拒绝公网来源地址。"""
    try:
        address = ipaddress.ip_address(request.remote_addr or '')
        mapped = getattr(address, 'ipv4_mapped', None)
        if mapped:
            address = mapped
    except ValueError:
        return "拒绝访问", 403
    if not (address.is_private or address.is_loopback or address.is_link_local):
        return "仅允许局域网访问", 403
    origin = request.headers.get('Origin')
    if request.method == 'POST' and origin:
        expected = request.host_url.rstrip('/')
        if origin.rstrip('/') != expected:
            return "请求来源无效", 403


def _enabled_methods():
    return web_auth.get_enabled_methods() if web_auth else []


def _email_code_matches(value):
    code = session.get('email_code')
    expiry = session.get('email_code_expires', 0)
    session.pop('email_code', None)
    session.pop('email_code_expires', None)
    return bool(code and expiry >= time.time()
                and secrets.compare_digest(value, code))


def _login_lock_remaining(client):
    with _rate_lock:
        state = _login_rates.get(client)
        if not state:
            return 0
        remaining = state.get('lock_until', 0) - time.time()
        if remaining <= 0 and state.get('lock_until'):
            _login_rates.pop(client, None)
            return 0
        return max(0, int(remaining))


def _record_login_result(client, succeeded):
    with _rate_lock:
        if succeeded:
            _login_rates.pop(client, None)
        else:
            state = _login_rates.setdefault(
                client, {'failures': 0, 'lock_until': 0, 'last_seen': 0})
            state['failures'] += 1
            state['last_seen'] = time.time()
            if state['failures'] >= LOGIN_MAX_ATTEMPTS:
                state['failures'] = 0
                state['lock_until'] = time.time() + LOGIN_LOCK_SECONDS
        _cleanup_rates_locked(_login_rates, LOGIN_LOCK_SECONDS * 2)


@flask_app.template_filter('b64encode')
def b64encode_filter(data):
    import base64
    return base64.b64encode(data).decode('utf-8')


@flask_app.route('/')
def web_index():
    if 'authenticated' not in session or not session['authenticated']:
        return redirect(url_for('web_login'))
    entries = web_storage.get_all_entries() if web_storage else []
    return render_template_string(WEB_TEMPLATE, entries=entries, VERSION=VERSION)


@flask_app.route('/login', methods=['GET', 'POST'])
def web_login():
    questions = web_auth.get_questions() if web_auth else []
    methods = _enabled_methods()
    if request.method == 'POST':
        client = request.remote_addr or 'unknown'
        wait_seconds = _login_lock_remaining(client)
        if wait_seconds:
            return render_template_string(WEB_LOGIN_TEMPLATE, methods=methods,
                                          questions=questions,
                                          error=f"尝试次数过多，请等待 {wait_seconds} 秒"), 429
        method = request.form.get('method', 'password')
        inp = request.form.get('input', '')
        ok = False
        if method not in methods:
            ok = False
        elif method == 'password':
            ok = web_auth.verify_password(inp) if web_auth else False
        elif method == 'question':
            q = request.form.get('question', '')
            ok = web_auth.verify_question(q, inp) if web_auth else False
        elif method == 'totp':
            ok = web_auth.verify_totp(inp) if web_auth else False
        elif method == 'email':
            ok = _email_code_matches(inp)
        if ok:
            web_storage.log("移动端登录成功")
            _record_login_result(client, True)
            session['authenticated'] = True
            return redirect(url_for('web_index'))
        else:
            web_storage.log("移动端登录失败")
            _record_login_result(client, False)
            return render_template_string(WEB_LOGIN_TEMPLATE, methods=methods,
                                          questions=questions, error="验证失败")
    return render_template_string(WEB_LOGIN_TEMPLATE, methods=methods,
                                  questions=questions, error=None)


@flask_app.route('/view/<entry_id>')
def web_view(entry_id):
    if 'authenticated' not in session or not session['authenticated']:
        return redirect(url_for('web_login'))
    if not check_second_auth(entry_id):
        entry = web_storage.get_entry_by_id(entry_id)
        if entry and entry.get('is_advanced', False):
            return redirect(url_for('web_second_auth', entry_id=entry_id))
    try:
        data = web_storage.get_file_data(entry_id)
        entry = web_storage.get_entry_by_id(entry_id)
        if not entry:
            return "文件不存在", 404
        web_storage.log(f"移动端查看文件: {entry['original_name']}")
        return render_template_string(WEB_VIEW_TEMPLATE, data=data, entry=entry)
    except Exception as e:
        web_storage.log(f"移动端查看失败 (文件ID: {entry_id}): {e}")
        return "查看失败", 500


@flask_app.route('/second_auth/<entry_id>', methods=['GET', 'POST'])
def web_second_auth(entry_id):
    if 'authenticated' not in session or not session['authenticated']:
        return redirect(url_for('web_login'))
    entry = web_storage.get_entry_by_id(entry_id)
    if not entry:
        return "文件不存在", 404
    enabled = set(_enabled_methods())
    allowed_methods = [m for m in entry.get('second_auth_methods', []) if m in enabled]
    questions = web_auth.get_questions() if web_auth else []
    if not allowed_methods:
        return "此文件没有可用的二次验证方式", 403
    if request.method == 'POST':
        client = request.remote_addr or 'unknown'
        wait_seconds = _login_lock_remaining(client)
        if wait_seconds:
            return render_template_string(
                WEB_SECOND_AUTH_TEMPLATE, entry=entry, methods=allowed_methods,
                questions=questions,
                error=f"尝试次数过多，请等待 {wait_seconds} 秒"), 429
        method = request.form.get('method', 'password')
        if method not in allowed_methods:
            return render_template_string(WEB_SECOND_AUTH_TEMPLATE, entry=entry, methods=allowed_methods, questions=questions, error="不允许的验证方式"), 400
        inp = request.form.get('input', '')
        ok = False
        if method == 'password':
            ok = web_auth.verify_password(inp) if web_auth else False
        elif method == 'question':
            q = request.form.get('question', '')
            ok = web_auth.verify_question(q, inp) if web_auth else False
        elif method == 'totp':
            ok = web_auth.verify_totp(inp) if web_auth else False
        elif method == 'email':
            ok = _email_code_matches(inp)
        if ok:
            web_storage.log(f"移动端二次验证成功 (文件ID: {entry_id})")
            _record_login_result(client, True)
            second_auth = dict(session.get('second_auth', {}))
            second_auth[entry_id] = datetime.now().timestamp() + 3600
            session['second_auth'] = second_auth
            data = web_storage.get_file_data(entry_id)
            return render_template_string(WEB_VIEW_TEMPLATE, data=data, entry=entry)
        else:
            web_storage.log(f"移动端二次验证失败 (文件ID: {entry_id})")
            _record_login_result(client, False)
            return render_template_string(WEB_SECOND_AUTH_TEMPLATE, entry=entry, methods=allowed_methods, questions=questions, error="验证失败")
    return render_template_string(WEB_SECOND_AUTH_TEMPLATE, entry=entry, methods=allowed_methods, questions=questions, error=None)


@flask_app.route('/download/<entry_id>')
def web_download(entry_id):
    if 'authenticated' not in session or not session['authenticated']:
        return redirect(url_for('web_login'))
    entry = web_storage.get_entry_by_id(entry_id)
    if not entry:
        return "文件不存在", 404
    if entry.get('is_advanced', False) and not check_second_auth(entry_id):
        return redirect(url_for('web_second_auth', entry_id=entry_id))
    try:
        data = web_storage.get_file_data(entry_id)
        web_storage.log(f"移动端下载文件: {entry['original_name']}")
        return send_file(BytesIO(data), as_attachment=True, download_name=entry['original_name'])
    except Exception as e:
        web_storage.log(f"移动端下载失败 (文件ID: {entry_id}): {e}")
        return "下载失败", 500


def check_second_auth(entry_id):
    second_auth = session.get('second_auth', {})
    expiry = second_auth.get(entry_id, 0)
    return expiry > datetime.now().timestamp()


@flask_app.route('/send_code', methods=['POST'])
def send_code():
    if 'email' not in _enabled_methods() or not web_auth.email_config:
        return jsonify({'success': False, 'message': '邮箱未配置或未启用'}), 400
    now = time.time()
    client = request.remote_addr or 'unknown'
    with _rate_lock:
        last_sent = _email_rates.get(client, 0)
        if now - last_sent < EMAIL_CODE_COOLDOWN:
            return jsonify({'success': False, 'message': '发送过于频繁，请稍后再试'}), 429
    code = ''.join(secrets.choice('0123456789') for _ in range(6))
    config = web_auth.email_config
    to_email = config.get('receiver_email')
    if not to_email:
        return jsonify({'success': False, 'message': '未设置收件邮箱'}), 400
    msg = MIMEText(f'您的SecureVault验证码是：{code}')
    msg['Subject'] = 'SecureVault验证码'
    msg['From'] = config['sender_email']
    msg['To'] = to_email
    try:
        with smtplib.SMTP(config['smtp_server'], config['port'], timeout=20) as server:
            server.starttls()
            server.login(config['sender_email'], config['password'])
            server.sendmail(config['sender_email'], [to_email], msg.as_string())
    except Exception as e:
        if web_storage:
            web_storage.log(f"移动端邮箱验证码发送失败: {e}")
        return jsonify({'success': False, 'message': '邮件发送失败，请检查桌面端日志'}), 500
    web_storage.log(f"移动端发送邮箱验证码至: {to_email}")
    session['email_code'] = code
    session['email_code_expires'] = now + EMAIL_CODE_TTL
    with _rate_lock:
        _email_rates[client] = now
        _cleanup_rates_locked(_email_rates, EMAIL_CODE_TTL * 2)
    return jsonify({'success': True, 'message': '验证码已发送'})


def start_web_server(storage, auth):
    """启动 Flask 服务（可被 stop_web_server 关闭）"""
    global web_storage, web_auth, _server, _server_thread
    web_storage = storage
    web_auth = auth
    if _server is not None:
        return True
    try:
        print("\n⚠️ 警告：Web服务使用明文HTTP，仅限可信局域网，公共网络下请勿启用。")
        _server = make_server('0.0.0.0', WEB_PORT, flask_app)
        _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
        _server_thread.start()
        return True
    except Exception as e:
        _server = None
        _server_thread = None
        print(f"Web server error: {e}")
        return False


def stop_web_server():
    """停止 Flask 服务"""
    global _server, _server_thread
    if _server is not None:
        try:
            _server.shutdown()
        except Exception:
            pass
        _server = None
        _server_thread = None


def is_web_running():
    return _server is not None


# ---------- 模板 ----------
WEB_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>SecureVault 移动端</title>
<style>body{font-family:Arial;background:#1e1e1e;color:#eee;padding:10px}h1{font-size:20px}.file-item{background:#2b2b2b;padding:10px;margin:5px 0;border-radius:5px;border-left:3px solid #5a8cbf}a{color:#5a8cbf;text-decoration:none}</style>
</head><body><h1>📁 SecureVault</h1><p style="color:#888;">版本 {{ VERSION }}</p>
{% for e in entries %}
<div class="file-item"><strong>{{ e.original_name }}</strong>{% if e.is_advanced %}<span style="color:#ff6b6b;">[高级]</span>{% endif %}<br><small>标签: {{ e.tags|join(', ') }}</small><br><a href="/view/{{ e.id }}">查看</a></div>
{% else %}<p>暂无文件</p>{% endfor %}
</body></html>"""

WEB_LOGIN_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>登录 - SecureVault</title>
<style>body{background:#1e1e1e;color:#eee;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}form{background:#2b2b2b;padding:30px;border-radius:10px;width:300px}input,select,button{width:100%;padding:8px;margin:5px 0;background:#3c3c3c;border:1px solid #555;color:#eee;border-radius:3px}button{background:#5a8cbf;cursor:pointer}.error{color:#ff6b6b}</style>
<script>
function toggleQuestion() {
    var method = document.getElementById('method').value;
    var qDiv = document.getElementById('question_div');
    var emailDiv = document.getElementById('email_div');
    if (method === 'question') { qDiv.style.display = 'block'; } else { qDiv.style.display = 'none'; }
    if (method === 'email') { emailDiv.style.display = 'block'; } else { emailDiv.style.display = 'none'; }
}
function sendCode() {
    var btn = document.getElementById('send_code_btn');
    btn.disabled = true;
    btn.textContent = '发送中...';
    fetch('/send_code', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) { alert('验证码已发送至您的邮箱'); } else { alert('发送失败: ' + data.message); }
        })
        .catch(err => alert('请求失败'))
        .finally(() => { btn.disabled = false; btn.textContent = '发送验证码'; });
}
window.onload = function() { toggleQuestion(); document.getElementById('method').addEventListener('change', toggleQuestion); }
</script>
</head><body>
<form method="post">
<h2>SecureVault 登录</h2>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<select id="method" name="method">
{% for m in methods %}<option value="{{ m }}">{{ {'password':'密码','question':'安全问题','totp':'TOTP','email':'邮箱验证码'}.get(m, m) }}</option>{% endfor %}
</select>
<div id="question_div" style="display:none;">
<select name="question">
{% for q in questions %}<option value="{{ q }}">{{ q }}</option>{% endfor %}
</select>
</div>
<div id="email_div" style="display:none;">
<button type="button" id="send_code_btn" onclick="sendCode()">发送验证码</button>
</div>
<input type="text" name="input" placeholder="输入验证信息">
<button type="submit">登录</button>
</form>
</body></html>"""

WEB_SECOND_AUTH_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>二次验证 - SecureVault</title>
<style>body{background:#1e1e1e;color:#eee;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}form{background:#2b2b2b;padding:30px;border-radius:10px;width:300px}input,select,button{width:100%;padding:8px;margin:5px 0;background:#3c3c3c;border:1px solid #555;color:#eee;border-radius:3px}button{background:#5a8cbf;cursor:pointer}.error{color:#ff6b6b}</style>
<script>
function toggleQuestion() {
    var method = document.getElementById('method').value;
    var qDiv = document.getElementById('question_div');
    var emailDiv = document.getElementById('email_div');
    if (method === 'question') { qDiv.style.display = 'block'; } else { qDiv.style.display = 'none'; }
    if (method === 'email') { emailDiv.style.display = 'block'; } else { emailDiv.style.display = 'none'; }
}
function sendCode() {
    var btn = document.getElementById('send_code_btn');
    btn.disabled = true;
    btn.textContent = '发送中...';
    fetch('/send_code', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) { alert('验证码已发送至您的邮箱'); } else { alert('发送失败: ' + data.message); }
        })
        .catch(err => alert('请求失败'))
        .finally(() => { btn.disabled = false; btn.textContent = '发送验证码'; });
}
window.onload = function() { toggleQuestion(); document.getElementById('method').addEventListener('change', toggleQuestion); }
</script>
</head><body>
<form method="post">
<h2>二次验证 - {{ entry.original_name }}</h2>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<select id="method" name="method">
{% for m in methods %}<option value="{{ m }}">{{ m }}</option>{% endfor %}
</select>
<div id="question_div" style="display:none;">
<select name="question">
{% for q in questions %}<option value="{{ q }}">{{ q }}</option>{% endfor %}
</select>
</div>
<div id="email_div" style="display:none;">
<button type="button" id="send_code_btn" onclick="sendCode()">发送验证码</button>
</div>
<input type="text" name="input" placeholder="输入验证信息">
<button type="submit">验证</button>
</form>
</body></html>"""

WEB_VIEW_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>预览 - SecureVault</title>
<style>body{background:#1e1e1e;color:#eee;padding:10px}pre{background:#2b2b2b;padding:10px;border-radius:5px;white-space:pre-wrap;word-wrap:break-word}img{max-width:100%;border-radius:5px}</style>
</head><body><h2>{{ entry.original_name }}</h2><p><a href="/">返回列表</a> | <a href="/download/{{ entry.id }}">下载</a></p>
{% set ext = entry.ext|lower %}
{% if entry.type == 'text' %}<pre>{{ data.decode('utf-8', errors='replace') }}</pre>
{% elif entry.type == 'image' %}<img src="data:image/{{ ext[1:] }};base64,{{ data|b64encode }}" />
{% else %}<p>此文件类型不支持在线预览，请下载后查看。</p>{% endif %}
</body></html>"""
