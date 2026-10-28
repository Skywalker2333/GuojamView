"""Small input windows over hotspots; the large visual canvas stays click-through."""
import ctypes as C
from ctypes import wintypes as W
from PyQt6.QtCore import Qt,QRectF,QPointF,QTimer
from PyQt6.QtGui import QColor,QPainter,QPainterPath,QPen,QPolygonF
from PyQt6.QtWidgets import QWidget
import native


class Hotspot(QWidget):
    def __init__(self,callback):
        super().__init__(None,Qt.WindowType.FramelessWindowHint|Qt.WindowType.Tool|Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle('GuojamView 控件')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.callback=callback;self.kind='app';self.payload=None;self.enabled=True
        self.hovered=False;self.pressed=False;self.physical=None;self.host=None

    def configure(self,kind,payload,enabled,physical,monitor):
        self.kind=kind;self.payload=payload;self.enabled=enabled;self.physical=physical
        self.setToolTip({'play':'播放','pause':'暂停','previous':'上一首','next':'下一首','app':'在主屏呼出'}.get(kind,''))
        if not self.isVisible():
            # Initial Qt placement establishes the monitor DPI before pixel correction.
            from PyQt6.QtWidgets import QApplication
            screen=next((s for s in QApplication.screens() if s.name()==monitor['device']),QApplication.primaryScreen())
            x,y,w,h=physical;dpr=screen.devicePixelRatio()
            self.setGeometry(screen.geometry().x()+round((x-monitor['rect'][0])/dpr),
                             screen.geometry().y()+round((y-monitor['rect'][1])/dpr),round(w/dpr),round(h/dpr))
            self.show()
            self.host=native.attach(int(self.winId()),dict(monitor,work=physical),click_through=not enabled)
            QTimer.singleShot(120,self.correct)
        else:self.correct()
        ex=native.user32.GetWindowLongPtrW(int(self.winId()),-20)
        native.user32.SetWindowLongPtrW(int(self.winId()),-20,ex&~0x20 if enabled else ex|0x20)
        self.update()

    def correct(self):
        if self.physical and self.host:
            x,y,w,h=self.physical
            native.user32.SetWindowPos(int(self.winId()),W.HWND(1),x,y,w,h,0x10|0x40)

    def enterEvent(self,event):self.hovered=True;self.update()
    def leaveEvent(self,event):self.hovered=False;self.pressed=False;self.update()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.enabled:self.pressed=True;self.update()

    def mouseReleaseEvent(self,event):
        pressed=self.pressed;self.pressed=False;self.update()
        if not pressed or not self.enabled or not self.rect().contains(event.position().toPoint()):return
        # If an ordinary window covered this hotspot between press and release,
        # never send the pending action through it.
        point=W.POINT();native.user32.GetCursorPos(C.byref(point))
        native.user32.WindowFromPoint.argtypes=[W.POINT];native.user32.WindowFromPoint.restype=W.HWND
        if native.user32.WindowFromPoint(point)!=int(self.winId()):return
        self.callback(self.kind,self.payload)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor(0,0,0,1))
        w,h=self.width(),self.height()
        if self.kind=='app':
            if self.hovered:
                p.setPen(QPen(QColor('#70dce7'),2));p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(1,1,w-2,h-2),10,10)
            p.end();return
        p.setOpacity(1. if self.enabled else .3)
        primary=self.kind in ('play','pause')
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#70dce7') if primary else QColor(239,248,252,85 if self.hovered else 35))
        p.drawEllipse(QRectF(1,1,w-2,h-2))
        p.save();p.translate(w/2,h/2)
        p.setBrush(QColor('#14232b') if primary else QColor('#edf4f7'))
        k=min(w,h)/52
        if self.pressed:k*=.92
        p.scale(k,k)
        if self.kind=='pause':
            p.drawRoundedRect(QRectF(-8,-10,5,20),1,1);p.drawRoundedRect(QRectF(3,-10,5,20),1,1)
        elif self.kind=='play':p.drawPolygon(QPolygonF([QPointF(-6,-11),QPointF(10,0),QPointF(-6,11)]))
        else:
            if self.kind=='previous':p.scale(-1,1)
            p.drawPolygon(QPolygonF([QPointF(-8,-9),QPointF(5,0),QPointF(-8,9)]));p.drawRoundedRect(QRectF(6,-9,3,18),.6,.6)
        p.restore();p.end()


class Hotspots:
    def __init__(self,controller):self.c=controller;self.windows={}

    def sync(self):
        c=self.c
        if c.stopping or not c.user_visible or not c.target or not c.dashboard.isVisible():
            for window in self.windows.values():window.hide()
            return
        if c.args.preview:return
        x,y,w,h=c.target['work'];scale=min(w/1920,h/1080)
        ox=x+(w-1920*scale)/2;oy=y+(h-1080*scale)/2
        models=c.dashboard.hotspots();keys={row[0] for row in models}
        for key in list(self.windows):
            if key not in keys:
                self.windows.pop(key).deleteLater()
        for key,rect,kind,payload,enabled in models:
            if key not in self.windows:self.windows[key]=Hotspot(c.activate_hotspot)
            physical=(round(ox+rect.x()*scale),round(oy+rect.y()*scale),round(rect.width()*scale),round(rect.height()*scale))
            self.windows[key].configure(kind,payload,enabled,physical,c.target)

    def close(self):
        for window in self.windows.values():window.close()
        self.windows.clear()
