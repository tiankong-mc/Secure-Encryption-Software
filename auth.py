import bcrypt
import pyotp
import qrcode
from io import BytesIO
import smtplib
from email.mime.text import MIMEText
import random
import string
import base64

class AuthManager:
    def __init__(self, settings_manager):
        self.settings = settings_manager
        self.settings_dict = self.settings.load_settings()
        self._init_auth_data()

    def _init_auth_data(self):
        self.password_hash = self.settings_dict.get('password_hash')
        self.qa = self.settings_dict.get('qa', {})
        self.totp_secret = self.settings_dict.get('totp_secret')
        self.email_config = self.settings_dict.get('email', {})
        self.fail_count = self.settings_dict.get('fail_count', 0)
        self.initialized = self.settings_dict.get('initialized', False)
        self.recovery_code_encrypted_b64 = self.settings_dict.get('recovery_code_encrypted_b64', None)
        self.recovery_code_used = self.settings_dict.get('recovery_code_used', True)

    def _save(self):
        self.settings.save_settings(self.settings_dict)

    # ---------- 密码 ----------
    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        self.settings_dict['password_hash'] = self.password_hash
        self._save()

    def verify_password(self, password):
        if not self.password_hash:
            return False
        return bcrypt.checkpw(password.encode(), self.password_hash.encode())

    # ---------- 安全问题 ----------
    def set_questions(self, qa_list):
        for q, a in qa_list:
            self.qa[q] = bcrypt.hashpw(a.encode(), bcrypt.gensalt()).decode()
        self.settings_dict['qa'] = self.qa
        self._save()

    def verify_question(self, question, answer):
        if question not in self.qa:
            return False
        return bcrypt.checkpw(answer.encode(), self.qa[question].encode())

    def get_questions(self):
        return list(self.qa.keys())

    # ---------- TOTP ----------
    def setup_totp(self):
        self.totp_secret = pyotp.random_base32()
        self.settings_dict['totp_secret'] = self.totp_secret
        self._save()
        totp = pyotp.TOTP(self.totp_secret)
        uri = totp.provisioning_uri(name="SecureVault", issuer_name="SecureApp")
        img = qrcode.make(uri)
        buf = BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def verify_totp(self, code):
        if not self.totp_secret:
            return False
        totp = pyotp.TOTP(self.totp_secret)
        return totp.verify(code)

    # ---------- 邮箱验证码 ----------
    def set_email_config(self, smtp_server, port, sender_email, password, receiver_email):
        self.email_config = {
            'smtp_server': smtp_server,
            'port': port,
            'sender_email': sender_email,
            'password': password,
            'receiver_email': receiver_email
        }
        self.settings_dict['email'] = self.email_config
        self._save()

    def send_verification_code(self, to_email=None):
        if not to_email:
            to_email = self.email_config.get('receiver_email')
        if not to_email:
            return None
        code = str(random.randint(100000, 999999))
        msg = MIMEText(f'您的SecureVault验证码是：{code}')
        msg['Subject'] = 'SecureVault验证码'
        msg['From'] = self.email_config['sender_email']
        msg['To'] = to_email
        try:
            server = smtplib.SMTP(self.email_config['smtp_server'], self.email_config['port'])
            server.starttls()
            server.login(self.email_config['sender_email'], self.email_config['password'])
            server.sendmail(self.email_config['sender_email'], [to_email], msg.as_string())
            server.quit()
            return code
        except Exception as e:
            print(f"邮件发送失败: {e}")
            return None

    # ---------- 失败计数 ----------
    def increment_fail_count(self):
        self.fail_count += 1
        self.settings_dict['fail_count'] = self.fail_count
        self._save()
        return self.fail_count

    def reset_fail_count(self):
        self.fail_count = 0
        self.settings_dict['fail_count'] = 0
        self._save()

    # ---------- 紧急恢复代码 ----------
    def generate_recovery_code(self):
        chars = string.ascii_uppercase + string.digits
        raw = ''.join(random.choice(chars) for _ in range(20))
        formatted = '-'.join(raw[i:i+4] for i in range(0, 20, 4))
        encrypted = self.settings.dpapi.protect(formatted.encode())
        encrypted_b64 = base64.b64encode(encrypted).decode()
        self.settings_dict['recovery_code_encrypted_b64'] = encrypted_b64
        self.settings_dict['recovery_code_used'] = False
        self._save()
        # 发送邮件通知（不包含代码）
        self._send_recovery_email(generated=True)
        return formatted

    def verify_recovery_code(self, input_code):
        encrypted_b64 = self.settings_dict.get('recovery_code_encrypted_b64')
        if not encrypted_b64:
            return False
        used = self.settings_dict.get('recovery_code_used', True)
        if used:
            return False
        try:
            encrypted = base64.b64decode(encrypted_b64)
            stored_code = self.settings.dpapi.unprotect(encrypted).decode()
        except Exception:
            return False
        if stored_code == input_code:
            self.settings_dict['recovery_code_used'] = True
            self._save()
            # 发送邮件通知使用（不包含代码）
            self._send_recovery_email(generated=False)
            return True
        return False

    def _send_recovery_email(self, generated=True):
        """发送紧急恢复代码相关邮件（不包含代码内容）"""
        smtp_config = self.email_config
        if not smtp_config:
            return
        to_email = smtp_config.get('receiver_email')
        if not to_email:
            return
        if generated:
            subject = '紧急恢复代码已生成'
            body = '您的SecureVault紧急恢复代码已生成，旧代码已失效。\n\n请登录软件，在“设置”中查看并妥善保管新的紧急恢复代码。'
        else:
            subject = '紧急恢复代码已使用'
            body = '您的SecureVault紧急恢复代码已被使用，该代码已失效。\n\n如非本人操作，请立即修改密码和安全设置。'
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = smtp_config['sender_email']
        msg['To'] = to_email
        try:
            server = smtplib.SMTP(smtp_config['smtp_server'], smtp_config['port'])
            server.starttls()
            server.login(smtp_config['sender_email'], smtp_config['password'])
            server.sendmail(smtp_config['sender_email'], [to_email], msg.as_string())
            server.quit()
        except Exception as e:
            print(f"紧急恢复邮件发送失败: {e}")

    def is_recovery_code_available(self):
        encrypted_b64 = self.settings_dict.get('recovery_code_encrypted_b64')
        if not encrypted_b64:
            return False
        used = self.settings_dict.get('recovery_code_used', True)
        return not used
