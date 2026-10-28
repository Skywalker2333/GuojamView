"""Native desktop QA; only creates/changes GuojamView's own test windows."""
import argparse
import copy
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

import native
native.dpi_awareness()
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication,QWidget,QVBoxLayout,QLabel,QPushButton
from PIL import ImageGrab
from app import Controller

app=QApplication(sys.argv)
out=Path(__file__).parent.parent/'native-qa';out.mkdir(exist_ok=True)
args=argparse.Namespace(preview=False,settings=False,diagnostics=None,quit_after=0)
c=Controller(app,args,out)
result={}
cover=QWidget();cover.setWindowTitle('GuojamView QA — 普通窗口覆盖测试')
cover.setStyleSheet('background:#213845;color:white;font:16pt "Microsoft YaHei UI"')
v=QVBoxLayout(cover);v.addWidget(QLabel('普通应用应覆盖圆环\n关闭后恢复透明监控'))
button=QPushButton('关闭测试窗口');button.clicked.connect(cover.close);v.addWidget(button)
screen=next(s for s in app.screens() if s.name()==c.target['device'])
g=screen.geometry();cover.setGeometry(g.x()+30,g.y()+390,380,160)

def check_base():
    hwnd=int(c.dashboard.winId());info=native.window_info(hwnd)
    result['window']=info
    result['monitor_rect']=info['rect']
    result['dpi']=info['dpi']
    result['transparent_style']=bool(info['ex_style']&0x20 and info['ex_style']&0x80000)
    native.user32.WindowFromPoint.argtypes=[W.POINT];native.user32.WindowFromPoint.restype=W.HWND
    rx,ry,rw,rh=c.target['rect']
    target=native.user32.WindowFromPoint(W.POINT(rx+rw//2,ry+rh//2))
    result['hit_test_passes_through']=int(target or 0)!=hwnd
    cover.show()
    QTimer.singleShot(700,check_cover)

def capture(name):
    x,y,w,h=c.target['rect'];ImageGrab.grab(bbox=(x,y,x+w,y+h),all_screens=True).save(out/name)

def check_cover():
    # Read z-order: a normal application must precede the desktop-owned overlay.
    order=[]
    @native.CALLBACK
    def cb(h,p):order.append(int(h));return True
    native.user32.EnumWindows(cb,0)
    result['normal_app_above_overlay']=order.index(int(cover.winId()))<order.index(int(c.dashboard.winId()))
    capture('coverage.png')
    # Remaining visual and dialog checks are exposed for Computer Use.
    c.show_settings()

def check_recovery():
    actual=native.monitors()
    with patch('app.native.monitors',return_value=[m for m in actual if m['device']!=c.target['device']]):
        c.bind_monitor(True)
        result['disconnect_hides']=not c.dashboard.isVisible()
    c.bind_monitor(True)
    result['reconnect_shows']=c.dashboard.isVisible()
    c.toggle();result['tray_hide']=not c.dashboard.isVisible()
    c.toggle();result['tray_show']=c.dashboard.isVisible()
    c.refresh();result['reset_clears_baseline']=c.dashboard.last_received is None
    # Exercise owner recovery using OUR window handle; Explorer is left running.
    c.host=None;c.bind_monitor(True)
    result['owner_rebind']=bool(c.host)
    (out/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')

QTimer.singleShot(5000,check_base)
QTimer.singleShot(45000,check_recovery)
QTimer.singleShot(55000,app.quit)
sys.exit(app.exec())
