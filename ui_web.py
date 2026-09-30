from mail_security import secure_smtp
import os, secrets, smtplib, threading, time, ipaddress, socket, tempfile
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from io import BytesIO
import hashlib, json, math
from urllib.parse import urlsplit
from flask import Flask, request, render_template_string, session, redirect, url_for, jsonify, send_file
from werkzeug.serving import make_server
from constants import VERSION, WEB_PORT

flask_app = Flask(__name__)
flask_app.secret_key = os.urandom(24)
flask_app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Strict',
    SESSION_COOKIE_SECURE=True,
    MAX_CONTENT_LENGTH=16 * 1024,
    MAX_FORM_MEMORY_SIZE=16 * 1024,
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    SESSION_REFRESH_EACH_REQUEST=False,
)
web_storage = None
web_auth = None
_server = None
_server_thread = None
_server_is_https = False

EMAIL_CODE_TTL = 300
EMAIL_CODE_COOLDOWN = 60
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 60
MAX_RATE_ENTRIES = 1000
MAX_EMAIL_CODE_ATTEMPTS = 5
# M3：服务端验证码字典的软上限，超过后按最旧清理
MAX_EMAIL_CODES = 1000
SESSION_TTL = 1800
SECOND_AUTH_TTL = 300
_email_global_last_sent = 0
_op_rates = {}

_rate_lock = threading.Lock()
_login_rates = {}
_email_rates = {}

# ---------- A2：服务端邮箱验证码存储 ----------
# Codes are bound to an unpredictable browser session ID and operation.
_email_codes = {}
_email_codes_lock = threading.Lock()

_CERT_DIR_CACHE = None


# ============================================================
#  自签名证书（A1）
# ============================================================
def _get_cert_dir():
    global _CERT_DIR_CACHE
    if _CERT_DIR_CACHE is None:
        appdata = os.environ.get('APPDATA') or tempfile.gettempdir()
        _CERT_DIR_CACHE = os.path.join(appdata, 'SecureVault')
        os.makedirs(_CERT_DIR_CACHE, exist_ok=True)
    return _CERT_DIR_CACHE


def _get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def _cert_not_after(cert_obj):
    """
    修复 M1：兼容 cryptography < 42。

    - cryptography 42+ 提供 not_valid_after_utc（带时区）
    - 41 及更早版本只有 not_valid_after（naive datetime）
    统一返回带 UTC 时区的 datetime。
    """
    try:
        not_after = cert_obj.not_valid_after_utc
    except AttributeError:
        not_after = cert_obj.not_valid_after
    if not_after.tzinfo is None:
        not_after = not_after.replace(tzinfo=timezone.utc)
    return not_after


def _ensure_self_signed_cert():
    """
    生成（或复用）自签名证书，返回 (cert_path, key_path)。

    依赖 cryptography。若不可用，调用方必须停止启动。
    证书有效期 1 年，SAN 含 localhost / 127.0.0.1 / 当前局域网 IP。
    """
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    cert_dir = _get_cert_dir()
    cert_path = os.path.join(cert_dir, 'web_cert.pem')
    key_path = os.path.join(cert_dir, 'web_key.pem')

    if os.path.exists(cert_path) and os.path.exists(key_path):
        # 检查证书是否仍然有效（未过期）
        try:
            with open(cert_path, 'rb') as f:
                cert_obj = x509.load_pem_x509_certificate(f.read())
            now = datetime.now(timezone.utc)
            not_after = _cert_not_after(cert_obj)
            if not_after > now + timedelta(days=7):
                return cert_path, key_path
        except Exception:
            # 证书损坏或解析失败 → 重新生成
            pass

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SecureVault"),
        x509.NameAttribute(NameOID.COMMON_NAME, "SecureVault Self-Signed"),
    ])

    san_entries = [x509.DNSName("localhost")]

    lan_ip = _get_lan_ip()
    if lan_ip:
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(lan_ip)))
        except ValueError:
            san_entries.append(x509.DNSName(lan_ip))

    for loopback in ('127.0.0.1', '::1'):
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(loopback)))
        except ValueError:
            pass

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .sign(key, hashes.SHA256())
    )

    with open(key_path, 'wb') as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
    try:
        os.chmod(key_path, 0o600)
    except Exception:
        pass

    with open(cert_path, 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return cert_path, key_path


def _configure_transport_security(https_on):
    flask_app.config['SESSION_COOKIE_SECURE'] = bool(https_on)


def is_https_enabled():
    return bool(_server_is_https)


# ============================================================
#  限流辅助
# ============================================================
def _cleanup_rates_locked(rates, ttl_seconds):
    if len(rates) <= MAX_RATE_ENTRIES:
        return
    now = time.time()
    to_remove = []
    for k, v in list(rates.items()):
        if isinstance(v, dict):
            lock_until = v.get('lock_until', 0)
            failures = v.get('failures', 0)
            last_seen = v.get('last_seen', 0)
            if lock_until and lock_until < now and failures == 0:
                to_remove.append(k)
                continue
            if last_seen and now - last_seen > ttl_seconds:
                to_remove.append(k)
        else:
            if now - v > ttl_seconds:
                to_remove.append(k)
    for k in to_remove:
        rates.pop(k, None)


def _auth_fingerprint():
    if not web_auth:
        return ''
    data = {key: web_auth.settings_dict.get(key)
            for key in web_auth.BACKUP_AUTH_KEYS}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _is_authenticated():
    valid = (session.get('authenticated') is True
             and session.get('auth_expiry', 0) > time.time()
             and session.get('auth_fingerprint') == _auth_fingerprint()
             and session.get('auth_client') == request.remote_addr)
    if not valid and session.get('authenticated'):
        session.clear()
    return valid


def _csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']


def _email_scope(purpose):
    if 'challenge_id' not in session:
        session['challenge_id'] = secrets.token_urlsafe(32)
    return session['challenge_id'], purpose


@flask_app.context_processor
def security_template_context():
    purpose = ('second_auth:' + request.view_args['entry_id']
               if request.endpoint == 'web_second_auth' else 'login')
    return {'csrf_token': _csrf_token(), 'email_purpose': purpose}


@flask_app.before_request
def restrict_to_local_network():
    try:
        address = ipaddress.ip_address(request.remote_addr or '')
        address = getattr(address, 'ipv4_mapped', None) or address
    except ValueError:
        return "拒绝访问", 403
    if not (address.is_private or address.is_loopback or address.is_link_local):
        return "仅允许局域网访问", 403
    # Host must be a local IP literal or localhost, never an arbitrary DNS name.
    # This prevents a hostile website from rebinding its domain to this service.
    try:
        hostname = urlsplit(request.host_url).hostname
        host_address = ipaddress.ip_address(hostname) if hostname != 'localhost' else None
        if host_address and not (host_address.is_private or host_address.is_loopback
                                 or host_address.is_link_local):
            return "请求主机无效", 403
    except ValueError:
        return "请求主机无效", 403
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('Origin')
        if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
            return "请求来源无效", 403
        expected = session.get('csrf_token')
        supplied = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token', '')
        if not expected or not supplied.isascii() or not secrets.compare_digest(expected, supplied):
            return "请求验证失败，请刷新页面", 403


@flask_app.after_request
def security_headers(response):
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'; object-src 'none'")
    return response


def _enabled_methods():
    return web_auth.get_enabled_methods() if web_auth else []


def _login_lock_remaining(client, operation=False):
    persistent = (web_auth.get_op_lock_remaining() if operation
                  else web_auth.get_login_lock_remaining()) if web_auth else 0
    if persistent:
        return persistent
    rates = _op_rates if operation else _login_rates
    with _rate_lock:
        state = rates.get(client)
        if not state:
            return 0
        lock_until = state.get('lock_until', 0)
        if lock_until > 0 and lock_until <= time.time():
            rates.pop(client, None)
            return 0
        return max(0, math.ceil(lock_until - time.time()))


def _record_login_result(client, succeeded, operation=False):
    if web_auth:
        if operation:
            action = web_auth.reset_op_lock if succeeded else web_auth.register_op_failure
        else:
            action = web_auth.reset_login_lock if succeeded else web_auth.register_login_failure
        action()
    rates = _op_rates if operation else _login_rates
    with _rate_lock:
        if succeeded:
            rates.pop(client, None)
        else:
            state = rates.setdefault(
                client, {'failures': 0, 'lock_until': 0, 'last_seen': 0})
            state['failures'] += 1
            state['last_seen'] = time.time()
            if state['failures'] >= LOGIN_MAX_ATTEMPTS:
                state['failures'] = 0
                state['lock_until'] = time.time() + LOGIN_LOCK_SECONDS
        _cleanup_rates_locked(rates, LOGIN_LOCK_SECONDS * 2)


# ============================================================
#  A2：服务端邮箱验证码管理
# ============================================================
def _store_email_code(client, code):
    """
    把验证码存到服务端（不写 session）。
    M3：超过 MAX_EMAIL_CODES 时按创建时间最旧的清理。
    """
    now = time.time()
    with _email_codes_lock:
        _email_codes[client] = {
            'code': code,
            'expiry': now + EMAIL_CODE_TTL,
            'attempts': 0,
            'created_at': now,
        }
        # 清理已过期的
        expired = [k for k, v in _email_codes.items()
                   if v.get('expiry', 0) < now]
        for k in expired:
            _email_codes.pop(k, None)
        # M3：软上限，按最旧的清理
        if len(_email_codes) > MAX_EMAIL_CODES:
            overflow = len(_email_codes) - MAX_EMAIL_CODES
            oldest = sorted(_email_codes.items(),
                            key=lambda kv: kv[1].get('created_at', 0))[:overflow]
            for k, _ in oldest:
                _email_codes.pop(k, None)


def _email_code_matches(client, value):
    """
    从服务端校验验证码：
      - 过期即失效
      - 超过 MAX_EMAIL_CODE_ATTEMPTS 次失败即作废（防暴力）
      - 校验成功后立即消费
    """
    now = time.time()
    with _email_codes_lock:
        entry = _email_codes.get(client)
        if not entry:
            return False
        if entry.get('expiry', 0) <= now:
            _email_codes.pop(client, None)
            return False
        entry['attempts'] = entry.get('attempts', 0) + 1
        if entry['attempts'] > MAX_EMAIL_CODE_ATTEMPTS:
            _email_codes.pop(client, None)
            return False
        if (isinstance(value, str) and value.isascii()
                and secrets.compare_digest(value, str(entry.get('code', '')))):
            _email_codes.pop(client, None)
            return True
    return False


def _reserve_email_send(client):
    """
    预占位：锁内检查+写入，避免并发请求全部通过冷却检查。
    返回 0 表示已占用成功；否则返回还需等待的秒数。
    """
    global _email_global_last_sent
    now = time.time()
    with _rate_lock:
        last_sent = max(_email_rates.get(client, 0), _email_global_last_sent)
        if now - last_sent < EMAIL_CODE_COOLDOWN:
            return max(1, int(EMAIL_CODE_COOLDOWN - (now - last_sent)) + 1)
        _email_rates[client] = now
        _email_global_last_sent = now
        _cleanup_rates_locked(_email_rates, EMAIL_CODE_TTL * 2)
    return 0


def _rollback_email_send(client):
    with _rate_lock:
        _email_rates.pop(client, None)


@flask_app.template_filter('b64encode')
def b64encode_filter(data):
    import base64
    return base64.b64encode(data).decode('utf-8')


@flask_app.route('/')
def web_index():
    if not _is_authenticated():
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
            ok = _email_code_matches(_email_scope('login'), inp)
        if ok:
            web_storage.log("移动端登录成功")
            _record_login_result(client, True)
            session.clear()
            session.permanent = True
            session['authenticated'] = True
            session['auth_expiry'] = time.time() + SESSION_TTL
            session['auth_client'] = request.remote_addr
            session['auth_fingerprint'] = _auth_fingerprint()
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
    if not _is_authenticated():
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
    if not _is_authenticated():
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
        wait_seconds = _login_lock_remaining(client, operation=True)
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
            ok = _email_code_matches(_email_scope('second_auth:' + entry_id), inp)
        if ok:
            web_storage.log(f"移动端二次验证成功 (文件ID: {entry_id})")
            _record_login_result(client, True, operation=True)
            second_auth = dict(session.get('second_auth', {}))
            second_auth[entry_id] = {
                'expiry': datetime.now(timezone.utc).timestamp() + SECOND_AUTH_TTL,
                'client': client,
            }
            session['second_auth'] = second_auth
            data = web_storage.get_file_data(entry_id)
            return render_template_string(WEB_VIEW_TEMPLATE, data=data, entry=entry)
        else:
            web_storage.log(f"移动端二次验证失败 (文件ID: {entry_id})")
            _record_login_result(client, False, operation=True)
            return render_template_string(WEB_SECOND_AUTH_TEMPLATE, entry=entry, methods=allowed_methods, questions=questions, error="验证失败")
    return render_template_string(WEB_SECOND_AUTH_TEMPLATE, entry=entry, methods=allowed_methods, questions=questions, error=None)


@flask_app.route('/download/<entry_id>')
def web_download(entry_id):
    if not _is_authenticated():
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
    """Only a current authenticated session can hold a recent per-file grant."""
    if not _is_authenticated():
        return False
    second_auth = session.get('second_auth', {})
    record = second_auth.get(entry_id, 0)
    now_ts = datetime.now(timezone.utc).timestamp()
    if isinstance(record, dict):
        expiry = record.get('expiry', 0)
        client_in_record = record.get('client')
        current_client = request.remote_addr or 'unknown'
        return (expiry > now_ts) and (client_in_record == current_client)
    return False


@flask_app.route('/send_code', methods=['POST'])
def send_code():
    if 'email' not in _enabled_methods() or not web_auth.email_config:
        return jsonify({'success': False, 'message': '邮箱未配置或未启用'}), 400
    purpose = request.headers.get('X-Email-Purpose', '')
    if purpose == 'login':
        if _is_authenticated():
            return jsonify({'success': False, 'message': '请使用文件二次验证页面'}), 400
    elif purpose.startswith('second_auth:'):
        entry_id = purpose.split(':', 1)[1]
        if not _is_authenticated():
            return jsonify({'success': False, 'message': '请先登录'}), 401
        entry = web_storage.get_entry_by_id(entry_id)
        if not entry or 'email' not in entry.get('second_auth_methods', []):
            return jsonify({'success': False, 'message': '不允许的验证方式'}), 403
    else:
        return jsonify({'success': False, 'message': '验证用途无效'}), 400
    client = request.remote_addr or 'unknown'
    wait = _login_lock_remaining(client, operation=(purpose != 'login'))
    if wait:
        return jsonify({'success': False, 'message': '验证已锁定'}), 429
    wait = _reserve_email_send(client)
    if wait:
        return jsonify({'success': False,
                        'message': f'发送过于频繁，请 {wait} 秒后再试'}), 429

    code = ''.join(secrets.choice('0123456789') for _ in range(6))
    config = web_auth.email_config
    to_email = config.get('receiver_email')
    if not to_email:
        _rollback_email_send(client)
        return jsonify({'success': False, 'message': '未设置收件邮箱'}), 400
    msg = MIMEText(f'您的SecureVault验证码是：{code}')
    msg['Subject'] = 'SecureVault验证码'
    msg['From'] = config['sender_email']
    msg['To'] = to_email
    try:
        with secure_smtp(config['smtp_server'], config['port'], timeout=20) as server:
            server.login(config['sender_email'], config['password'])
            server.sendmail(config['sender_email'], [to_email], msg.as_string())
    except Exception as e:
        _rollback_email_send(client)
        if web_storage:
            web_storage.log(f"移动端邮箱验证码发送失败: {e}")
        return jsonify({'success': False, 'message': '邮件发送失败，请检查桌面端日志'}), 500
    web_storage.log(f"移动端发送邮箱验证码至: {to_email}")

    _store_email_code(_email_scope(purpose), code)

    return jsonify({'success': True, 'message': '验证码已发送'})


# ============================================================
#  服务启动/停止
# ============================================================
def start_web_server(storage, auth, enable_https=True):
    global web_storage, web_auth, _server, _server_thread, _server_is_https
    web_storage = storage
    web_auth = auth
    if _server is not None:
        return True

    ssl_context = None
    https_on = False

    if enable_https:
        try:
            cert_path, key_path = _ensure_self_signed_cert()
            ssl_context = (cert_path, key_path)
            https_on = True
        except Exception as e:
            print(f"HTTPS 初始化失败，已停止启动: {e}")
            return False

    _configure_transport_security(https_on)

    try:
        if https_on:
            print("\n🔒 Web服务已启用 HTTPS（自签名证书）。")
            print("   浏览器会提示证书不受信任，请手动选择“继续访问”。")
        else:
            print("\n⚠️ 警告：Web服务使用明文HTTP，仅允许本机访问。")
            print("   手机或其他设备访问必须启用 HTTPS。")

        bind_host = '0.0.0.0' if https_on else '127.0.0.1'
        flask_app.secret_key = os.urandom(32)
        with _email_codes_lock:
            _email_codes.clear()
        if ssl_context:
            _server = make_server(bind_host, WEB_PORT, flask_app, ssl_context=ssl_context)
        else:
            _server = make_server(bind_host, WEB_PORT, flask_app)

        _server_is_https = https_on
        _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
        _server_thread.start()
        return True
    except Exception as e:
        _server = None
        _server_thread = None
        _server_is_https = False
        print(f"Web server error: {e}")
        return False


def stop_web_server():
    global _server, _server_thread, _server_is_https
    flask_app.secret_key = os.urandom(32)
    with _email_codes_lock:
        _email_codes.clear()
    if _server is not None:
        try:
            _server.shutdown()
        except Exception:
            pass
        _server = None
        _server_thread = None
        _server_is_https = False


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
    document.getElementById('auth_input').type = (method === 'password' || method === 'question') ? 'password' : 'text';
    var qDiv = document.getElementById('question_div');
    var emailDiv = document.getElementById('email_div');
    if (method === 'question') { qDiv.style.display = 'block'; } else { qDiv.style.display = 'none'; }
    if (method === 'email') { emailDiv.style.display = 'block'; } else { emailDiv.style.display = 'none'; }
}
function sendCode() {
    var btn = document.getElementById('send_code_btn');
    btn.disabled = true;
    btn.textContent = '发送中...';
    fetch('/send_code', { method: 'POST', headers: { 'X-CSRF-Token': {{ csrf_token|tojson }}, 'X-Email-Purpose': {{ email_purpose|tojson }} } })
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
<input type="hidden" name="csrf_token" value="{{ csrf_token }}">
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
<input id="auth_input" type="password" name="input" placeholder="输入验证信息" autocomplete="off">
<button type="submit">登录</button>
</form>
</body></html>"""

WEB_SECOND_AUTH_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>二次验证 - SecureVault</title>
<style>body{background:#1e1e1e;color:#eee;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}form{background:#2b2b2b;padding:30px;border-radius:10px;width:300px}input,select,button{width:100%;padding:8px;margin:5px 0;background:#3c3c3c;border:1px solid #555;color:#eee;border-radius:3px}button{background:#5a8cbf;cursor:pointer}.error{color:#ff6b6b}</style>
<script>
function toggleQuestion() {
    var method = document.getElementById('method').value;
    document.getElementById('auth_input').type = (method === 'password' || method === 'question') ? 'password' : 'text';
    var qDiv = document.getElementById('question_div');
    var emailDiv = document.getElementById('email_div');
    if (method === 'question') { qDiv.style.display = 'block'; } else { qDiv.style.display = 'none'; }
    if (method === 'email') { emailDiv.style.display = 'block'; } else { emailDiv.style.display = 'none'; }
}
function sendCode() {
    var btn = document.getElementById('send_code_btn');
    btn.disabled = true;
    btn.textContent = '发送中...';
    fetch('/send_code', { method: 'POST', headers: { 'X-CSRF-Token': {{ csrf_token|tojson }}, 'X-Email-Purpose': {{ email_purpose|tojson }} } })
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
<input type="hidden" name="csrf_token" value="{{ csrf_token }}">
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
<input id="auth_input" type="password" name="input" placeholder="输入验证信息" autocomplete="off">
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
