DARK_STYLE = """
QMainWindow,QDialog{background:#2b2b2b;color:#f0f0f0}
QWidget{background:#2b2b2b;color:#f0f0f0}
QPushButton{background:#3c3c3c;border:1px solid #555;padding:5px;border-radius:3px;color:#f0f0f0}
QPushButton:hover{background:#4a4a4a}
QPushButton:pressed{background:#2a2a2a}
QLineEdit,QTextEdit,QListWidget,QTreeWidget,QComboBox,QSpinBox{background:#3c3c3c;border:1px solid #555;color:#f0f0f0}
QTreeWidget{outline:none}
QTreeWidget::item{height:24px}
QTreeWidget::item:selected{background:#4a4a4a;color:#ffffff}
QTreeWidget::item:hover{background:#2a2a2a}
QLabel{color:#f0f0f0}
QLabel#HintLabel{color:#888;font-size:8pt}
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

LIGHT_STYLE = """
QMainWindow,QDialog{background:#f5f5f5;color:#1a1a1a}
QWidget{background:#f5f5f5;color:#1a1a1a}
QPushButton{background:#e8e8e8;border:1px solid #c8c8c8;padding:5px;border-radius:3px;color:#1a1a1a}
QPushButton:hover{background:#dcdcdc}
QPushButton:pressed{background:#cccccc}
QLineEdit,QTextEdit,QListWidget,QTreeWidget,QComboBox,QSpinBox{background:#ffffff;border:1px solid #c8c8c8;color:#1a1a1a}
QTreeWidget{outline:none}
QTreeWidget::item{height:24px}
QTreeWidget::item:selected{background:#cce4f7;color:#000000}
QTreeWidget::item:hover{background:#e8f0f8}
QLabel{color:#1a1a1a}
QLabel#HintLabel{color:#666;font-size:8pt}
QGroupBox{border:1px solid #c8c8c8;margin-top:10px;color:#1a1a1a}
QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 5px}
QTabWidget::pane{border:1px solid #c8c8c8;background:#f5f5f5}
QTabBar::tab{background:#e8e8e8;color:#1a1a1a;padding:5px 10px}
QTabBar::tab:selected{background:#d5d5d5}
QScrollBar:vertical{background:#f0f0f0;width:12px}
QScrollBar::handle:vertical{background:#c0c0c0;border-radius:6px;min-height:20px}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0}
QMenuBar{background:#f5f5f5;color:#1a1a1a}
QMenuBar::item:selected{background:#e0e0e0}
QMenu{background:#ffffff;color:#1a1a1a;border:1px solid #c8c8c8}
QMenu::item:selected{background:#cce4f7}
QMessageBox{background:#f5f5f5;color:#1a1a1a}
QMessageBox QPushButton{min-width:80px}
QCheckBox{color:#1a1a1a}
QRadioButton{color:#1a1a1a}
QProgressBar{background:#e8e8e8;border:1px solid #c8c8c8;border-radius:3px;text-align:center;color:#1a1a1a}
QProgressBar::chunk{background:#5a8cbf}
QToolTip{background:#ffffff;color:#1a1a1a;border:1px solid #c8c8c8}
"""
