"""Transparent native render QA. Test fixtures, never production sample data."""
import copy
from pathlib import Path
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor,QImage,QPainter,QFontInfo
from PyQt6.QtWidgets import QApplication
from app import DEFAULTS
from dashboard import Dashboard,display_font
from telemetry import Snapshot

app=QApplication(sys.argv)
out=Path(__file__).parent.parent/'visual-qa';out.mkdir(exist_ok=True)
settings=copy.deepcopy(DEFAULTS)
widget=Dashboard(settings,True);widget.resize(1920,1080)
print('Numeric font:',QFontInfo(display_font(84,True)).family(),QFontInfo(display_font(84,True)).styleName())
print('Chinese font:',QFontInfo(display_font(32,False)).family(),QFontInfo(display_font(32,False)).weight())

for state in ('empty','zero','full'):
    if state=='empty':snapshot=Snapshot()
    else:
        percent=0 if state=='zero' else 100
        snapshot=Snapshot(timestamp=1,cpu=percent,memory=dict(percent=percent,used=16*1024**3*percent/100,total=16*1024**3),
                          gpu=dict(load=percent,used=8*1024**3*percent/100,total=8*1024**3,temperature=70),
                          processes=[dict(pid=i,name='示例应用 · 很长的应用名称',foreground=i==0,cpu=percent,memory=2*1024**3,exe='') for i in range(4)])
    widget.receive(snapshot)
    for scale in (1.,1.15):
        settings['font_scale']=scale
        overlay=widget.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
        # Background remains actually transparent, rather than a wallpaper screenshot.
        assert overlay.pixelColor(800,300).alpha()==0
        overlay.save(str(out/f'{state}-{scale}-transparent.png'))
        if state=='full':
            for theme,background in [('light','#f2f4f7'),('dark','#101418')]:
                canvas=QImage(1920,1080,QImage.Format.Format_ARGB32);canvas.fill(QColor(background))
                painter=QPainter(canvas);painter.drawImage(0,0,overlay);painter.end()
                canvas.save(str(out/f'{theme}-{scale}.png'))
print('PASS: transparent background, empty / zero / 100%, both supported font scales rendered')
