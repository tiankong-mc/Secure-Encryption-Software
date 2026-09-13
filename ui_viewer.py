import os, tempfile
from io import BytesIO
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QLabel, QPushButton, QHBoxLayout, QMessageBox
from PyQt5.QtCore import Qt, QUrl, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PIL import Image, ImageQt
import docx, PyPDF2
from ui_utils import protect_window


class FileViewer(QDialog):
    """文件预览（文本/图片/视频/音频/文档）"""

    def __init__(self, parent, data, ftype, original_name):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle(f"查看: {original_name}")
        self.setModal(False)  # 非模态，允许操作主界面
        self.resize(700, 500)
        layout = QVBoxLayout()
        self.tmp_path = None
        self.player = None
        self.file_data = data
        self.exported_tmp_files = []  # 导出的明文临时文件，关闭时统一清理

        if ftype == 'text':
            te = QTextEdit()
            te.setPlainText(data.decode('utf-8', errors='replace'))
            te.setReadOnly(True)
            layout.addWidget(te)
        elif ftype == 'image':
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                label = QLabel()
                label.setPixmap(pixmap.scaled(600, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                layout.addWidget(label)
            else:
                try:
                    img = Image.open(BytesIO(data))
                    qimg = ImageQt.ImageQt(img)
                    pixmap = QPixmap.fromImage(qimg)
                    label = QLabel()
                    label.setPixmap(pixmap.scaled(600, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    layout.addWidget(label)
                except:
                    layout.addWidget(QLabel("无法显示该图片"))
        elif ftype in ['video', 'audio']:
            try:
                ext = os.path.splitext(original_name)[1]
                fd, path = tempfile.mkstemp(suffix=ext)
                os.close(fd)
                with open(path, 'wb') as f:
                    f.write(data)
                self.tmp_path = path
                abs_path = os.path.abspath(path)
                self.player = QMediaPlayer()
                if ftype == 'video':
                    self.video_widget = QVideoWidget()
                    layout.addWidget(self.video_widget)
                    self.player.setVideoOutput(self.video_widget)
                self.player.setMedia(QMediaContent(QUrl.fromLocalFile(abs_path)))
                self.load_ok = False
                self.player.mediaStatusChanged.connect(self.check_media_status)
                QTimer.singleShot(5000, self.check_load_timeout)
                cl = QHBoxLayout()
                pb = QPushButton("播放/暂停")
                pb.clicked.connect(self.toggle_play)
                cl.addWidget(pb)
                sb = QPushButton("停止")
                sb.clicked.connect(self.player.stop)
                cl.addWidget(sb)
                if ftype == 'audio':
                    self.position_label = QLabel("00:00 / 00:00")
                    cl.addWidget(self.position_label)
                    self.timer = QTimer(self)
                    self.timer.timeout.connect(self.update_position)
                    self.timer.start(1000)
                eb = QPushButton("导出并观看")
                eb.clicked.connect(self.export_and_view)
                cl.addWidget(eb)
                layout.addLayout(cl)
                self.status_label = QLabel("正在加载媒体...")
                layout.addWidget(self.status_label)
                self.player.play()
                self.finished.connect(self.cleanup_tmp)
            except Exception as e:
                layout.addWidget(QLabel(f"播放器初始化失败: {e}"))
                btn = QPushButton("导出并观看")
                btn.clicked.connect(self.export_and_view)
                layout.addWidget(btn)
        elif ftype == 'document':
            ext = os.path.splitext(original_name)[1].lower()
            text_content = ""
            try:
                if ext in ['.docx']:
                    doc = docx.Document(BytesIO(data))
                    for para in doc.paragraphs:
                        text_content += para.text + "\n"
                elif ext in ['.pdf']:
                    pdf_reader = PyPDF2.PdfReader(BytesIO(data))
                    for page in pdf_reader.pages:
                        text_content += (page.extract_text() or "") + "\n"
                else:
                    text_content = "此文档格式暂不支持预览"
            except Exception as e:
                text_content = f"文档解析失败: {e}"
            te = QTextEdit()
            te.setPlainText(text_content)
            te.setReadOnly(True)
            layout.addWidget(te)
        else:
            layout.addWidget(QLabel("不支持预览此文件类型"))
        self.setLayout(layout)

    def showEvent(self, event):
        super().showEvent(event)
        # 跟随主窗口的截屏防护设置
        if getattr(self.parent_window, 'screenshot_protection', False):
            protect_window(self, True)

    def check_media_status(self, status):
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            self.load_ok = True
            if hasattr(self, 'status_label'):
                self.status_label.setText("媒体已加载，正在播放...")
        elif status == QMediaPlayer.InvalidMedia:
            if hasattr(self, 'status_label'):
                self.status_label.setText("❌ 媒体格式不支持，请导出观看")
            self.load_ok = False
        elif status == QMediaPlayer.NoMedia:
            if hasattr(self, 'status_label'):
                self.status_label.setText("无媒体")
            self.load_ok = False

    def check_load_timeout(self):
        if not hasattr(self, 'load_ok') or not self.load_ok:
            if hasattr(self, 'status_label'):
                self.status_label.setText("⚠️ 加载超时，请尝试导出观看")

    def toggle_play(self):
        if self.player and self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def update_position(self):
        if hasattr(self, 'player') and self.player:
            if self.player.state() != QMediaPlayer.StoppedState:
                pos = self.player.position()
                dur = self.player.duration()
                if dur > 0:
                    self.position_label.setText(f"{pos//60000:02d}:{(pos%60000)//1000:02d} / {dur//60000:02d}:{(dur%60000)//1000:02d}")

    def export_and_view(self):
        if hasattr(self, 'file_data') and self.file_data:
            ext = os.path.splitext(self.windowTitle().replace("查看: ", ""))[1] if hasattr(self, 'windowTitle') else '.bin'
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(self.file_data)
                export_path = tmp.name
            self.exported_tmp_files.append(export_path)
            os.startfile(export_path)
            QMessageBox.information(self, "提示", f"文件已导出到：{export_path}\n关闭预览窗口后将自动清理。")
        else:
            QMessageBox.warning(self, "错误", "没有可导出的数据")

    def cleanup_tmp(self):
        if hasattr(self, 'tmp_path') and self.tmp_path and os.path.exists(self.tmp_path):
            try:
                os.unlink(self.tmp_path)
            except:
                pass

    def closeEvent(self, event):
        self.cleanup_tmp()
        for path in self.exported_tmp_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except:
                pass
        event.accept()
