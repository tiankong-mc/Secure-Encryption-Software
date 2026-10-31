from mail_security import secure_smtp
import bcrypt, pyotp, qrcode, secrets, string, base64, hmac, time, threading, math
from functools import wraps
from io import BytesIO
from email.mime.text import MIMEText

def _serialized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._auth_lock: return method(self, *args, **kwargs)
    return wrapped

class AuthManager:
    def __init__(self, settings_manager):
        self._auth_lock = threading.RLock()
        self.recovery_verified_until = 0
        self.settings = settings_manager
        self.settings_dict = self.settings.load_settings()
        self._init_auth_data()

    def _init_auth_data(self):
        self.password_hash = self.settings_dict.get('password_hash')
        self.qa = self.settings_dict.get('qa', {})
        self.totp_secret = self.settings_dict.get('totp_secret')
        self.email_config = self.settings_dict.get('email', {})
        self.initialized = self.settings_dict.get('initialized', False)
        self.method_enabled = self.settings_dict.get('method_enabled', {})
        self.recovery_code_used = self.settings_dict.get('recovery_code_used', True)

    @_serialized
    def _save(self): self.settings.save_settings(self.settings_dict)

    def get_configured_methods(self):
        result = []
        if self.password_hash: result.append('password')
        if self.qa: result.append('question')
        if self.totp_secret: result.append('totp')
        if self.email_config: result.append('email')
        return result

    def is_method_enabled(self, name): return self.settings_dict.get('method_enabled', {}).get(name, True)

    def get_enabled_methods(self):
        enabled = self.settings_dict.get('method_enabled', {})
        result = []
        if self.password_hash and enabled.get('password', True): result.append('password')
        if self.qa and enabled.get('question', True): result.append('question')
        if self.totp_secret and enabled.get('totp', True): result.append('totp')
        if self.email_config and enabled.get('email', True): result.append('email')
        return result

    def set_method_enabled(self, name, value):
        enabled = dict(self.settings_dict.get('method_enabled', {}))
        enabled[name] = value
        if not [m for m in self.get_configured_methods() if enabled.get(m, True)]: return False
        self.settings_dict['method_enabled'] = enabled
        self._save()
        return True

    @_serialized
    def set_password(self, password):
        encoded = password.encode('utf-8')
        if len(password) < 6 or len(encoded) > 72: raise ValueError('密码格式错误')
        self.password_hash = bcrypt.hashpw(encoded, bcrypt.gensalt()).decode()
        self.settings_dict['password_hash'] = self.password_hash
        self._save()

    def verify_password(self, password):
        if not self.password_hash: return False
        return self._check_bcrypt(password, self.password_hash)

    @staticmethod
    def _check_bcrypt(value, stored_hash):
        if not isinstance(value, str) or not isinstance(stored_hash, str): return False
        encoded = value.encode('utf-8')
        if not encoded or len(encoded) > 72: return False
        try: return bcrypt.checkpw(encoded, stored_hash.encode('ascii'))
        except Exception: return False

    @_serialized
    def set_questions(self, qa_list):
        qa = {}
        for q, a in qa_list:
            encoded = a.encode('utf-8')
            if not encoded or len(encoded) > 72: raise ValueError('答案长度错误')
            qa[q] = bcrypt.hashpw(encoded, bcrypt.gensalt()).decode()
        self.qa = qa
        self.settings_dict['qa'] = self.qa
        self._save()

    def verify_question(self, question, answer):
        if question not in self.qa: return False
        return self._check_bcrypt(answer, self.qa[question])

    def get_questions(self): return list(self.qa.keys())

    @_serialized
    def verify_totp(self, code, domain='login'):
        if not self.totp_secret or not isinstance(code, str) or len(code) != 6: return False
        try:
            totp = pyotp.TOTP(self.totp_secret)
            now = time.time()
            counter = int(now // totp.interval)
            last_counter = self.settings_dict.get(f'totp_last_counter_{domain}', -1)
            if counter <= last_counter: return False
            if not totp.verify(code, for_time=now): return False
            self.settings_dict[f'totp_last_counter_{domain}'] = counter
            self._save()
            return True
        except Exception: return False

    def generate_totp_secret(self): return pyotp.random_base32()

    def verify_totp_secret(self, secret, code):
        try: return pyotp.TOTP(secret).verify(code)
        except Exception: return False

    @_serialized
    def save_totp_secret(self, secret):
        self.totp_secret = secret
        self.settings_dict['totp_secret'] = secret
        self.settings_dict.pop('totp_last_counter_login', None)
        self._save()

    def set_email_config(self, smtp_server, port, sender_email, password, receiver_email):
        self.email_config = {'smtp_server': smtp_server, 'port': port, 'sender_email': sender_email, 'password': password, 'receiver_email': receiver_email}
        self.settings_dict['email'] = self.email_config
        self._save()

    def send_verification_code(self, to_email=None):
        if not to_email: to_email = self.email_config.get('receiver_email')
        if not to_email: return None
        code = ''.join(secrets.choice(string.digits) for _ in range(6))
        msg = MIMEText(f'您的SecureVault验证码是：{code}')
        msg['Subject'] = 'SecureVault验证码'
        msg['From'] = self.email_config['sender_email']
        msg['To'] = to_email
        try:
            with secure_smtp(self.email_config['smtp_server'], self.email_config['port'], timeout=20) as server:
                server.login(self.email_config['sender_email'], self.email_config['password'])
                server.sendmail(self.email_config['sender_email'], [to_email], msg.as_string())
            return code
        except Exception: return None

    def test_email_config(self, smtp_server, port, sender_email, password, receiver_email):
        try:
            code = ''.join(secrets.choice(string.digits) for _ in range(6))
            msg = MIMEText(f'测试邮件，验证码：{code}')
            msg['Subject'] = 'SecureVault 邮箱配置测试'
            msg['From'] = sender_email
            msg['To'] = receiver_email
            with secure_smtp(smtp_server, port, timeout=20) as server:
                server.login(sender_email, password)
                server.sendmail(sender_email, [receiver_email], msg.as_string())
            return True, code
        except Exception as e: return False, str(e)

    def save_email_config(self, *args): self.set_email_config(*args)

    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_BASE_LOCK = 60
    LOGIN_MAX_LOCK = 3600
    OP_MAX_ATTEMPTS = 5
    OP_BASE_LOCK = 60
    OP_MAX_LOCK = 3600
    FILE_MAX_ATTEMPTS = 5

    def get_login_lock_remaining(self):
        try: return max(0, math.ceil(float(self.settings_dict.get('login_lock_until', 0)) - time.time()))
        except Exception: return 0

    def get_op_lock_remaining(self):
        try: return max(0, math.ceil(float(self.settings_dict.get('op_lock_until', 0)) - time.time()))
        except Exception: return 0

    @_serialized
    def register_login_failure(self):
        remaining = self.get_login_lock_remaining()
        if remaining > 0: return 0, remaining
        count = int(self.settings_dict.get('login_fail_count', 0)) + 1
        self.settings_dict['login_fail_count'] = count
        if count >= self.LOGIN_MAX_ATTEMPTS:
            lock_count = int(self.settings_dict.get('login_lock_count', 0))
            duration = self.LOGIN_BASE_LOCK if lock_count == 0 else min(int(self.settings_dict.get('login_lock_duration', self.LOGIN_BASE_LOCK)) * 2, self.LOGIN_MAX_LOCK)
            self.settings_dict['login_lock_duration'] = duration
            self.settings_dict['login_lock_count'] = lock_count + 1
            self.settings_dict['login_lock_until'] = int(time.time()) + duration
            self.settings_dict['login_fail_count'] = 0
            self._save(); return 0, duration
        self._save(); return count, 0

    @_serialized
    def reset_login_lock(self):
        self.settings_dict.pop('login_fail_count', None)
        self.settings_dict.pop('login_lock_until', None)
        self._save()

    @_serialized
    def register_op_failure(self):
        remaining = self.get_op_lock_remaining()
        if remaining > 0: return 0, remaining
        count = int(self.settings_dict.get('op_fail_count', 0)) + 1
        self.settings_dict['op_fail_count'] = count
        if count >= self.OP_MAX_ATTEMPTS:
            lock_count = int(self.settings_dict.get('op_lock_count', 0))
            duration = self.OP_BASE_LOCK if lock_count == 0 else min(int(self.settings_dict.get('op_lock_duration', self.OP_BASE_LOCK)) * 2, self.OP_MAX_LOCK)
            self.settings_dict['op_lock_duration'] = duration
            self.settings_dict['op_lock_count'] = lock_count + 1
            self.settings_dict['op_lock_until'] = int(time.time()) + duration
            self.settings_dict['op_fail_count'] = 0
            self._save(); return 0, duration
        self._save(); return count, 0

    @_serialized
    def reset_op_lock(self):
        self.settings_dict.pop('op_fail_count', None)
        self.settings_dict.pop('op_lock_until', None)
        self._save()

    # ---------- 按文件隔离的失败计数 ----------
    def get_file_fail_count(self, entry_id):
        counts = self.settings_dict.get('file_fail_counts', {})
        return int(counts.get(entry_id, 0))

    @_serialized
    def register_file_failure(self, entry_id):
        counts = dict(self.settings_dict.get('file_fail_counts', {}))
        counts[entry_id] = counts.get(entry_id, 0) + 1
        self.settings_dict['file_fail_counts'] = counts
        self._save()
        return counts[entry_id]

    @_serialized
    def reset_file_fail_count(self, entry_id):
        counts = dict(self.settings_dict.get('file_fail_counts', {}))
        if entry_id in counts:
            del counts[entry_id]
            self.settings_dict['file_fail_counts'] = counts
            self._save()

    # ---------- 恢复代码 ----------
    @_serialized
    def generate_recovery_code(self, send_email=False):
        chars = string.ascii_uppercase + string.digits
        raw = ''.join(secrets.choice(chars) for _ in range(20))
        formatted = '-'.join(raw[i:i+4] for i in range(0, 20, 4))
        encrypted = self.settings.dpapi.protect(formatted.encode())
        self.settings_dict['recovery_code_encrypted_b64'] = base64.b64encode(encrypted).decode()
        self.settings_dict['recovery_code_used'] = False
        self._save()
        if send_email: self._send_recovery_email(generated=True)
        return formatted

    @_serialized
    def clear_recovery_code(self):
        self.settings_dict.pop('recovery_code_encrypted_b64', None)
        self.settings_dict['recovery_code_used'] = True
        self._save()

    @_serialized
    def verify_recovery_code(self, input_code):
        if self.settings_dict.get('recovery_code_used', True): return False
        enc_b64 = self.settings_dict.get('recovery_code_encrypted_b64')
        if not enc_b64: return False
        try:
            stored = self.settings.dpapi.unprotect(base64.b64decode(enc_b64, validate=True)).decode()
        except Exception: return False
        normalized = input_code.strip().upper()
        if not normalized.isascii():
            return False
        if hmac.compare_digest(stored.encode('utf-8'), normalized.encode('utf-8')):
            self.settings_dict['recovery_code_used'] = True
            self._save()
            self.recovery_verified_until = time.time() + 900
            self._send_recovery_email(generated=False)
            return True
        return False

    def _send_recovery_email(self, generated=True):
        if not self.email_config: return
        to_email = self.email_config.get('receiver_email')
        subject = '紧急恢复代码已生成' if generated else '紧急恢复代码已使用'
        body = '您的SecureVault紧急恢复代码已重新生成，旧代码已失效。' if generated else '您的SecureVault紧急恢复代码已被使用。'
        msg = MIMEText(body); msg['Subject'] = subject
        msg['From'] = self.email_config['sender_email']; msg['To'] = to_email
        try:
            with secure_smtp(self.email_config['smtp_server'], self.email_config['port'], timeout=20) as server:
                server.login(self.email_config['sender_email'], self.email_config['password'])
                server.sendmail(self.email_config['sender_email'], [to_email], msg.as_string())
        except Exception: pass

    def send_high_security_enabled_email(self):
        if not self.email_config: return False
        to_email = self.email_config.get('receiver_email')
        if not to_email: return False
        msg = MIMEText("您的 SecureVault 已成功开启高安全模式。\n\n今后启动程序时，必须输入您刚才设置的主密码。\n请务必牢记该密码。如果您忘记了主密码，可以使用在界面中展示的紧急恢复代码解锁。\n\n（注：出于安全考虑，恢复代码不会通过邮件传输。）")
        msg['Subject'] = 'SecureVault 高安全模式已开启'
        msg['From'] = self.email_config['sender_email']; msg['To'] = to_email
        try:
            with secure_smtp(self.email_config['smtp_server'], self.email_config['port'], timeout=20) as server:
                server.login(self.email_config['sender_email'], self.email_config['password'])
                server.sendmail(self.email_config['sender_email'], [to_email], msg.as_string())
            return True
        except Exception: return False

    BACKUP_AUTH_KEYS = ('password_hash', 'qa', 'totp_secret', 'email', 'method_enabled')
    def export_auth_settings(self):
        return {k: v for k, v in self.settings_dict.items() if k in self.BACKUP_AUTH_KEYS and v not in (None, '', {}, [])}

    @_serialized
    def import_auth_settings(self, data):
        if not isinstance(data, dict): return False
        changed = False
        for key in self.BACKUP_AUTH_KEYS:
            if key in data and data[key] not in (None, '', {}, []):
                self.settings_dict[key] = data[key]
                changed = True
        if changed: self._save(); self._init_auth_data()
        return changed