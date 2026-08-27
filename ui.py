import sys,os,tempfile,shutil,json,threading,socket,webbrowser,urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtMultimedia import QMediaPlayer,QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from io import BytesIO
from PIL import Image,ImageQt
import docx,PyPDF2
from backup import BackupManager
from datetime import datetime
import traceback,requests,qrcode
from flask import Flask, request, render_template_string, session, redirect, url_for

VERSION = "v2.4.0"

DARK_STYLE="""
QMainWindow,QDialog{background:#2b2b2b;color:#f0f0f0}
QWidget{background:#2b2b2b;color:#f0f0f0}
QPushButton{background:#3c3c3c;border:1px solid #555;padding:5px;border-radius:3px;color:#f0f0f0}
QPushButton:hover{background:#4a4a4a}
QPushButton:pressed{background:#2a2a2a}
QLineEdit,QTextEdit,QListWidget,QComboBox,QSpinBox{background:#3c3c3c;border:1px solid #555;color:#f0f0f0}
QLabel{color:#f0f0f0}
QGroupBox{border:1px solid #555;margin-top:10px;color:#f0f0f0}
QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 5px}
QTabWidget::pane{border:1px solid #555;background:#2b2b2b}
QTabBar::tab{background:#3c3c3c;color:#f0f0f0;padding:5px 10px}
QTabBar::tab:selected{background:#4a4a4a}
QScrollBar:vertical{background:#2b2b2b;width:12px}
QScrollBar::handle:vertical{background:#555;border-radius:6px;min-height:20px}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0}
QMenuBar{background:#2b2b2b;color:#f0f0f0}
QMenuBar::item:selected{background:#3c3c3c}
QMenu{background:#2b2b2b;color:#f0f0f0}
QMenu::item:selected{background:#3c3c3c}
QMessageBox{background:#2b2b2b;color:#f0f0f0}
QMessageBox QPushButton{min-width:80px}
QCheckBox{color:#f0f0f0}
QRadioButton{color:#f0f0f0}
QProgressBar{background:#3c3c3c;border:1px solid #555;border-radius:3px;text-align:center;color:#f0f0f0}
QProgressBar::chunk{background:#5a8cbf}
QToolTip{background:#3c3c3c;color:#f0f0f0;border:1px solid #555}
"""
LIGHT_STYLE=""

flask_app=Flask(__name__)
flask_app.secret_key=os.urandom(24)
web_storage=None; web_auth=None; WEB_PORT=8080

@flask_app.route('/')
def web_index():
    if 'authenticated' not in session or not session['authenticated']:
        return redirect(url_for('web_login'))
    entries=web_storage.get_all_entries() if web_storage else []
    return render_template_string(WEB_TEMPLATE, entries=entries, VERSION=VERSION)

@flask_app.route('/login', methods=['GET','POST'])
def web_login():
    questions = web_auth.get_questions() if web_auth else []
    if request.method=='POST':
        method=request.form.get('method','password')
        inp=request.form.get('input','')
        ok=False
        if method=='password':
            ok=web_auth.verify_password(inp) if web_auth else False
        elif method=='question':
            q=request.form.get('question','')
            ok=web_auth.verify_question(q,inp) if web_auth else False
        elif method=='totp':
            ok=web_auth.verify_totp(inp) if web_auth else False
        elif method=='email':
            ok=(inp==request.form.get('code',''))
        if ok:
            session['authenticated']=True
            return redirect(url_for('web_index'))
        else:
            return render_template_string(WEB_LOGIN_TEMPLATE, methods=questions, error="验证失败，请重试")
    return render_template_string(WEB_LOGIN_TEMPLATE, methods=questions, error=None)

@flask_app.route('/view/<entry_id>')
def web_view(entry_id):
    if 'authenticated' not in session or not session['authenticated']:
        return redirect(url_for('web_login'))
    try:
        data=web_storage.get_file_data(entry_id)
        entry=web_storage.get_entry_by_id(entry_id)
        if not entry: return "文件不存在",404
        if entry.get('is_advanced',False):
            return redirect(url_for('web_second_auth', entry_id=entry_id))
        return render_template_string(WEB_VIEW_TEMPLATE, data=data, entry=entry)
    except Exception as e:
        return f"查看失败: {e}",500

@flask_app.route('/second_auth/<entry_id>', methods=['GET','POST'])
def web_second_auth(entry_id):
    entry=web_storage.get_entry_by_id(entry_id)
    if not entry: return "文件不存在",404
    allowed_methods = entry.get('second_auth_methods', [])
    questions = web_auth.get_questions() if web_auth else []
    if request.method=='POST':
        method=request.form.get('method','password')
        inp=request.form.get('input','')
        ok=False
        if method=='password':
            ok=web_auth.verify_password(inp) if web_auth else False
        elif method=='question':
            q=request.form.get('question','')
            ok=web_auth.verify_question(q,inp) if web_auth else False
        elif method=='totp':
            ok=web_auth.verify_totp(inp) if web_auth else False
        if ok:
            data=web_storage.get_file_data(entry_id)
            return render_template_string(WEB_VIEW_TEMPLATE, data=data, entry=entry)
        else:
            return render_template_string(WEB_SECOND_AUTH_TEMPLATE, entry=entry, methods=allowed_methods, questions=questions, error="验证失败")
    return render_template_string(WEB_SECOND_AUTH_TEMPLATE, entry=entry, methods=allowed_methods, questions=questions, error=None)

def start_web_server(storage,auth):
    global web_storage,web_auth
    web_storage=storage; web_auth=auth
    try:
        flask_app.run(host='0.0.0.0', port=WEB_PORT, debug=False, use_reloader=False)
    except Exception as e:
        print(f"Web server error: {e}")

WEB_TEMPLATE="""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>SecureVault 移动端</title>
<style>body{font-family:Arial;background:#1e1e1e;color:#eee;padding:10px}h1{font-size:20px}.file-item{background:#2b2b2b;padding:10px;margin:5px 0;border-radius:5px;border-left:3px solid #5a8cbf}a{color:#5a8cbf;text-decoration:none}</style>
</head><body><h1>📁 SecureVault</h1><p style="color:#888;">版本 {{ VERSION }}</p>
{% for e in entries %}
<div class="file-item"><strong>{{ e.original_name }}</strong>{% if e.is_advanced %}<span style="color:#ff6b6b;">[高级]</span>{% endif %}<br><small>标签: {{ e.tags|join(', ') }}</small><br><a href="/view/{{ e.id }}">查看</a></div>
{% else %}<p>暂无文件</p>{% endfor %}
</body></html>"""

WEB_LOGIN_TEMPLATE="""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>登录 - SecureVault</title>
<style>body{background:#1e1e1e;color:#eee;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}form{background:#2b2b2b;padding:30px;border-radius:10px;width:300px}input,select,button{width:100%;padding:8px;margin:5px 0;background:#3c3c3c;border:1px solid #555;color:#eee;border-radius:3px}button{background:#5a8cbf;cursor:pointer}.error{color:#ff6b6b}</style>
<script>
function toggleQuestion() {
    var method = document.getElementById('method').value;
    var qDiv = document.getElementById('question_div');
    if (method === 'question') { qDiv.style.display = 'block'; } else { qDiv.style.display = 'none'; }
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
<input type="text" name="input" placeholder="输入验证信息">
<button type="submit">登录</button>
</form>
</body></html>"""

WEB_SECOND_AUTH_TEMPLATE="""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>二次验证 - SecureVault</title>
<style>body{background:#1e1e1e;color:#eee;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}form{background:#2b2b2b;padding:30px;border-radius:10px;width:300px}input,select,button{width:100%;padding:8px;margin:5px 0;background:#3c3c3c;border:1px solid #555;color:#eee;border-radius:3px}button{background:#5a8cbf;cursor:pointer}.error{color:#ff6b6b}</style>
<script>
function toggleQuestion() {
    var method = document.getElementById('method').value;
    var qDiv = document.getElementById('question_div');
    if (method === 'question') { qDiv.style.display = 'block'; } else { qDiv.style.display = 'none'; }
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
<input type="text" name="input" placeholder="输入验证信息">
<button type="submit">验证</button>
</form>
</body></html>"""

WEB_VIEW_TEMPLATE="""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>预览 - SecureVault</title>
<style>body{background:#1e1e1e;color:#eee;padding:10px}pre{background:#2b2b2b;padding:10px;border-radius:5px;white-space:pre-wrap;word-wrap:break-word}img{max-width:100%;border-radius:5px}</style>
</head><body><h2>{{ entry.original_name }}</h2><p><a href="/">返回列表</a></p>
{% set ext = entry.ext|lower %}
{% if entry.type == 'text' %}<pre>{{ data.decode('utf-8', errors='replace') }}</pre>
{% elif entry.type == 'image' %}<img src="data:image/{{ ext[1:] }};base64,{{ data|b64encode }}" />
{% else %}<p>此文件类型不支持在线预览，请下载后查看。</p><a href="/download/{{ entry.id }}">下载</a>{% endif %}
</body></html>"""

# ---------- FileViewer ----------
class FileViewer(QDialog):
    def __init__(self,parent,data,ftype,original_name):
        super().__init__(parent)
        self.setWindowTitle(f"查看: {original_name}")
        self.setModal(True); self.resize(700,500)
        layout=QVBoxLayout()
        self.tmp_path=None; self.player=None; self.file_data=data
        if ftype=='text':
            te=QTextEdit(); te.setPlainText(data.decode('utf-8',errors='replace')); te.setReadOnly(True); layout.addWidget(te)
        elif ftype=='image':
            pixmap=QPixmap()
            if pixmap.loadFromData(data):
                label=QLabel(); label.setPixmap(pixmap.scaled(600,400,Qt.KeepAspectRatio,Qt.SmoothTransformation)); layout.addWidget(label)
            else:
                try:
                    img=Image.open(BytesIO(data)); qimg=ImageQt.ImageQt(img); pixmap=QPixmap.fromImage(qimg)
                    label=QLabel(); label.setPixmap(pixmap.scaled(600,400,Qt.KeepAspectRatio,Qt.SmoothTransformation)); layout.addWidget(label)
                except: layout.addWidget(QLabel("无法显示该图片"))
        elif ftype in ['video','audio']:
            try:
                ext=os.path.splitext(original_name)[1]
                fd,path=tempfile.mkstemp(suffix=ext); os.close(fd)
                with open(path,'wb') as f: f.write(data)
                self.tmp_path=path; abs_path=os.path.abspath(path)
                self.player=QMediaPlayer()
                if ftype=='video':
                    self.video_widget=QVideoWidget(); layout.addWidget(self.video_widget); self.player.setVideoOutput(self.video_widget)
                self.player.setMedia(QMediaContent(QUrl.fromLocalFile(abs_path)))
                self.load_ok=False
                self.player.mediaStatusChanged.connect(self.check_media_status)
                QTimer.singleShot(5000,self.check_load_timeout)
                cl=QHBoxLayout()
                pb=QPushButton("播放/暂停"); pb.clicked.connect(self.toggle_play); cl.addWidget(pb)
                sb=QPushButton("停止"); sb.clicked.connect(self.player.stop); cl.addWidget(sb)
                if ftype=='audio':
                    self.position_label=QLabel("00:00 / 00:00"); cl.addWidget(self.position_label)
                    self.timer=QTimer(self); self.timer.timeout.connect(self.update_position); self.timer.start(1000)
                eb=QPushButton("导出并观看"); eb.clicked.connect(self.export_and_view); cl.addWidget(eb)
                layout.addLayout(cl)
                self.status_label=QLabel("正在加载媒体..."); layout.addWidget(self.status_label)
                self.player.play(); self.finished.connect(self.cleanup_tmp)
            except Exception as e:
                layout.addWidget(QLabel(f"播放器初始化失败: {e}"))
                btn=QPushButton("导出并观看"); btn.clicked.connect(self.export_and_view); layout.addWidget(btn)
        elif ftype=='document':
            ext=os.path.splitext(original_name)[1].lower(); text_content=""
            try:
                if ext in ['.docx']:
                    doc=docx.Document(BytesIO(data))
                    for para in doc.paragraphs: text_content+=para.text+"\n"
                elif ext in ['.pdf']:
                    pdf_reader=PyPDF2.PdfReader(BytesIO(data))
                    for page in pdf_reader.pages: text_content+=page.extract_text()+"\n"
                else: text_content="此文档格式暂不支持预览"
            except Exception as e: text_content=f"文档解析失败: {e}"
            te=QTextEdit(); te.setPlainText(text_content); te.setReadOnly(True); layout.addWidget(te)
        else: layout.addWidget(QLabel("不支持预览此文件类型"))
        self.setLayout(layout)
    def check_media_status(self,status):
        if status in (QMediaPlayer.LoadedMedia,QMediaPlayer.BufferedMedia):
            self.load_ok=True
            if hasattr(self,'status_label'): self.status_label.setText("媒体已加载，正在播放...")
        elif status==QMediaPlayer.InvalidMedia:
            if hasattr(self,'status_label'): self.status_label.setText("❌ 媒体格式不支持，请导出观看")
            self.load_ok=False
        elif status==QMediaPlayer.NoMedia:
            if hasattr(self,'status_label'): self.status_label.setText("无媒体")
            self.load_ok=False
    def check_load_timeout(self):
        if not hasattr(self,'load_ok') or not self.load_ok:
            if hasattr(self,'status_label'): self.status_label.setText("⚠️ 加载超时，请尝试导出观看")
    def toggle_play(self):
        if self.player and self.player.state()==QMediaPlayer.PlayingState: self.player.pause()
        else: self.player.play()
    def update_position(self):
        if hasattr(self,'player') and self.player:
            if self.player.state()!=QMediaPlayer.StoppedState:
                pos=self.player.position(); dur=self.player.duration()
                if dur>0:
                    self.position_label.setText(f"{pos//60000:02d}:{(pos%60000)//1000:02d} / {dur//60000:02d}:{(dur%60000)//1000:02d}")
    def export_and_view(self):
        if hasattr(self,'file_data') and self.file_data:
            ext=os.path.splitext(self.windowTitle().replace("查看: ",""))[1] if hasattr(self,'windowTitle') else '.bin'
            with tempfile.NamedTemporaryFile(delete=False,suffix=ext) as tmp:
                tmp.write(self.file_data); export_path=tmp.name
            os.startfile(export_path)
            QMessageBox.information(self,"提示",f"文件已导出到：{export_path}")
        else: QMessageBox.warning(self,"错误","没有可导出的数据")
    def cleanup_tmp(self):
        if hasattr(self,'tmp_path') and self.tmp_path and os.path.exists(self.tmp_path):
            try: os.unlink(self.tmp_path)
            except: pass

# ---------- AuthDialog ----------
class AuthDialog(QDialog):
    def __init__(self,parent,auth_manager,allowed_methods,entry_id):
        super().__init__(parent)
        self.auth=auth_manager; self.allowed_methods=allowed_methods; self.entry_id=entry_id
        self.setWindowTitle("二次验证"); self.setModal(True); self.resize(400,300)
        layout=QVBoxLayout()
        layout.addWidget(QLabel("请通过以下任意一种方式验证："))
        self.stack=QStackedWidget(); self.widgets={}
        for m in allowed_methods:
            if m=='password':
                w=self.create_password_widget(); self.stack.addWidget(w); self.widgets['password']=w
            elif m=='question':
                w=self.create_question_widget(); self.stack.addWidget(w); self.widgets['question']=w
            elif m=='totp':
                w=self.create_totp_widget(); self.stack.addWidget(w); self.widgets['totp']=w
            elif m=='email':
                w=self.create_email_widget(); self.stack.addWidget(w); self.widgets['email']=w
        layout.addWidget(self.stack)
        self.method_combo=QComboBox()
        self.method_combo.addItems(self.widgets.keys())
        self.method_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        layout.addWidget(self.method_combo)
        self.btn_box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.btn_box.accepted.connect(self.accept); self.btn_box.rejected.connect(self.reject)
        layout.addWidget(self.btn_box); self.setLayout(layout)
    def create_password_widget(self):
        w=QWidget(); l=QVBoxLayout()
        l.addWidget(QLabel("输入密码：")); self.pw_input=QLineEdit(); self.pw_input.setEchoMode(QLineEdit.Password)
        l.addWidget(self.pw_input); w.setLayout(l); return w
    def create_question_widget(self):
        w=QWidget(); l=QVBoxLayout()
        l.addWidget(QLabel("选择安全问题：")); self.question_combo=QComboBox(); self.question_combo.addItems(self.auth.get_questions()); l.addWidget(self.question_combo)
        l.addWidget(QLabel("输入答案：")); self.answer_input=QLineEdit(); self.answer_input.setEchoMode(QLineEdit.Password)
        l.addWidget(self.answer_input); w.setLayout(l); return w
    def create_totp_widget(self):
        w=QWidget(); l=QVBoxLayout()
        l.addWidget(QLabel("输入 Authenticator 动态码：")); self.totp_input=QLineEdit(); l.addWidget(self.totp_input); w.setLayout(l); return w
    def create_email_widget(self):
        w=QWidget(); l=QVBoxLayout()
        l.addWidget(QLabel("输入邮箱验证码：")); self.email_code_input=QLineEdit(); l.addWidget(self.email_code_input)
        self.send_btn=QPushButton("发送验证码"); self.send_btn.clicked.connect(self.send_email_code); l.addWidget(self.send_btn)
        self.email_code=None; w.setLayout(l); return w
    def send_email_code(self):
        self.email_code=self.auth.send_verification_code()
        if self.email_code: QMessageBox.information(self,"提示","验证码已发送至您的邮箱")
        else: QMessageBox.warning(self,"错误","邮件发送失败，请检查配置")
    def accept(self):
        method=self.method_combo.currentText()
        ok=False
        if method=='password': ok=self.auth.verify_password(self.pw_input.text())
        elif method=='question': ok=self.auth.verify_question(self.question_combo.currentText(),self.answer_input.text())
        elif method=='totp': ok=self.auth.verify_totp(self.totp_input.text())
        elif method=='email': ok=(self.email_code_input.text()==self.email_code)
        if ok:
            self.auth.reset_fail_count(); super().accept()
        else:
            count=self.auth.increment_fail_count()
            QMessageBox.warning(self,"验证失败",f"失败 {count} 次")
            if count>=5:
                self.trigger_emergency_backup(); super().reject()
    def trigger_emergency_backup(self):
        from PyQt5.QtWidgets import QApplication
        main_window=None
        for w in QApplication.topLevelWidgets():
            if w.__class__.__name__=='MainWindow': main_window=w; break
        if not main_window: QMessageBox.critical(self,"错误","无法找到主窗口"); return
        storage=main_window.storage; auth=main_window.auth
        smtp_config=auth.email_config
        if not smtp_config: QMessageBox.critical(self,"错误","未配置邮箱"); return
        to_email=smtp_config.get('receiver_email')
        if not to_email: QMessageBox.critical(self,"错误","未设置收件邮箱"); return
        entry=storage.get_entry_by_id(self.entry_id)
        if not entry: QMessageBox.critical(self,"错误","未找到该文件记录"); return
        vault_path=entry['secret_path']
        if not os.path.exists(vault_path) and entry['user_path'] and os.path.exists(entry['user_path']): vault_path=entry['user_path']
        if not os.path.exists(vault_path): QMessageBox.critical(self,"错误","加密文件不存在"); return
        display_name=entry['original_name']+'.vault'
        try: BackupManager.send_vault_file(vault_path,to_email,smtp_config,display_name)
        except Exception as e: QMessageBox.critical(self,"错误",f"邮件发送失败: {e}"); return
        storage.remove_entry(self.entry_id,destroy=True)
        auth.reset_fail_count()
        QMessageBox.critical(self,"紧急备份",f"加密文件已发送至您的邮箱，原始文件已被销毁。程序将退出。")
        QApplication.quit()

# ---------- DeleteAuthDialog ----------
class DeleteAuthDialog(QDialog):
    def __init__(self,parent,auth_manager,allowed_methods):
        super().__init__(parent)
        self.auth=auth_manager; self.allowed_methods=allowed_methods
        self.setWindowTitle("身份验证"); self.setModal(True); self.resize(400,300)
        layout=QVBoxLayout()
        layout.addWidget(QLabel("请验证身份以继续操作："))
        self.stack=QStackedWidget(); self.widgets={}
        for m in allowed_methods:
            if m=='password':
                w=self.create_password_widget(); self.stack.addWidget(w); self.widgets['password']=w
            elif m=='question':
                w=self.create_question_widget(); self.stack.addWidget(w); self.widgets['question']=w
            elif m=='totp':
                w=self.create_totp_widget(); self.stack.addWidget(w); self.widgets['totp']=w
            elif m=='email':
                w=self.create_email_widget(); self.stack.addWidget(w); self.widgets['email']=w
        layout.addWidget(self.stack)
        self.method_combo=QComboBox()
        self.method_combo.addItems(self.widgets.keys())
        self.method_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        layout.addWidget(self.method_combo)
        self.btn_box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.btn_box.accepted.connect(self.accept); self.btn_box.rejected.connect(self.reject)
        layout.addWidget(self.btn_box); self.setLayout(layout)
    def create_password_widget(self):
        w=QWidget(); l=QVBoxLayout()
        l.addWidget(QLabel("输入密码：")); self.pw_input=QLineEdit(); self.pw_input.setEchoMode(QLineEdit.Password)
        l.addWidget(self.pw_input); w.setLayout(l); return w
    def create_question_widget(self):
        w=QWidget(); l=QVBoxLayout()
        l.addWidget(QLabel("选择安全问题：")); self.question_combo=QComboBox(); self.question_combo.addItems(self.auth.get_questions()); l.addWidget(self.question_combo)
        l.addWidget(QLabel("输入答案：")); self.answer_input=QLineEdit(); self.answer_input.setEchoMode(QLineEdit.Password)
        l.addWidget(self.answer_input); w.setLayout(l); return w
    def create_totp_widget(self):
        w=QWidget(); l=QVBoxLayout()
        l.addWidget(QLabel("输入 Authenticator 动态码：")); self.totp_input=QLineEdit(); l.addWidget(self.totp_input); w.setLayout(l); return w
    def create_email_widget(self):
        w=QWidget(); l=QVBoxLayout()
        l.addWidget(QLabel("输入邮箱验证码：")); self.email_code_input=QLineEdit(); l.addWidget(self.email_code_input)
        self.send_btn=QPushButton("发送验证码"); self.send_btn.clicked.connect(self.send_email_code); l.addWidget(self.send_btn)
        self.email_code=None; w.setLayout(l); return w
    def send_email_code(self):
        self.email_code=self.auth.send_verification_code()
        if self.email_code: QMessageBox.information(self,"提示","验证码已发送至您的邮箱")
        else: QMessageBox.warning(self,"错误","邮件发送失败，请检查配置")
    def accept(self):
        method=self.method_combo.currentText()
        ok=False
        if method=='password': ok=self.auth.verify_password(self.pw_input.text())
        elif method=='question': ok=self.auth.verify_question(self.question_combo.currentText(),self.answer_input.text())
        elif method=='totp': ok=self.auth.verify_totp(self.totp_input.text())
        elif method=='email': ok=(self.email_code_input.text()==self.email_code)
        if ok: super().accept()
        else: QMessageBox.warning(self,"验证失败","身份验证未通过，请重试或取消")

# ---------- UploadDialog ----------
class UploadDialog(QDialog):
    def __init__(self,parent,file_path):
        super().__init__(parent)
        self.file_path=file_path; self.user_dest=None; self.is_advanced=False; self.second_methods=[]
        self.setWindowTitle("上传加密选项"); self.setModal(True); self.resize(400,300)
        layout=QVBoxLayout()
        layout.addWidget(QLabel(f"文件：{os.path.basename(file_path)}"))
        self.dest_btn=QPushButton("选择用户存储位置（可选）"); self.dest_btn.clicked.connect(self.select_dest)
        self.dest_label=QLabel("未选择")
        layout.addWidget(self.dest_btn); layout.addWidget(self.dest_label)
        self.advanced_cb=QCheckBox("标记为高级文件（需二次验证）")
        self.advanced_cb.toggled.connect(self.toggle_advanced)
        layout.addWidget(self.advanced_cb)
        self.method_group=QGroupBox("二次验证方式（高级文件时可用）")
        self.method_group.setEnabled(False)
        ml=QVBoxLayout()
        self.totp_cb=QCheckBox("TOTP (Authenticator)")
        self.email_cb=QCheckBox("邮箱验证码")
        self.question_cb=QCheckBox("安全问题")
        self.password_cb=QCheckBox("密码")
        ml.addWidget(self.totp_cb); ml.addWidget(self.email_cb); ml.addWidget(self.question_cb); ml.addWidget(self.password_cb)
        self.method_group.setLayout(ml)
        layout.addWidget(self.method_group)
        btn_box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept); btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box); self.setLayout(layout)
    def select_dest(self):
        d=QFileDialog.getExistingDirectory(self,"选择存储文件夹")
        if d: self.user_dest=d; self.dest_label.setText(d)
    def toggle_advanced(self,checked): self.method_group.setEnabled(checked)
    def accept(self):
        self.is_advanced=self.advanced_cb.isChecked()
        if self.is_advanced:
            self.second_methods=[]
            if self.totp_cb.isChecked(): self.second_methods.append('totp')
            if self.email_cb.isChecked(): self.second_methods.append('email')
            if self.question_cb.isChecked(): self.second_methods.append('question')
            if self.password_cb.isChecked(): self.second_methods.append('password')
            if not self.second_methods:
                QMessageBox.warning(self,"提示","高级文件至少选择一种二次验证方式")
                return
        super().accept()

# ---------- SetupWizard ----------
class SetupWizard(QWizard):
    def __init__(self,auth_manager):
        super().__init__()
        self.auth=auth_manager
        self.setWindowTitle("SecureVault 首次设置")
        self.setWizardStyle(QWizard.ModernStyle)
        p1=QWizardPage(); p1.setTitle("欢迎"); p1.setSubTitle("配置安全设置以保护您的文件")
        l=QVBoxLayout(); l.addWidget(QLabel("请依次设置以下安全选项，至少需要配置一种验证方式。")); p1.setLayout(l); self.addPage(p1)
        p2=QWizardPage(); p2.setTitle("密码验证"); p2.setSubTitle("（可选）设置登录密码")
        l=QVBoxLayout()
        self.pw_enable=QCheckBox("启用密码验证"); l.addWidget(self.pw_enable)
        self.pw_input=QLineEdit(); self.pw_input.setEchoMode(QLineEdit.Password); self.pw_input.setPlaceholderText("输入密码（至少8位）"); l.addWidget(self.pw_input)
        self.pw_confirm=QLineEdit(); self.pw_confirm.setEchoMode(QLineEdit.Password); self.pw_confirm.setPlaceholderText("确认密码"); l.addWidget(self.pw_confirm)
        p2.setLayout(l); self.addPage(p2)
        p3=QWizardPage(); p3.setTitle("安全问题"); p3.setSubTitle("设置三个安全问题和答案")
        l=QVBoxLayout()
        self.q1=QLineEdit(); self.q1.setPlaceholderText("问题1")
        self.a1=QLineEdit(); self.a1.setEchoMode(QLineEdit.Password); self.a1.setPlaceholderText("答案1")
        self.q2=QLineEdit(); self.q2.setPlaceholderText("问题2")
        self.a2=QLineEdit(); self.a2.setEchoMode(QLineEdit.Password); self.a2.setPlaceholderText("答案2")
        self.q3=QLineEdit(); self.q3.setPlaceholderText("问题3")
        self.a3=QLineEdit(); self.a3.setEchoMode(QLineEdit.Password); self.a3.setPlaceholderText("答案3")
        l.addWidget(QLabel("问题1")); l.addWidget(self.q1); l.addWidget(self.a1)
        l.addWidget(QLabel("问题2")); l.addWidget(self.q2); l.addWidget(self.a2)
        l.addWidget(QLabel("问题3")); l.addWidget(self.q3); l.addWidget(self.a3)
        p3.setLayout(l); self.addPage(p3)
        p4=QWizardPage(); p4.setTitle("TOTP 验证"); p4.setSubTitle("使用 Microsoft Authenticator 等应用扫描二维码")
        l=QVBoxLayout()
        self.totp_enable=QCheckBox("启用 TOTP"); l.addWidget(self.totp_enable)
        self.qr_label=QLabel(); self.qr_label.setAlignment(Qt.AlignCenter); l.addWidget(self.qr_label)
        self.totp_code=QLineEdit(); self.totp_code.setPlaceholderText("输入当前动态码以验证"); l.addWidget(self.totp_code)
        self.totp_secret_label=QLabel(); l.addWidget(self.totp_secret_label)
        p4.setLayout(l); self.totp_secret=None; self.totp_setup_done=False; self.addPage(p4)
        p5=QWizardPage(); p5.setTitle("邮箱验证"); p5.setSubTitle("配置SMTP发送验证码")
        l=QVBoxLayout()
        self.email_enable=QCheckBox("启用邮箱验证"); l.addWidget(self.email_enable)
        self.smtp_server=QLineEdit(); self.smtp_server.setPlaceholderText("SMTP服务器 (如 smtp.qq.com)"); l.addWidget(self.smtp_server)
        self.smtp_port=QLineEdit(); self.smtp_port.setPlaceholderText("端口 (如 587)"); l.addWidget(self.smtp_port)
        self.sender_email=QLineEdit(); self.sender_email.setPlaceholderText("发件邮箱"); l.addWidget(self.sender_email)
        self.sender_password=QLineEdit(); self.sender_password.setEchoMode(QLineEdit.Password); self.sender_password.setPlaceholderText("授权码或密码"); l.addWidget(self.sender_password)
        self.receiver_email=QLineEdit(); self.receiver_email.setPlaceholderText("收件邮箱（用于接收验证码）"); l.addWidget(self.receiver_email)
        p5.setLayout(l); self.addPage(p5)
        p6=QWizardPage(); p6.setTitle("完成"); p6.setSubTitle("设置已保存，点击完成启动程序")
        l=QVBoxLayout(); l.addWidget(QLabel("所有设置将加密存储，请牢记您的安全信息。")); p6.setLayout(l); self.addPage(p6)
    def initializePage(self,id):
        if id==3:
            if not self.totp_setup_done:
                self.totp_secret=self.auth.setup_totp()
                qr_data=self.auth.setup_totp()
                pixmap=QPixmap(); pixmap.loadFromData(qr_data)
                self.qr_label.setPixmap(pixmap.scaled(200,200,Qt.KeepAspectRatio))
                self.totp_secret_label.setText(f"密钥：{self.auth.totp_secret}")
                self.totp_setup_done=True
    def accept(self):
        if self.pw_enable.isChecked():
            pw=self.pw_input.text()
            if len(pw)<8: QMessageBox.warning(self,"错误","密码长度至少8位"); return
            if pw!=self.pw_confirm.text(): QMessageBox.warning(self,"错误","两次密码输入不一致"); return
            self.auth.set_password(pw)
        qa_list=[]
        for q,a in [(self.q1.text(),self.a1.text()),(self.q2.text(),self.a2.text()),(self.q3.text(),self.a3.text())]:
            if not q or not a: QMessageBox.warning(self,"错误","请完整填写所有安全问题和答案"); return
            qa_list.append((q,a))
        self.auth.set_questions(qa_list)
        if self.totp_enable.isChecked():
            code=self.totp_code.text()
            if not self.auth.verify_totp(code): QMessageBox.warning(self,"错误","TOTP验证码不正确，请重新输入"); return
        else: self.auth.settings_dict.pop('totp_secret',None)
        if self.email_enable.isChecked():
            server=self.smtp_server.text(); port=int(self.smtp_port.text())
            sender=self.sender_email.text(); pw=self.sender_password.text(); receiver=self.receiver_email.text()
            if not all([server,port,sender,pw,receiver]): QMessageBox.warning(self,"错误","请完整填写邮箱配置"); return
            self.auth.set_email_config(server,port,sender,pw,receiver)
            code=self.auth.send_verification_code(receiver)
            if not code: QMessageBox.warning(self,"错误","邮箱配置测试失败，请检查设置"); return
            verify_code,ok=QInputDialog.getText(self,"验证邮箱",f"输入发送到 {receiver} 的验证码")
            if not ok or verify_code!=code: QMessageBox.warning(self,"错误","验证码错误"); return
        else: self.auth.email_config={}
        self.auth.settings_dict['initialized']=True
        self.auth._save()
        super().accept()

# ---------- LoginDialog ----------
class LoginDialog(QDialog):
    def __init__(self,auth_manager):
        super().__init__()
        self.auth=auth_manager; self.recovery_accepted=False
        self.setWindowTitle("SecureVault 登录"); self.setModal(True); self.resize(400,350)
        layout=QVBoxLayout()
        layout.addWidget(QLabel("请通过以下任一方式验证身份"))
        self.stack=QStackedWidget(); self.methods=[]
        if self.auth.password_hash:
            w=self.create_password_widget(); self.stack.addWidget(w); self.methods.append('password')
        if self.auth.qa:
            w=self.create_question_widget(); self.stack.addWidget(w); self.methods.append('question')
        if self.auth.totp_secret:
            w=self.create_totp_widget(); self.stack.addWidget(w); self.methods.append('totp')
        if self.auth.email_config:
            w=self.create_email_widget(); self.stack.addWidget(w); self.methods.append('email')
        layout.addWidget(self.stack)
        self.method_combo=QComboBox()
        self.method_combo.addItems(self.methods)
        self.method_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        layout.addWidget(self.method_combo)
        self.btn_box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.btn_box.accepted.connect(self.accept); self.btn_box.rejected.connect(self.reject)
        layout.addWidget(self.btn_box)
        self.recovery_btn=QPushButton("使用紧急恢复代码")
        self.recovery_btn.clicked.connect(self.recovery_login)
        layout.addWidget(self.recovery_btn)
        self.setLayout(layout)
    def recovery_login(self):
        code,ok=QInputDialog.getText(self,"紧急恢复","请输入紧急恢复代码（格式：XXXX-XXXX-XXXX-XXXX-XXXX）:")
        if not ok or not code: return
        if self.auth.verify_recovery_code(code):
            self.recovery_accepted=True; self.accept()
        else: QMessageBox.warning(self,"错误","恢复代码无效或已使用")
    def create_password_widget(self):
        w=QWidget(); l=QVBoxLayout()
        l.addWidget(QLabel("输入密码：")); self.pw_input=QLineEdit(); self.pw_input.setEchoMode(QLineEdit.Password)
        l.addWidget(self.pw_input); w.setLayout(l); return w
    def create_question_widget(self):
        w=QWidget(); l=QVBoxLayout()
        l.addWidget(QLabel("选择安全问题：")); self.question_combo=QComboBox(); self.question_combo.addItems(self.auth.get_questions()); l.addWidget(self.question_combo)
        l.addWidget(QLabel("输入答案：")); self.answer_input=QLineEdit(); self.answer_input.setEchoMode(QLineEdit.Password)
        l.addWidget(self.answer_input); w.setLayout(l); return w
    def create_totp_widget(self):
        w=QWidget(); l=QVBoxLayout()
        l.addWidget(QLabel("输入 Authenticator 动态码：")); self.totp_input=QLineEdit(); l.addWidget(self.totp_input); w.setLayout(l); return w
    def create_email_widget(self):
        w=QWidget(); l=QVBoxLayout()
        l.addWidget(QLabel("输入邮箱验证码：")); self.email_code_input=QLineEdit(); l.addWidget(self.email_code_input)
        self.send_btn=QPushButton("发送验证码"); self.send_btn.clicked.connect(self.send_email_code); l.addWidget(self.send_btn)
        self.email_code=None; w.setLayout(l); return w
    def send_email_code(self):
        self.email_code=self.auth.send_verification_code()
        if self.email_code: QMessageBox.information(self,"提示","验证码已发送")
        else: QMessageBox.warning(self,"错误","发送失败")
    def accept(self):
        if self.recovery_accepted: super().accept(); return
        method=self.method_combo.currentText()
        ok=False
        if method=='password': ok=self.auth.verify_password(self.pw_input.text())
        elif method=='question': ok=self.auth.verify_question(self.question_combo.currentText(),self.answer_input.text())
        elif method=='totp': ok=self.auth.verify_totp(self.totp_input.text())
        elif method=='email': ok=(self.email_code_input.text()==self.email_code)
        if ok:
            self.auth.reset_fail_count(); super().accept()
        else:
            count=self.auth.increment_fail_count()
            QMessageBox.warning(self,"验证失败",f"失败 {count} 次")
            if count>=5:
                self.trigger_emergency_backup(); super().reject()
    def trigger_emergency_backup(self):
        from PyQt5.QtWidgets import QApplication
        main_window=None
        for w in QApplication.topLevelWidgets():
            if w.__class__.__name__=='MainWindow': main_window=w; break
        if not main_window: QMessageBox.critical(self,"错误","无法找到主窗口"); return
        storage=main_window.storage; auth=main_window.auth
        smtp_config=auth.email_config
        if not smtp_config: QMessageBox.critical(self,"错误","未配置邮箱"); return
        to_email=smtp_config.get('receiver_email')
        if not to_email: QMessageBox.critical(self,"错误","未设置收件邮箱"); return
        file_info_list=storage.get_all_vault_paths_with_names()
        if not file_info_list: QMessageBox.critical(self,"错误","没有可备份的文件"); return
        try: BackupManager.send_multiple_vault_files(file_info_list,to_email,smtp_config)
        except Exception as e: QMessageBox.critical(self,"错误",f"邮件发送失败: {e}"); return
        for entry in storage.get_all_entries():
            storage.remove_entry(entry['id'],destroy=True)
        storage.index=[]; storage._save_index()
        auth.reset_fail_count()
        QMessageBox.critical(self,"紧急备份","所有加密文件已发送至您的邮箱，原始文件已被销毁。程序将退出。")
        QApplication.quit()

# ---------- SettingsDialog ----------
class SettingsDialog(QDialog):
    def __init__(self,parent,auth_manager,is_recovery_login=False):
        super().__init__(parent)
        self.auth=auth_manager; self.is_recovery_login=is_recovery_login; self.parent_main=parent
        self.web_thread=None
        self.setWindowTitle("设置"); self.setModal(True); self.resize(600,550)
        layout=QVBoxLayout()
        ver_layout=QHBoxLayout()
        ver_layout.addWidget(QLabel(f"当前版本：{VERSION}"))
        self.update_btn=QPushButton("检查更新")
        self.update_btn.clicked.connect(self.check_update)
        ver_layout.addWidget(self.update_btn); ver_layout.addStretch()
        layout.addLayout(ver_layout)
        info_label=QLabel("当前已启用的验证方式："); layout.addWidget(info_label)
        methods=[]
        if self.auth.password_hash: methods.append("密码")
        if self.auth.qa: methods.append("安全问题")
        if self.auth.totp_secret: methods.append("TOTP")
        if self.auth.email_config: methods.append("邮箱验证码")
        status_text=", ".join(methods) if methods else "无"
        status_label=QLabel(f"已启用：{status_text}"); layout.addWidget(status_label)
        self.btn_change_password=QPushButton("修改密码"); self.btn_change_password.clicked.connect(self.change_password); layout.addWidget(self.btn_change_password)
        self.btn_change_questions=QPushButton("修改安全问题"); self.btn_change_questions.clicked.connect(self.change_questions); layout.addWidget(self.btn_change_questions)
        self.btn_change_totp=QPushButton("修改 TOTP 设置"); self.btn_change_totp.clicked.connect(self.change_totp); layout.addWidget(self.btn_change_totp)
        self.btn_change_email=QPushButton("修改邮箱配置"); self.btn_change_email.clicked.connect(self.change_email); layout.addWidget(self.btn_change_email)
        self.btn_generate_recovery=QPushButton("生成紧急恢复代码"); self.btn_generate_recovery.clicked.connect(self.generate_recovery); layout.addWidget(self.btn_generate_recovery)
        self.recovery_status=QLabel(); self.update_recovery_status(); layout.addWidget(self.recovery_status)
        theme_layout=QHBoxLayout()
        theme_layout.addWidget(QLabel("主题："))
        self.theme_combo=QComboBox(); self.theme_combo.addItems(["明亮","暗黑"])
        current_theme=self.auth.settings_dict.get('theme','明亮')
        self.theme_combo.setCurrentText(current_theme)
        self.theme_combo.currentTextChanged.connect(self.on_theme_changed)
        theme_layout.addWidget(self.theme_combo)
        layout.addLayout(theme_layout)
        migrate_group=QGroupBox("保险库迁移")
        migrate_layout=QVBoxLayout()
        self.btn_export_vault=QPushButton("导出保险库（备份/迁移）"); self.btn_export_vault.clicked.connect(self.export_vault); migrate_layout.addWidget(self.btn_export_vault)
        self.btn_import_vault=QPushButton("导入保险库（恢复）"); self.btn_import_vault.clicked.connect(self.import_vault); migrate_layout.addWidget(self.btn_import_vault)
        migrate_group.setLayout(migrate_layout); layout.addWidget(migrate_group)
        web_group=QGroupBox("移动端网页版")
        web_layout=QVBoxLayout()
        self.btn_web_qr=QPushButton("移动端二维码"); self.btn_web_qr.clicked.connect(self.show_web_qr); web_layout.addWidget(self.btn_web_qr)
        self.web_status=QLabel("状态：未启动"); web_layout.addWidget(self.web_status)
        web_group.setLayout(web_layout); layout.addWidget(web_group)
        bottom_layout=QHBoxLayout()
        bottom_layout.addWidget(QLabel(f"SecureVault v{VERSION}")); bottom_layout.addStretch()
        layout.addLayout(bottom_layout)
        btn_box=QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box); self.setLayout(layout)

    def update_recovery_status(self):
        if self.auth.is_recovery_code_available():
            self.recovery_status.setText("状态：当前有一份有效的紧急恢复代码"); self.recovery_status.setStyleSheet("color: green;")
        else:
            self.recovery_status.setText("状态：当前没有有效的紧急恢复代码"); self.recovery_status.setStyleSheet("color: gray;")
    def _verify_identity(self):
        if self.is_recovery_login: return True
        methods=[]
        if self.auth.password_hash: methods.append('password')
        if self.auth.qa: methods.append('question')
        if self.auth.totp_secret: methods.append('totp')
        if self.auth.email_config: methods.append('email')
        if not methods: QMessageBox.warning(self,"提示","没有可用的验证方式"); return False
        dialog=DeleteAuthDialog(self,self.auth,methods)
        return dialog.exec_()==QDialog.Accepted
    def generate_recovery(self):
        try:
            if not self.is_recovery_login and not self._verify_identity(): return
            code=self.auth.generate_recovery_code()
            dialog=QDialog(self); dialog.setWindowTitle("紧急恢复代码")
            layout=QVBoxLayout()
            layout.addWidget(QLabel("您的紧急恢复代码已生成，请妥善保管："))
            code_label=QLabel(code); code_label.setStyleSheet("font-size:16pt;font-weight:bold;font-family:monospace;"); code_label.setAlignment(Qt.AlignCenter); layout.addWidget(code_label)
            code_edit=QLineEdit(code); code_edit.setReadOnly(True); code_edit.setStyleSheet("font-family:monospace;"); layout.addWidget(code_edit)
            export_btn=QPushButton("导出为 .txt 文件")
            def export_code():
                try:
                    path,_=QFileDialog.getSaveFileName(self,"保存恢复代码","recovery_code.txt","Text Files (*.txt)")
                    if path:
                        with open(path,'w') as f:
                            f.write(f"紧急恢复代码：{code}\n\n生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                        QMessageBox.information(dialog,"导出成功",f"代码已保存到：{path}")
                except Exception as e: QMessageBox.warning(dialog,"导出失败",str(e))
            export_btn.clicked.connect(export_code); layout.addWidget(export_btn)
            btn_box=QDialogButtonBox(QDialogButtonBox.Close); btn_box.rejected.connect(dialog.accept); layout.addWidget(btn_box)
            dialog.setLayout(layout); dialog.exec_()
            self.update_recovery_status()
            QMessageBox.information(self,"提示","新的恢复代码已生成，旧代码已失效，邮件通知已发送。")
        except Exception as e:
            QMessageBox.critical(self,"错误",f"生成恢复代码失败: {e}"); traceback.print_exc()
    def on_theme_changed(self,theme):
        self.auth.settings_dict['theme']=theme; self.auth._save()
        if self.parent_main: self.parent_main.apply_theme(theme)
    def export_vault(self):
        try:
            if not self.is_recovery_login and not self._verify_identity(): return
            path,_=QFileDialog.getSaveFileName(self,"导出保险库","SecureVault_Backup.vaultbk","Vault Backup (*.vaultbk)")
            if not path: return
            password,ok=QInputDialog.getText(self,"设置密码","为备份包设置密码（可选，留空则无密码）：",QLineEdit.Password)
            if not ok: return
            pwd=password if password else None
            storage=self.parent_main.storage
            QApplication.setOverrideCursor(Qt.WaitCursor)
            storage.export_vault(path,pwd)
            QApplication.restoreOverrideCursor()
            QMessageBox.information(self,"成功",f"保险库已导出到：{path}")
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self,"错误",f"导出失败: {e}"); traceback.print_exc()
    def import_vault(self):
        try:
            if not self.is_recovery_login and not self._verify_identity(): return
            path,_=QFileDialog.getOpenFileName(self,"导入保险库","","Vault Backup (*.vaultbk)")
            if not path: return
            password,ok=QInputDialog.getText(self,"输入密码","如果备份包有密码，请输入：",QLineEdit.Password)
            if not ok: return
            pwd=password if password else None
            reply=QMessageBox.question(self,"确认","导入将覆盖当前所有数据和设置，是否继续？",QMessageBox.Yes|QMessageBox.No)
            if reply!=QMessageBox.Yes: return
            storage=self.parent_main.storage
            QApplication.setOverrideCursor(Qt.WaitCursor)
            storage.import_vault(path,pwd)
            QApplication.restoreOverrideCursor()
            self.parent_main.load_files()
            QMessageBox.information(self,"成功","保险库导入成功，请重启程序以使所有设置生效。")
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self,"错误",f"导入失败: {e}"); traceback.print_exc()
    def check_update(self):
        try:
            headers={'User-Agent':'SecureVault'}
            resp=requests.get("https://api.github.com/repos/tiankong-mc/Secure-Encryption-Software/releases/latest", timeout=10, headers=headers, verify=False)
            if resp.status_code!=200:
                QMessageBox.warning(self,"错误","无法获取更新信息"); return
            data=resp.json()
            latest=data.get('tag_name','')
            if latest>VERSION:
                ret=QMessageBox.question(self,"发现新版本",f"最新版本：{latest}\n当前版本：{VERSION}\n是否下载并更新？",QMessageBox.Yes|QMessageBox.No)
                if ret==QMessageBox.Yes: self.download_update(data)
            else: QMessageBox.information(self,"已是最新",f"当前已是最新版本（{VERSION}）")
        except Exception as e:
            QMessageBox.critical(self,"错误",f"检查更新失败: {e}")
    def download_update(self,data):
        try:
            assets=data.get('assets',[]); exe_asset=None
            for a in assets:
                if a.get('name','').lower()=='encryption.exe': exe_asset=a; break
            if not exe_asset: QMessageBox.warning(self,"错误","未找到可执行文件"); return
            url=exe_asset['browser_download_url']
            progress=QProgressDialog("正在下载更新...","取消",0,100,self)
            progress.setWindowModality(Qt.WindowModal); progress.show()
            response=requests.get(url, stream=True, verify=False)
            total_size=int(response.headers.get('content-length',0))
            block_size=8192
            temp_path=os.path.join(os.path.dirname(sys.executable),"SecureVault_update.exe")
            with open(temp_path,'wb') as f:
                downloaded=0
                for chunk in response.iter_content(chunk_size=block_size):
                    if chunk:
                        f.write(chunk); downloaded+=len(chunk)
                        if total_size: progress.setValue(int(downloaded/total_size*100))
                        QApplication.processEvents()
            progress.setValue(100)
            QMessageBox.information(self,"下载完成","准备重启并安装更新")
            bat_path=os.path.join(os.path.dirname(sys.executable),"update.bat")
            with open(bat_path,'w') as f:
                f.write(f"""@echo off
timeout /t 2 > nul
copy /Y "{temp_path}" "{sys.executable}"
del "{temp_path}"
start "" "{sys.executable}"
del "%~f0"
""")
            subprocess.Popen([bat_path], creationflags=subprocess.CREATE_NEW_CONSOLE)
            QApplication.quit()
        except Exception as e: QMessageBox.critical(self,"错误",f"更新失败: {e}")
    def show_web_qr(self):
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(0); s.connect(('8.8.8.8',1)); ip=s.getsockname()[0]; s.close()
        except: ip='127.0.0.1'
        url=f"http://{ip}:{WEB_PORT}"
        if self.web_thread is None or not self.web_thread.is_alive():
            self.web_thread=threading.Thread(target=start_web_server, args=(self.parent_main.storage,self.auth), daemon=True)
            self.web_thread.start()
            self.web_status.setText(f"状态：已启动（{url}）")
            QTimer.singleShot(2000, lambda: self.web_status.setText(f"状态：运行中（{url}）"))
        qr=qrcode.make(url)
        qr_bytes=BytesIO(); qr.save(qr_bytes, format='PNG')
        pixmap=QPixmap(); pixmap.loadFromData(qr_bytes.getvalue())
        dialog=QDialog(self); dialog.setWindowTitle("移动端二维码")
        layout=QVBoxLayout()
        layout.addWidget(QLabel(f"请使用手机扫描二维码访问：\n{url}"))
        label=QLabel(); label.setPixmap(pixmap.scaled(300,300,Qt.KeepAspectRatio)); layout.addWidget(label)
        btn_box=QDialogButtonBox(QDialogButtonBox.Close); btn_box.rejected.connect(dialog.accept); layout.addWidget(btn_box)
        dialog.setLayout(layout); dialog.exec_()

    def change_password(self):
        if not self._verify_identity(): return
        pw,ok=QInputDialog.getText(self,"修改密码","输入新密码（至少8位）：",QLineEdit.Password)
        if not ok: return
        if len(pw)<8: QMessageBox.warning(self,"错误","密码长度至少8位"); return
        confirm,ok=QInputDialog.getText(self,"修改密码","再次输入新密码：",QLineEdit.Password)
        if not ok: return
        if pw!=confirm: QMessageBox.warning(self,"错误","两次密码不一致"); return
        self.auth.set_password(pw); QMessageBox.information(self,"成功","密码已更新")
    def change_questions(self):
        if not self._verify_identity(): return
        dialog=QDialog(self); dialog.setWindowTitle("修改安全问题")
        layout=QVBoxLayout()
        q1=QLineEdit(); q1.setPlaceholderText("问题1")
        a1=QLineEdit(); a1.setEchoMode(QLineEdit.Password); a1.setPlaceholderText("答案1")
        q2=QLineEdit(); q2.setPlaceholderText("问题2")
        a2=QLineEdit(); a2.setEchoMode(QLineEdit.Password); a2.setPlaceholderText("答案2")
        q3=QLineEdit(); q3.setPlaceholderText("问题3")
        a3=QLineEdit(); a3.setEchoMode(QLineEdit.Password); a3.setPlaceholderText("答案3")
        layout.addWidget(QLabel("问题1")); layout.addWidget(q1); layout.addWidget(a1)
        layout.addWidget(QLabel("问题2")); layout.addWidget(q2); layout.addWidget(a2)
        layout.addWidget(QLabel("问题3")); layout.addWidget(q3); layout.addWidget(a3)
        btn_box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dialog.accept); btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box); dialog.setLayout(layout)
        if dialog.exec_()!=QDialog.Accepted: return
        if not q1.text() or not a1.text() or not q2.text() or not a2.text() or not q3.text() or not a3.text():
            QMessageBox.warning(self,"错误","请完整填写所有问题和答案"); return
        qa_list=[(q1.text(),a1.text()),(q2.text(),a2.text()),(q3.text(),a3.text())]
        self.auth.set_questions(qa_list); QMessageBox.information(self,"成功","安全问题已更新")
    def change_totp(self):
        if not self._verify_identity(): return
        reply=QMessageBox.question(self,"确认","重新生成 TOTP 密钥将导致之前的二维码失效，是否继续？",QMessageBox.Yes|QMessageBox.No)
        if reply!=QMessageBox.Yes: return
        qr_data=self.auth.setup_totp()
        pixmap=QPixmap(); pixmap.loadFromData(qr_data)
        dialog=QDialog(self); dialog.setWindowTitle("TOTP 设置")
        layout=QVBoxLayout()
        layout.addWidget(QLabel("请使用 Authenticator 扫描以下二维码："))
        img_label=QLabel(); img_label.setPixmap(pixmap.scaled(200,200,Qt.KeepAspectRatio)); layout.addWidget(img_label)
        secret_label=QLabel(f"密钥：{self.auth.totp_secret}"); layout.addWidget(secret_label)
        code_input=QLineEdit(); code_input.setPlaceholderText("输入动态码验证"); layout.addWidget(code_input)
        btn_box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dialog.accept); btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box); dialog.setLayout(layout)
        if dialog.exec_()==QDialog.Accepted:
            if not self.auth.verify_totp(code_input.text()):
                QMessageBox.warning(self,"错误","验证码不正确"); return
            QMessageBox.information(self,"成功","TOTP 已更新")
    def change_email(self):
        if not self._verify_identity(): return
        dialog=QDialog(self); dialog.setWindowTitle("修改邮箱配置")
        layout=QVBoxLayout()
        smtp_server=QLineEdit(); smtp_server.setPlaceholderText("SMTP服务器"); smtp_server.setText(self.auth.email_config.get('smtp_server',''))
        smtp_port=QLineEdit(); smtp_port.setPlaceholderText("端口"); smtp_port.setText(str(self.auth.email_config.get('port','')))
        sender_email=QLineEdit(); sender_email.setPlaceholderText("发件邮箱"); sender_email.setText(self.auth.email_config.get('sender_email',''))
        sender_password=QLineEdit(); sender_password.setEchoMode(QLineEdit.Password); sender_password.setPlaceholderText("授权码"); sender_password.setText(self.auth.email_config.get('password',''))
        receiver_email=QLineEdit(); receiver_email.setPlaceholderText("收件邮箱"); receiver_email.setText(self.auth.email_config.get('receiver_email',''))
        layout.addWidget(QLabel("SMTP服务器")); layout.addWidget(smtp_server)
        layout.addWidget(QLabel("端口")); layout.addWidget(smtp_port)
        layout.addWidget(QLabel("发件邮箱")); layout.addWidget(sender_email)
        layout.addWidget(QLabel("授权码/密码")); layout.addWidget(sender_password)
        layout.addWidget(QLabel("收件邮箱")); layout.addWidget(receiver_email)
        btn_box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dialog.accept); btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box); dialog.setLayout(layout)
        if dialog.exec_()!=QDialog.Accepted: return
        if not all([smtp_server.text(), smtp_port.text(), sender_email.text(), sender_password.text(), receiver_email.text()]):
            QMessageBox.warning(self,"错误","请完整填写所有字段"); return
        try: port=int(smtp_port.text())
        except: QMessageBox.warning(self,"错误","端口必须为数字"); return
        self.auth.set_email_config(smtp_server.text(), port, sender_email.text(), sender_password.text(), receiver_email.text())
        code=self.auth.send_verification_code(receiver_email.text())
        if not code: QMessageBox.warning(self,"错误","邮箱配置测试失败"); return
        verify_code,ok=QInputDialog.getText(self,"验证邮箱",f"输入发送到 {receiver_email.text()} 的验证码")
        if not ok or verify_code!=code: QMessageBox.warning(self,"错误","验证码错误"); return
        QMessageBox.information(self,"成功","邮箱配置已更新")

# ---------- MainWindow ----------
class MainWindow(QMainWindow):
    def __init__(self, storage, auth, is_recovery_login=False):
        super().__init__()
        self.storage=storage; self.auth=auth; self.is_recovery_login=is_recovery_login
        self.current_tag=None
        self.setWindowTitle(f"SecureVault {VERSION}")
        self.setGeometry(100,100,900,600)
        self.initUI()
        self.load_files()
        theme=self.auth.settings_dict.get('theme','明亮')
        self.apply_theme(theme)
        self.setAcceptDrops(True)
    def initUI(self):
        central=QWidget(); self.setCentralWidget(central)
        main_layout=QHBoxLayout()
        left_panel=QWidget(); left_panel.setFixedWidth(200)
        left_layout=QVBoxLayout()
        left_layout.addWidget(QLabel("标签分类"))
        self.tag_list=QListWidget()
        self.tag_list.addItem("全部")
        self.tag_list.itemClicked.connect(self.on_tag_clicked)
        left_layout.addWidget(self.tag_list)
        tag_btn_layout=QHBoxLayout()
        add_tag_btn=QPushButton("+"); add_tag_btn.setToolTip("创建新标签"); add_tag_btn.clicked.connect(self.create_tag)
        tag_btn_layout.addWidget(add_tag_btn)
        del_tag_btn=QPushButton("-"); del_tag_btn.setToolTip("删除选中标签"); del_tag_btn.clicked.connect(self.delete_tag)
        tag_btn_layout.addWidget(del_tag_btn)
        left_layout.addLayout(tag_btn_layout)
        left_panel.setLayout(left_layout)
        main_layout.addWidget(left_panel)
        right_panel=QWidget()
        right_layout=QVBoxLayout()
        top_bar=QHBoxLayout()
        self.upload_btn=QPushButton("上传加密")
        self.import_btn=QPushButton("导入加密文件")
        self.export_btn=QPushButton("导出解密文件")
        self.refresh_btn=QPushButton("刷新")
        self.settings_btn=QPushButton("设置")
        self.delete_btn=QPushButton("删除")
        top_bar.addWidget(self.upload_btn); top_bar.addWidget(self.import_btn)
        top_bar.addWidget(self.export_btn); top_bar.addWidget(self.refresh_btn)
        top_bar.addWidget(self.settings_btn); top_bar.addWidget(self.delete_btn)
        right_layout.addLayout(top_bar)
        self.file_list=QListWidget()
        self.file_list.setDragEnabled(True)
        self.file_list.setAcceptDrops(True)
        self.file_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.file_list.itemDoubleClicked.connect(self.open_file)
        right_layout.addWidget(self.file_list)
        right_panel.setLayout(right_layout)
        main_layout.addWidget(right_panel)
        central.setLayout(main_layout)
        self.upload_btn.clicked.connect(self.upload_file)
        self.import_btn.clicked.connect(self.import_vault_file)
        self.export_btn.clicked.connect(self.export_decrypted_file)
        self.refresh_btn.clicked.connect(self.load_files)
        self.settings_btn.clicked.connect(self.open_settings)
        self.delete_btn.clicked.connect(self.delete_file)
        self.setAcceptDrops(True)
    def apply_theme(self,theme):
        if theme=="暗黑": self.setStyleSheet(DARK_STYLE)
        else: self.setStyleSheet(LIGHT_STYLE)
    def load_tags(self):
        self.tag_list.clear(); self.tag_list.addItem("全部")
        for tag in self.storage.get_all_tags(): self.tag_list.addItem(tag)
        if self.current_tag:
            items=self.tag_list.findItems(self.current_tag, Qt.MatchExactly)
            if items: self.tag_list.setCurrentItem(items[0])
    def on_tag_clicked(self,item):
        self.current_tag=None if item.text()=="全部" else item.text()
        self.load_files()
    def create_tag(self):
        tag,ok=QInputDialog.getText(self,"创建标签","输入新标签名称：")
        if ok and tag and tag not in self.storage.get_all_tags():
            selected=self.file_list.currentItem()
            if selected:
                entry_id=selected.data(Qt.UserRole)
                self.storage.add_tag_to_entry(entry_id, tag)
                self.load_files(); self.load_tags()
            else:
                QMessageBox.information(self,"提示","请先选择一个文件来添加标签。")
    def delete_tag(self):
        current=self.tag_list.currentItem()
        if not current or current.text()=="全部": return
        tag=current.text()
        reply=QMessageBox.question(self,"确认",f"确定删除标签 '{tag}' 吗？",QMessageBox.Yes|QMessageBox.No)
        if reply==QMessageBox.Yes:
            for entry in self.storage.get_all_entries():
                if tag in entry.get('tags',[]): entry['tags'].remove(tag)
            self.storage._save_index()
            self.load_tags(); self.load_files()
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: event.ignore()
    def dropEvent(self,event):
        for url in event.mimeData().urls():
            file_path=url.toLocalFile()
            if os.path.isfile(file_path): self._do_upload(file_path)
        event.acceptProposedAction()
    def _do_upload(self,file_path):
        dialog=UploadDialog(self,file_path)
        if dialog.exec_():
            try:
                uid=self.storage.add_file(file_path, dialog.user_dest, dialog.is_advanced, dialog.second_methods)
                QMessageBox.information(self,"成功",f"文件已加密保存，ID: {uid}")
                self.load_files(); self.load_tags()
            except Exception as e: QMessageBox.critical(self,"错误",f"加密失败: {e}")
    def load_files(self):
        self.file_list.clear()
        entries=self.storage.get_all_entries()
        if self.current_tag:
            entries=[e for e in entries if self.current_tag in e.get('tags',[])]
        for entry in entries:
            tags_str="["+", ".join(entry.get('tags',[]))+"] " if entry.get('tags') else ""
            item_text=f"{tags_str}{entry['original_name']}  {'[高级]' if entry['is_advanced'] else ''}"
            item=QListWidgetItem(item_text)
            item.setData(Qt.UserRole, entry['id'])
            self.file_list.addItem(item)
    def upload_file(self):
        file_path,_=QFileDialog.getOpenFileName(self,"选择要加密的文件")
        if file_path: self._do_upload(file_path)
    def import_vault_file(self):
        file_path,_=QFileDialog.getOpenFileName(self,"选择要导入的 .vault 加密文件","","Vault Files (*.vault)")
        if not file_path: return
        is_advanced=QMessageBox.question(self,"高级文件","是否标记为高级文件？",QMessageBox.Yes|QMessageBox.No)==QMessageBox.Yes
        second_methods=[]
        if is_advanced:
            dialog=QDialog(self); dialog.setWindowTitle("选择二次验证方式")
            layout=QVBoxLayout()
            cb_totp=QCheckBox("TOTP"); cb_email=QCheckBox("邮箱"); cb_question=QCheckBox("问题"); cb_password=QCheckBox("密码")
            layout.addWidget(cb_totp); layout.addWidget(cb_email); layout.addWidget(cb_question); layout.addWidget(cb_password)
            btn_box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
            btn_box.accepted.connect(dialog.accept); btn_box.rejected.connect(dialog.reject)
            layout.addWidget(btn_box); dialog.setLayout(layout)
            if dialog.exec_()==QDialog.Accepted:
                if cb_totp.isChecked(): second_methods.append('totp')
                if cb_email.isChecked(): second_methods.append('email')
                if cb_question.isChecked(): second_methods.append('question')
                if cb_password.isChecked(): second_methods.append('password')
                if not second_methods:
                    QMessageBox.warning(self,"提示","至少选一种"); return
        try:
            uid=self.storage.import_vault_file(file_path, is_advanced=is_advanced, second_auth_methods=second_methods)
            QMessageBox.information(self,"成功",f"文件已导入，ID: {uid}")
            self.load_files(); self.load_tags()
        except Exception as e: QMessageBox.critical(self,"错误",f"导入失败: {e}")
    def export_decrypted_file(self):
        current=self.file_list.currentItem()
        if not current: QMessageBox.warning(self,"提示","请先选择文件"); return
        entry_id=current.data(Qt.UserRole)
        entry=self.storage.get_entry_by_id(entry_id)
        if not entry: QMessageBox.warning(self,"错误","记录不存在"); return
        if entry['is_advanced']:
            methods=entry['second_auth_methods']
            if not methods: QMessageBox.warning(self,"提示","未设置二次验证"); return
            auth_dialog=AuthDialog(self,self.auth,methods,entry_id)
            if auth_dialog.exec_()!=QDialog.Accepted: return
        else:
            avail=self._get_available_auth_methods()
            if not avail: QMessageBox.warning(self,"提示","无可用验证方式"); return
            auth_dialog=DeleteAuthDialog(self,self.auth,avail)
            if auth_dialog.exec_()!=QDialog.Accepted: return
        save_path,_=QFileDialog.getSaveFileName(self,"导出解密文件",entry['original_name'],"All Files (*.*)")
        if not save_path: return
        try:
            data=self.storage.get_file_data(entry_id)
            with open(save_path,'wb') as f: f.write(data)
            QMessageBox.information(self,"成功",f"导出到：{save_path}")
        except Exception as e: QMessageBox.critical(self,"错误",f"导出失败: {e}")
    def open_file(self,item):
        entry_id=item.data(Qt.UserRole)
        entry=self.storage.get_entry_by_id(entry_id)
        if not entry: return
        if entry['is_advanced']:
            methods=entry['second_auth_methods']
            if not methods: QMessageBox.warning(self,"提示","未设置二次验证"); return
            auth_dialog=AuthDialog(self,self.auth,methods,entry_id)
            if auth_dialog.exec_()!=QDialog.Accepted: return
        try:
            data=self.storage.get_file_data(entry_id)
            viewer=FileViewer(self,data,entry['type'],entry['original_name'])
            viewer.exec_()
        except Exception as e: QMessageBox.critical(self,"错误",f"打开失败: {e}")
    def open_settings(self):
        dialog=SettingsDialog(self,self.auth,self.is_recovery_login)
        dialog.exec_()
        self.load_tags(); self.load_files()
    def delete_file(self):
        current=self.file_list.currentItem()
        if not current: QMessageBox.warning(self,"提示","请先选择文件"); return
        entry_id=current.data(Qt.UserRole)
        avail=self._get_available_auth_methods()
        if not avail: QMessageBox.warning(self,"提示","无可用验证方式"); return
        auth_dialog=DeleteAuthDialog(self,self.auth,avail)
        if auth_dialog.exec_()!=QDialog.Accepted: return
        reply=QMessageBox.question(self,"确认删除","确定永久删除该文件？",QMessageBox.Yes|QMessageBox.No)
        if reply==QMessageBox.Yes:
            try:
                self.storage.remove_entry(entry_id,destroy=False)
                self.load_files()
                QMessageBox.information(self,"成功","已删除")
            except Exception as e: QMessageBox.critical(self,"错误",f"删除失败: {e}")
    def _get_available_auth_methods(self):
        methods=[]
        if self.auth.password_hash: methods.append('password')
        if self.auth.qa: methods.append('question')
        if self.auth.totp_secret: methods.append('totp')
        if self.auth.email_config: methods.append('email')
        return methods
