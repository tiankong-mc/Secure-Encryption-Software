import os, random, smtplib, threading
from datetime import datetime
from email.mime.text import MIMEText
from io import BytesIO
from flask import Flask, request, render_template_string, session, redirect, url_for, jsonify, send_file
from werkzeug.serving import make_server
from constants import VERSION, WEB_PORT

flask_app = Flask(__name__)
flask_app.secret_key = os.urandom(24)
web_storage = None
web_auth = None
_server = None
_server_thread = None


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
    if request.method == 'POST':
        method = request.form.get('method', 'password')
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
            stored_code = session.get('email_code')
            if stored_code and inp == stored_code:
                ok = True
                session.pop('email_code', None)
        if ok:
            web_storage.log("移动端登录成功")
            session['authenticated'] = True
            return redirect(url_for('web_index'))
        else:
            web_storage.log("移动端登录失败")
            return render_template_string(WEB_LOGIN_TEMPLATE, methods=questions, error="验证失败")
    return render_template_string(WEB_LOGIN_TEMPLATE, methods=questions, error=None)


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
        return f"查看失败: {e}", 500


@flask_app.route('/second_auth/<entry_id>', methods=['GET', 'POST'])
def web_second_auth(entry_id):
    if 'authenticated' not in session or not session['authenticated']:
        return redirect(url_for('web_login'))
    entry = web_storage.get_entry_by_id(entry_id)
    if not entry:
        return "文件不存在", 404
    allowed_methods = entry.get('second_auth_methods', [])
    questions = web_auth.get_questions() if web_auth else []
    if request.method == 'POST':
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
            stored_code = session.get('email_code')
            if stored_code and inp == stored_code:
                ok = True
                session.pop('email_code', None)
        if ok:
            web_storage.log(f"移动端二次验证成功 (文件ID: {entry_id})")
            session.setdefault('second_auth', {})[entry_id] = datetime.now().timestamp() + 3600
            data = web_storage.get_file_data(entry_id)
            return render_template_string(WEB_VIEW_TEMPLATE, data=data, entry=entry)
        else:
            web_storage.log(f"移动端二次验证失败 (文件ID: {entry_id})")
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
        return f"下载失败: {e}", 500


def check_second_auth(entry_id):
    second_auth = session.get('second_auth', {})
    expiry = second_auth.get(entry_id, 0)
    return expiry > datetime.now().timestamp()


@flask_app.route('/send_code', methods=['POST'])
def send_code():
    if not web_auth or not web_auth.email_config:
        return jsonify({'success': False, 'message': '邮箱未配置'}), 400
    code = ''.join(random.choices('0123456789', k=6))
    config = web_auth.email_config
    to_email = config.get('receiver_email')
    if not to_email:
        return jsonify({'success': False, 'message': '未设置收件邮箱'}), 400
    msg = MIMEText(f'您的SecureVault验证码是：{code}')
    msg['Subject'] = 'SecureVault验证码'
    msg['From'] = config['sender_email']
    msg['To'] = to_email
    try:
        server = smtplib.SMTP(config['smtp_server'], config['port'])
        server.starttls()
        server.login(config['sender_email'], config['password'])
        server.sendmail(config['sender_email'], [to_email], msg.as_string())
        server.quit()
    except Exception as e:
        return jsonify({'success': False, 'message': f'邮件发送失败: {str(e)}'}), 500
    web_storage.log(f"移动端发送邮箱验证码至: {to_email}")
    session['email_code'] = code
    return jsonify({'success': True, 'message': '验证码已发送'})


def start_web_server(storage, auth):
    """启动 Flask 服务（可被 stop_web_server 关闭）"""
    global web_storage, web_auth, _server, _server_thread
    web_storage = storage
    web_auth = auth
    if _server is not None:
        return  # 已在运行
    try:
        print("\n⚠️ 警告：Web服务使用明文HTTP，仅限可信局域网，公共网络下请勿启用。")
        _server = make_server('0.0.0.0', WEB_PORT, flask_app)
        _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
        _server_thread.start()
    except Exception as e:
        print(f"Web server error: {e}")


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
<option value="password">密码</option>
<option value="question">安全问题</option>
<option value="totp">TOTP</option>
<option value="email">邮箱验证码</option>
</select>
<div id="question_div" style="display:none;">
<select name="question">
{% for q in methods %}<option value="{{ q }}">{{ q }}</option>{% endfor %}
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
