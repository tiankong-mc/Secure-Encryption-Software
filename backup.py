import os
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders

class BackupManager:
    @classmethod
    def send_vault_file(cls, file_path, to_email, smtp_config, display_name=None):
        if display_name is None:
            display_name = os.path.basename(file_path)
        msg = MIMEMultipart()
        msg['Subject'] = 'SecureVault 紧急备份 - 加密文件'
        msg['From'] = smtp_config['sender_email']
        msg['To'] = to_email
        with open(file_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename={display_name}')
            msg.attach(part)
        server = smtplib.SMTP(smtp_config['smtp_server'], smtp_config['port'])
        server.starttls()
        server.login(smtp_config['sender_email'], smtp_config['password'])
        server.sendmail(smtp_config['sender_email'], [to_email], msg.as_string())
        server.quit()

    @classmethod
    def send_multiple_vault_files(cls, file_info_list, to_email, smtp_config):
        """
        发送多个 .vault 文件，若任一文件发送失败则抛出异常，
        确保调用方能正确处理错误，避免误删文件。
        """
        for file_path, display_name in file_info_list:
            cls.send_vault_file(file_path, to_email, smtp_config, display_name)
