import os
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders


# 单个邮件附件大小上限（字节）
MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024  # 20 MB


class BackupManager:
    @classmethod
    def send_vault_file(cls, file_path, to_email, smtp_config, display_name=None):
        if display_name is None:
            display_name = os.path.basename(file_path)
        display_name = os.path.basename(display_name).replace('\r', '_').replace('\n', '_')

        # 修复 #2：在同一 open() 上下文中完成大小检查与读取，
        # 避免 getsize() 与 read() 之间文件被替换或追加的 TOCTOU 窗口。
        msg = MIMEMultipart()
        msg['Subject'] = 'SecureVault 紧急备份 - 加密文件'
        msg['From'] = smtp_config['sender_email']
        msg['To'] = to_email
        with open(file_path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size > MAX_ATTACHMENT_SIZE:
                raise ValueError(
                    f"文件过大（{size / 1024 / 1024:.1f} MB），"
                    f"超过邮件附件上限（{MAX_ATTACHMENT_SIZE // 1024 // 1024} MB）")
            f.seek(0)
            payload = f.read()
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(payload)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename={display_name}')
        msg.attach(part)
        with smtplib.SMTP(smtp_config['smtp_server'], smtp_config['port'], timeout=20) as server:
            server.starttls()
            server.login(smtp_config['sender_email'], smtp_config['password'])
            server.sendmail(smtp_config['sender_email'], [to_email], msg.as_string())

    @classmethod
    def send_multiple_vault_files(cls, file_info_list, to_email, smtp_config):
        """
        发送多个 .vault 文件。若任一文件发送失败会抛出异常，
        确保调用方能正确处理错误，避免误删文件。
        """
        for file_path, display_name in file_info_list:
            cls.send_vault_file(file_path, to_email, smtp_config, display_name)
