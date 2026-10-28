"""Four quiet rings and the user's open applications, on a clear canvas."""
import time
from datetime import datetime
from functools import lru_cache

from PyQt6.QtCore import Qt, QPointF, QRectF, QFileInfo, QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QImageReader, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget, QFileIconProvider
from telemetry import Snapshot
from weather import condition
from lyrics import lyric_at
import math

WHITE = '#edf4f7'
MUTED = '#cedae0'
CYAN = '#70dce7'


def fmt(value, suffix='', decimals=0):
    return '—' if value is None else f'{value:,.{decimals}f}{suffix}'


def storage(value):
    if value is None:return '—'
    return f'{value / 1024**3:.1f} GB'


@lru_cache(maxsize=512)
def text_stamp(text, size, numeric, outline, color, effect=False):
    font=display_font(size,numeric)
    metrics=QFontMetricsF(font)
    advance=metrics.horizontalAdvance(text)
    image=QImage(int(advance)+24,int(metrics.height())+24,QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p=QPainter(image);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path=QPainterPath();path.addText(5,metrics.ascent()+5,font,text)
    if effect:
        p.save();p.translate(4,6)
        p.fillPath(path,QColor(4,12,22,150));p.restore()
        p.strokePath(path,QPen(QColor(4,12,22,170),5.5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        p.strokePath(path,QPen(QColor(112,220,231,190),2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    elif outline:
        # A light edge keeps text legible without the old heavy outlined look.
        p.strokePath(path,QPen(QColor(3,9,15,125),1.2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    p.fillPath(path,QColor(color));p.end()
    return image,advance,metrics.ascent()


def display_font(size,numeric=False):
    font=QFont('Bahnschrift' if numeric else 'Microsoft YaHei UI')
    if numeric:font.setStyleName('SemiBold')
    font.setWeight(QFont.Weight.DemiBold)
    font.setPixelSize(size)
    return font


class Dashboard(QWidget):
    def __init__(self,settings,preview=False):
        flags=Qt.WindowType.FramelessWindowHint|Qt.WindowType.Tool
        if not preview:flags|=Qt.WindowType.WindowTransparentForInput|Qt.WindowType.WindowDoesNotAcceptFocus
        super().__init__(None,flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle('GuojamView — 透明系统监控')
        self.settings=settings;self.snapshot=Snapshot();self.info={}
        self.status='正在采集';self.last_received=None
        self.history=[]
        from collections import deque
        self.paint_ms=deque(maxlen=600);self.paint_count=0
        self.icons={};self.icon_provider=QFileIconProvider();self.p=None
        self.media=None;self.media_received=None;self.cover_data=b'';self.cover_image=QImage()
        self.weather=None;self.lyric_lines=[];self.lyric_track=None

    def receive(self,snapshot):
        self.snapshot=snapshot;self.last_received=time.monotonic();self.status='实时';self.update()

    def receive_media(self,media):
        self.media=media;self.media_received=time.monotonic()
        data=media.cover if media else b''
        if data!=self.cover_data:
            self.cover_data=data;self.cover_image=QImage()
            if data:
                buffer=QBuffer();buffer.setData(QByteArray(data));buffer.open(QIODevice.OpenModeFlag.ReadOnly)
                reader=QImageReader(buffer)
                size=reader.size()
                if 0<size.width()<=8192 and 0<size.height()<=8192:
                    size.scale(472,472,Qt.AspectRatioMode.KeepAspectRatio)
                    reader.setScaledSize(size);self.cover_image=reader.read()
                buffer.close()
        self.update()

    def draw_media(self):
        m=self.media
        if not m or not self.settings['modules'].get('music',True):return
        if self.media_received is None or time.monotonic()-self.media_received>5:return
        p=self.p;rect=QRectF(72,358,196,196)
        p.save();p.setOpacity(self.settings['text_opacity']/100)
        clip=QPainterPath();clip.addRoundedRect(rect,22,22);p.setClipPath(clip)
        if not self.cover_image.isNull():
            image=self.cover_image;side=min(image.width(),image.height())
            source=QRectF((image.width()-side)/2,(image.height()-side)/2,side,side)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform);p.drawImage(rect,image,source)
        else:
            p.fillRect(rect,QColor(20,34,44,180));p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(215,238,245,100),2));p.drawEllipse(QPointF(170,456),65,65)
            p.drawEllipse(QPointF(170,456),55,55);p.setPen(QPen(QColor(CYAN),6));p.drawEllipse(QPointF(170,456),13,13)
        p.restore()
        self.text(304,371,'QQ 音乐' if 'qqmusic' in m.source.lower() else ('正在播放' if m.playing else '已暂停'),21,CYAN)
        self.text(304,425,m.title,52,width=676,effect=True)
        source={'Chrome':'Google Chrome','Spotify.exe':'Spotify','Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic':'媒体播放器'}.get(m.source,m.source)
        self.text(304,472,m.artist or source,31,width=676)
        if m.duration>0:
            position=max(0,min(m.duration,m.position))
            p.save();p.setOpacity(self.settings['chart_opacity']/100)
            p.setPen(QPen(QColor(4,12,20,130),12,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(304,520),QPointF(1210,520))
            p.setPen(QPen(QColor(225,241,246,100),8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(304,520),QPointF(1210,520))
            p.setPen(QPen(QColor(CYAN),9,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
            end=304+906*position/m.duration
            p.drawLine(QPointF(304,520),QPointF(end,520))
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(WHITE));p.drawEllipse(QPointF(end,520),7,7);p.restore()
            def duration_text(seconds):
                seconds=int(seconds);return f'{seconds//60}:{seconds%60:02d}'
            self.text(304,559,duration_text(position),23,MUTED,numeric=True)
            self.text(1210,559,duration_text(m.duration),23,MUTED,numeric=True,align='right')
        track=(m.title,m.artist,round(m.duration))
        if self.settings['modules'].get('lyrics',True) and track==self.lyric_track:
            line=lyric_at(self.lyric_lines,m.position)
            if line:self.text(72,614,line,31,WHITE,width=1180,effect=True)

    def app_rows(self):
        sort=self.settings['process_sort']
        return sorted(self.snapshot.processes,key=lambda r:(r.get('foreground',False),r.get(sort) or 0),reverse=True)[:4]

    def hotspots(self):
        rows=[]
        if self.settings['modules'].get('apps',True):
            for i,app in enumerate(self.app_rows()):
                if app.get('hwnd'):rows.append((f'app{i}',QRectF(1360,650+i*90,78,78),'app',app['hwnd'],True))
        m=self.media
        if m and self.settings['modules'].get('music',True) and self.media_received and time.monotonic()-self.media_received<5:
            rows.extend([('previous',QRectF(1010,399,52,52),'previous',m.source,m.can_previous),
                         ('toggle',QRectF(1084,389,72,72),'pause' if m.playing else 'play',m.source,True),
                         ('next',QRectF(1178,399,52,52),'next',m.source,m.can_next)])
        return rows

    def draw_weather(self):
        w=self.weather
        if not self.settings['modules'].get('weather',True) or not w:return
        if w.temperature is None:
            self.text(74,143,'—°',64,numeric=True,effect=True)
            self.text(74,213,f'{w.city}  ·  {w.error or "更新中"}',27,width=650,effect=True)
            return
        p=self.p;x=112;y=123
        p.save();p.setRenderHint(QPainter.RenderHint.Antialiasing)
        kind=condition(w.code)
        if w.code==0 and not w.is_day:
            moon=QPainterPath();moon.addEllipse(QPointF(x,y),29,29)
            cut=QPainterPath();cut.addEllipse(QPointF(x+16,y-9),27,27)
            p.fillPath(moon.subtracted(cut),QColor('#e3eaf7'))
        else:
            if kind in ('晴','多云'):
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#ffd27a'));p.drawEllipse(QPointF(x-8,y-8),23,23)
                p.setPen(QPen(QColor('#ffd27a'),4,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
                for a in range(0,360,45):
                    radians=math.radians(a);dx=math.cos(radians);dy=math.sin(radians)
                    p.drawLine(QPointF(x-8+30*dx,y-8+30*dy),QPointF(x-8+37*dx,y-8+37*dy))
            if kind!='晴':
                cloud=QPainterPath();cloud.addEllipse(QPointF(x-12,y+8),24,20);cloud.addEllipse(QPointF(x+9,y-3),28,26);cloud.addEllipse(QPointF(x+32,y+13),21,17);cloud.addRect(QRectF(x-13,y+10,46,20))
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#e6f0f5'));p.drawPath(cloud.simplified())
                if kind in ('雨','毛毛雨','雷雨'):
                    p.setPen(QPen(QColor(CYAN),4,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
                    for dx in (-12,8,28):p.drawLine(QPointF(x+dx,y+37),QPointF(x+dx-5,y+48))
                elif kind=='雪':
                    p.setPen(QPen(QColor('#d8f3ff'),5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
                    for dx in (-12,8,28):p.drawPoint(QPointF(x+dx,y+42))
                elif kind=='雾':
                    p.setPen(QPen(QColor('#d5e5ec'),4,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap));p.drawLine(QPointF(x-27,y+40),QPointF(x+40,y+40))
        p.restore()
        self.text(183,143,fmt(w.temperature,'°',0),64,numeric=True,effect=True)
        self.text(74,213,f'{w.city}  ·  {w.description or kind}',27,width=650,effect=True)

    def text(self,x,y,value,size=18,color=WHITE,numeric=False,align='left',width=None,effect=False):
        text=str(value);size=max(10,round(size*self.settings['font_scale']))
        if width:
            font=display_font(size,numeric)
            text=QFontMetricsF(font).elidedText(text,Qt.TextElideMode.ElideRight,width)
        image,advance,ascent=text_stamp(text,size,numeric,self.settings['outline'],color,effect)
        if align=='right':x-=advance
        if align=='center':x-=advance/2
        self.p.save();self.p.setOpacity(self.settings['text_opacity']/100)
        self.p.drawImage(QPointF(x-5,y-ascent-5),image);self.p.restore()

    def ring(self,cx,cy,label,value,subline=''):
        r=130;rect=QRectF(cx-r,cy-r,2*r,2*r)
        self.p.save();self.p.setOpacity(self.settings['chart_opacity']/100)
        self.p.setBrush(Qt.BrushStyle.NoBrush)
        self.p.setPen(QPen(QColor(229,244,249,48),12,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        self.p.drawArc(rect,225*16,-270*16)
        if value is not None:
            self.p.setPen(QPen(QColor(CYAN),14,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
            if value>0:self.p.drawArc(rect,225*16,-round(max(0,min(100,value))*2.7*16))
        self.p.restore()
        if value is None:
            self.text(cx,cy+22,'—',78,numeric=True,align='center')
        else:
            number=f'{value:.0f}'
            size=round(84*self.settings['font_scale'])
            _,num_width,_=text_stamp(number,size,True,self.settings['outline'],WHITE)
            _,unit_width,_=text_stamp('%',round(34*self.settings['font_scale']),True,self.settings['outline'],MUTED)
            left=cx-(num_width+unit_width+6)/2
            self.text(left,cy+22,number,84,numeric=True)
            self.text(left+num_width+6,cy+21,'%',34,MUTED,numeric=True)
        self.text(cx,cy+76,label,32,align='center')
        if subline:self.text(cx,cy+184,subline,24,MUTED,numeric=True,align='center')

    def paintEvent(self,event):
        start=time.perf_counter();p=QPainter(self);self.p=p
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale=min(self.width()/1920,self.height()/1080)
        p.translate((self.width()-1920*scale)/2,(self.height()-1080*scale)/2);p.scale(scale,scale)
        s=self.snapshot;now=datetime.now();modules=self.settings['modules']
        self.draw_media()
        self.draw_weather()
        if modules.get('clock',True):
            self.text(1848,208,now.strftime('%H:%M'),160,numeric=True,align='right',effect=True)
            weekday='一二三四五六日'[now.weekday()]
            self.text(1848,268,f'{now:%m 月 %d 日}  星期{weekday}',36,WHITE,align='right',effect=True)
        specs=[('cpu','处理器',s.cpu,fmt(s.cpu_temperature,'°C') if s.cpu_temperature is not None else '温度 —'),
               ('gpu','显卡',s.gpu.get('load'),fmt(s.gpu.get('temperature'),'°C')),
               ('memory','内存',s.memory.get('percent'),f"{storage(s.memory.get('used'))} / {storage(s.memory.get('total'))}"),
               ('vram','显存',100*s.gpu['used']/s.gpu['total'] if s.gpu.get('total') and s.gpu.get('used') is not None else None,
                f"{storage(s.gpu.get('used'))} / {storage(s.gpu.get('total'))}")]
        for i,(_,label,value,subline) in enumerate(r for r in specs if modules.get(r[0],True)):
            self.ring(180+i*308,778,label,value,subline)
        if modules.get('apps',True):
            x=1364;self.text(x,608,'已打开的应用',28,MUTED)
            rows=self.app_rows()
            for i,row in enumerate(rows):
                y=682+i*90;exe=row.get('exe','')
                if exe and exe not in self.icons:
                    if len(self.icons)>32:self.icons.clear()
                    self.icons[exe]=self.icon_provider.icon(QFileInfo(exe)).pixmap(96,96)
                if exe and exe in self.icons:
                    pixmap=self.icons[exe]
                    p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(245,250,252,235))
                    p.drawRoundedRect(QRectF(x-4,y-32,78,78),18,18)
                    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                    p.drawPixmap(QRectF(x+3,y-25,64,64),pixmap,QRectF(pixmap.rect()))
                if row.get('foreground'):
                    p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(CYAN));p.drawEllipse(QPointF(x-14,y-7),2.5,2.5)
                self.text(x+90,y,row['name'],32,width=394)
                memory=f"{row['memory']/1024**3:.1f} GB" if row['memory']>=1024**3 else f"{row['memory']/1024**2:,.0f} MB"
                self.text(x+90,y+34,f"CPU {fmt(row['cpu'],'%',1)}   ·   内存 {memory}",23,MUTED,numeric=True)
            if not rows:self.text(x,710,'暂无已打开的应用',24,MUTED)
        if self.last_received is None or time.monotonic()-self.last_received>5:
            self.text(72,1000,self.status if self.last_received is None else '采样暂时中断',14,MUTED)
        p.end();self.p=None;self.paint_count+=1;self.paint_ms.append((time.perf_counter()-start)*1000)
