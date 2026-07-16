import bcrypt
import pyotp
import qrcode
from io import BytesIO
import smtplib
from email.mime.text import MIMEText
import random
import time
import threading

# 尝试导入Windows Hello相关
try:
    import winrt.windows.foundation.collections as collections
    import winrt.windows.security.credentials.ui as ui
    WINDOWS_HELLO_AVAILABLE = True
except:
    WINDOWS_HELLO_AVAILABLE = False

class AuthManager:
    def __init__(self, settings_manager):
        self.settings = settings_manager
        self.settings_dict = self.settings.load_settings()
        self._init_auth_data()

    def _init_auth_data(self):
        self.password_hash = self.settings_dict.get('password_hash')
        self.qa = self.settings_dict.get('qa', {})          # {question: bcrypt_hash}
        self.totp_secret = self.settings_dict.get('totp_secret')
        self.email_config = self.settings_dict.get('email', {})
        self.windows_hello_enabled = self.settings_dict.get('windows_hello', False)
        self.fail_count = self.settings_dict.get('fail_count', 0)   # 累计失败次数
        self.initialized = self.settings_dict.get('initialized', False)

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
        """qa_list: [(question, answer), ...]"""
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
        # 生成二维码图片数据（bytes）
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
        """生成6位验证码并发送，返回验证码字符串（用于验证）"""
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

    # ---------- Windows Hello ----------
    def enable_windows_hello(self, enable=True):
        if not WINDOWS_HELLO_AVAILABLE and enable:
            return False
        self.windows_hello_enabled = enable
        self.settings_dict['windows_hello'] = enable
        self._save()
        return True

    def verify_windows_hello(self):
        if not self.windows_hello_enabled or not WINDOWS_HELLO_AVAILABLE:
            return False
        try:
            result = ui.UserConsentVerifier.request_verification_async("验证身份以访问SecureVault").get()
            return result == ui.UserConsentVerificationResult.verified
        except:
            return False

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
