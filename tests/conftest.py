import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('APPDATA', tempfile.gettempdir())

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
