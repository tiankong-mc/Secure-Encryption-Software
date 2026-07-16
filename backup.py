import os
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders

class BackupManager:
    @classmethod
    def send_vault_file(cls, file_path, to_email, smtp_config, display_name=None):
        """
        发送 .vault 文件到邮箱，可指定附件显示名称
        display_name: 附件显示的文件名（如 "myfile.txt.vault"），若为 None 则使用原文件名
        """
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
        发送多个 .vault 文件，file_info_list 为 [(file_path, display_name), ...]
        """
        for file_path, display_name in file_info_list:
            try:
                cls.send_vault_file(file_path, to_email, smtp_config, display_name)
            except Exception as e:
                print(f"发送 {file_path} 失败: {e}")
