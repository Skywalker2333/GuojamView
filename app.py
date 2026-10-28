"""GuojamView: transparent, local-only secondary-display system monitor."""
import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import statistics
import sys
import time
import winreg

import native
native.dpi_awareness()
import psutil
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QSlider, QSystemTrayIcon, QMenu,
    QTabWidget, QVBoxLayout, QWidget)

from dashboard import Dashboard
from telemetry import SamplingThread
from media import MediaThread
from weather import WeatherThread
from lyrics import LyricsThread
from controls import Hotspots

VERSION = '1.2.0'
MODULES = dict(cpu='处理器圆环', gpu='显卡圆环', memory='内存圆环', vram='显存圆环', apps='已打开的应用', clock='时钟',music='正在播放',weather='天气',lyrics='同步歌词')
DEFAULTS = dict(monitor='', font_scale=1., text_opacity=100, chart_opacity=95,
                outline=True, process_sort='cpu', startup=False, weather_city='北京',
                modules={k: True for k in MODULES})


def load_settings(path):
    settings = dict(DEFAULTS, modules=dict(DEFAULTS['modules']))
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(raw,dict):return settings
        for key in ('monitor','weather_city'):
            if isinstance(raw.get(key), str):
                settings[key] = raw[key][:80] if key=='weather_city' else raw[key]
        for key in ('outline', 'startup'):
            if isinstance(raw.get(key), bool):
                settings[key] = raw[key]
        for key, lo, hi in [('font_scale', .8, 1.15), ('text_opacity', 25, 100), ('chart_opacity', 25, 100)]:
            value = raw.get(key)
            if isinstance(value, (int, float)) and lo <= value <= hi:
                settings[key] = value
        if raw.get('process_sort') in ('cpu', 'memory'):
            settings['process_sort'] = raw['process_sort']
        if isinstance(raw.get('modules'), dict):
            settings['modules'].update({k:v for k,v in raw['modules'].items() if k in MODULES and isinstance(v, bool)})
    except (OSError, ValueError, TypeError):
        pass
    return settings


def save_settings(path, settings):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def startup_command():
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"'
    executable = Path(sys.executable).with_name('pythonw.exe')
    return f'"{executable}" "{Path(__file__).resolve()}"'


def set_startup(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:
            winreg.SetValueEx(key, 'GuojamView', 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, 'GuojamView')
            except FileNotFoundError:
                pass


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            return bool(winreg.QueryValueEx(key, 'GuojamView')[0])
    except OSError:
        return False


def icon():
    pix = QPixmap(64,64)
    pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor('#70dce7'), 4))
    p.drawRoundedRect(5,10,54,38,7,7)
    p.drawLine(22,57,42,57)
    p.drawLine(32,48,32,57)
    p.drawPolyline(*[QPoint(x,y) for x,y in [(13,33),(23,33),(28,23),(35,39),(41,29),(51,29)]])
    p.end()
    return QIcon(pix)


class SettingsDialog(QDialog):
    def __init__(self, controller):
        super().__init__()
        self.c=controller
        s=controller.settings
        self.setWindowTitle('GuojamView 设置')
        self.setWindowIcon(controller.app_icon)
        self.resize(620, 660)
        self.setStyleSheet('''
            QDialog, QWidget { background:#101418; color:#edf4f7; font:10pt "Microsoft YaHei UI"; }
            QLabel#heading { font-size:22pt; font-weight:600; }
            QTabWidget::pane { border:0; }
            QTabBar::tab { padding:12px 18px; color:#acbec8; }
            QTabBar::tab:selected { color:#edf4f7; border-bottom:2px solid #70dce7; }
            QComboBox, QDoubleSpinBox { background:#20282e; border:1px solid #36444e; border-radius:4px; padding:7px; }
            QPushButton { background:#26323a; border:0; border-radius:4px; padding:9px 22px; }
            QPushButton:default { background:#dcebf0; color:#101418; }
            QPushButton:hover { background:#3a4c58; }
            QCheckBox { spacing:10px; padding:6px 0; }
            QSlider::groove:horizontal { height:3px; background:#344550; }
            QSlider::handle:horizontal { background:#70dce7; width:14px; margin:-6px 0; border-radius:7px; }
            QTableWidget { background:#101418; gridline-color:#26323a; border:0; }
            QHeaderView::section { background:#101418; color:#b5c9d3; border:0; padding:6px; }
        ''')
        layout=QVBoxLayout(self)
        layout.setContentsMargins(26,22,26,22)
        heading=QLabel('GuojamView');heading.setObjectName('heading');layout.addWidget(heading)
        layout.addWidget(QLabel('透明副屏 · 四个圆环与已打开的应用'))
        tabs=QTabWidget();layout.addWidget(tabs,1)
        general=QWidget();form=QFormLayout(general);form.setVerticalSpacing(18)
        self.monitor=QComboBox()
        for m in native.monitors():
            label=f"{m['device']}   {m['rect'][2]} × {m['rect'][3]}"+('  主屏' if m['primary'] else '  副屏')
            self.monitor.addItem(label,m['device'])
        if self.monitor.findData(s['monitor'])<0:
            self.monitor.addItem(s['monitor']+'（未连接）',s['monitor'])
        self.monitor.setCurrentIndex(max(0,self.monitor.findData(s['monitor'])))
        form.addRow('显示器',self.monitor)
        self.font=QDoubleSpinBox();self.font.setRange(.8,1.15);self.font.setSingleStep(.05);self.font.setValue(s['font_scale']);self.font.setSuffix(' ×')
        form.addRow('字号',self.font)
        self.city=QLineEdit(s['weather_city']);self.city.setMaxLength(80);form.addRow('天气城市',self.city)
        self.sliders={}
        for key,label in [('text_opacity','文字不透明度'),('chart_opacity','图表不透明度')]:
            row=QWidget();box=QHBoxLayout(row);box.setContentsMargins(0,0,0,0)
            slider=QSlider(Qt.Orientation.Horizontal);slider.setRange(25,100);slider.setValue(int(s[key]));slider.setAccessibleName(label)
            value=QLabel(f'{int(s[key])}%');value.setFixedWidth(45);slider.valueChanged.connect(lambda v,label=value: label.setText(f'{v}%'))
            box.addWidget(slider);box.addWidget(value);form.addRow(label,row);self.sliders[key]=slider
        self.outline=QCheckBox('增强文字轮廓');self.outline.setChecked(s['outline']);form.addRow('',self.outline)
        self.startup=QCheckBox('登录 Windows 时启动');self.startup.setChecked(startup_enabled());form.addRow('',self.startup)
        tabs.addTab(general,'外观与桌面')
        content=QWidget();v=QVBoxLayout(content);f=QFormLayout();v.addLayout(f)
        self.sort=QComboBox();self.sort.addItem('CPU 占用','cpu');self.sort.addItem('内存占用','memory');self.sort.setCurrentIndex(self.sort.findData(s['process_sort']));f.addRow('应用排序',self.sort)
        v.addWidget(QLabel('显示模块'))
        grid=QGridLayout();self.checks={}
        for i,(key,name) in enumerate(MODULES.items()):
            cb=QCheckBox(name);cb.setChecked(s['modules'][key]);grid.addWidget(cb,i//2,i%2);self.checks[key]=cb
        v.addLayout(grid);v.addStretch();tabs.addTab(content,'监控内容')
        temperature=controller.dashboard.snapshot.cpu_temperature
        v.addWidget(QLabel(f'CPU 温度：{temperature:.0f}°C' if temperature is not None else 'CPU 温度：未检测到传感器源'))
        attribution=QLabel('<a style="color:#a9c2cd" href="https://tianqi.qq.com/">腾讯天气</a> / <a style="color:#a9c2cd" href="https://open-meteo.com/">Open-Meteo</a>　·　歌词：QQ 音乐 / LRCLIB')
        attribution.setOpenExternalLinks(True);v.addWidget(attribution)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def save(self):
        s=dict(self.c.settings)
        if not self.city.text().strip():
            QMessageBox.warning(self,'城市不能为空','请输入天气城市。');return
        s.update(monitor=self.monitor.currentData(),font_scale=self.font.value(),
                 outline=self.outline.isChecked(),startup=self.startup.isChecked(),
                 process_sort=self.sort.currentData(),weather_city=self.city.text().strip(),
                 modules={k:cb.isChecked() for k,cb in self.checks.items()})
        s.update({k:slider.value() for k,slider in self.sliders.items()})
        try:
            if s['startup'] != startup_enabled():
                set_startup(s['startup'])
            save_settings(self.c.config_path,s)
        except OSError as exc:
            QMessageBox.warning(self,'无法保存',str(exc));return
        self.c.settings.clear();self.c.settings.update(s)
        self.c.weather_worker.city=s['weather_city']
        self.c.weather_worker.enabled=s['modules']['weather']
        self.c.lyrics_worker.enabled=s['modules']['lyrics'] and s['modules']['music']
        if self.c.dashboard.weather and self.c.dashboard.weather.city!=s['weather_city']:self.c.dashboard.weather=None
        self.c.bind_monitor(force=True)
        self.c.dashboard.update()
        self.c.hotspots.sync()
        self.accept()


class Controller:
    def __init__(self, app, args, data_dir):
        self.app=app;self.args=args;self.data_dir=data_dir
        self.config_path=data_dir/'settings.json'
        self.settings=load_settings(self.config_path)
        self.app_icon=icon();app.setWindowIcon(self.app_icon)
        self.dashboard=Dashboard(self.settings,preview=args.preview)
        self.hotspots=Hotspots(self)
        self.host=None;self.target=None;self.user_visible=True;self.stopping=False;self.dialog=None
        self.started=time.monotonic();self.records=[];self.snapshot_count=0
        self.process=psutil.Process();self.process.cpu_percent(None)
        self.worker=SamplingThread()
        self.worker.sampled.connect(self.receive)
        self.worker.failed.connect(self.failed)
        self.media_worker=MediaThread();self.media_worker.changed.connect(self.receive_media)
        self.media_worker.action_failed.connect(lambda message:self.tray.showMessage('GuojamView',message,QSystemTrayIcon.MessageIcon.Information,2000))
        self.weather_worker=WeatherThread(self.settings['weather_city']);self.weather_worker.enabled=self.settings['modules']['weather']
        self.weather_worker.changed.connect(self.receive_weather)
        self.lyrics_worker=LyricsThread();self.lyrics_worker.enabled=self.settings['modules']['lyrics'] and self.settings['modules']['music']
        self.lyrics_worker.changed.connect(self.receive_lyrics)
        self.tray=QSystemTrayIcon(self.app_icon,app);self.tray.setToolTip('GuojamView · 透明系统监控')
        menu=QMenu();self.toggle_action=menu.addAction('隐藏监控',self.toggle)
        menu.addAction('设置…',self.show_settings)
        menu.addAction('刷新采集',self.refresh)
        menu.addSeparator();menu.addAction('退出',app.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated);self.tray.show()
        app.screenAdded.connect(lambda *_: self.bind_monitor(force=True))
        app.screenRemoved.connect(lambda *_: self.bind_monitor(force=True))
        app.primaryScreenChanged.connect(lambda *_: self.bind_monitor(force=True))
        for screen in app.screens():
            screen.geometryChanged.connect(lambda *_: self.bind_monitor(force=True))
            screen.availableGeometryChanged.connect(lambda *_: self.bind_monitor(force=True))
        self.guard=QTimer();self.guard.timeout.connect(self.bind_monitor);self.guard.start(2000)
        self.clock=QTimer();self.clock.timeout.connect(lambda: self.dashboard.update());self.clock.start(1000)
        self.bind_monitor(force=True)
        self.worker.start()
        self.media_worker.start()
        self.weather_worker.start();self.lyrics_worker.start()
        app.aboutToQuit.connect(self.shutdown)
        if args.settings:QTimer.singleShot(500,self.show_settings)
        if args.quit_after:QTimer.singleShot(int(args.quit_after*1000),app.quit)
        if args.diagnostics:
            Path(args.diagnostics).mkdir(parents=True,exist_ok=True)
            QTimer.singleShot(10000,self.capture)

    def failed(self,message):
        self.dashboard.status=message
        self.dashboard.snapshot=__import__('telemetry').Snapshot()
        self.dashboard.last_received=None
        self.dashboard.history.clear();self.dashboard.update()

    def receive_media(self,media):
        self.dashboard.receive_media(media)
        track=(media.title,media.artist,round(media.duration)) if media else None
        if track!=self.lyrics_worker.track:
            self.dashboard.lyric_track=None;self.dashboard.lyric_lines=[]
            self.lyrics_worker.track=track
        self.hotspots.sync()

    def receive_weather(self,weather):
        if weather.city==self.settings['weather_city']:
            self.dashboard.weather=weather;self.dashboard.update()

    def receive_lyrics(self,result):
        track,lines=result
        if track==self.lyrics_worker.track:
            self.dashboard.lyric_track=track;self.dashboard.lyric_lines=lines;self.dashboard.update()

    def activate_hotspot(self,kind,payload):
        if kind=='app':native.activate_on_primary(int(payload))
        else:self.media_worker.request(payload,'toggle' if kind in ('play','pause') else kind)

    def bind_monitor(self,force=False):
        if self.stopping:return
        displays=native.monitors()
        chosen=next((m for m in displays if m['device']==self.settings['monitor']),None)
        if not self.settings['monitor'] and displays:
            chosen=next((m for m in displays if not m['primary']),displays[0])
            self.settings['monitor']=chosen['device']
            save_settings(self.config_path,self.settings)
        if not chosen or not self.user_visible:
            self.dashboard.hide();self.target=chosen;self.hotspots.sync();return
        changed=chosen!=self.target
        self.target=chosen
        hwnd=int(self.dashboard.winId())
        if not native.user32.IsWindow(hwnd):
            old=self.dashboard
            self.dashboard=Dashboard(self.settings,preview=self.args.preview)
            self.dashboard.receive(old.snapshot)
            self.dashboard.receive_media(old.media)
            self.dashboard.weather=old.weather;self.dashboard.lyric_track=old.lyric_track;self.dashboard.lyric_lines=old.lyric_lines
            old.deleteLater()
            hwnd=int(self.dashboard.winId())
            self.host=None
            force=True
        desired_host=native.user32.FindWindowW('Progman',None)
        if self.args.preview:
            if force or changed or not self.dashboard.isVisible():
                screen=next((s for s in self.app.screens() if s.name()==chosen['device']),self.app.primaryScreen())
                self.dashboard.setGeometry(screen.availableGeometry())
                self.dashboard.show()
            return
        try:
            if force or changed or self.host!=desired_host or not self.dashboard.isVisible():
                screen=next((s for s in self.app.screens() if s.name()==chosen['device']),None)
                if screen:self.dashboard.setGeometry(screen.availableGeometry())
                self.dashboard.show()
                self.host=native.attach(hwnd,chosen)
                QTimer.singleShot(200,self.correct_geometry)
            elif self.host:
                if self.dashboard.isMinimized():
                    native.user32.ShowWindow(hwnd,4)
                native.place(hwnd,self.host,chosen)
            self.hotspots.sync()
        except Exception:
            logging.exception('Desktop binding failed')
            self.dashboard.hide();self.host=None

    def correct_geometry(self):
        if self.target and self.host and self.user_visible and not self.stopping:
            native.place(int(self.dashboard.winId()),self.host,self.target)
            self.dashboard.update()
            self.hotspots.sync()

    def toggle(self):
        self.user_visible=not self.user_visible
        self.toggle_action.setText('隐藏监控' if self.user_visible else '显示监控')
        self.bind_monitor(force=True)

    def tray_activated(self,reason):
        if reason==QSystemTrayIcon.ActivationReason.DoubleClick:self.show_settings()

    def show_settings(self):
        if self.dialog and self.dialog.isVisible():
            self.dialog.raise_();self.dialog.activateWindow();return
        self.dialog=SettingsDialog(self);self.dialog.show();self.dialog.raise_();self.dialog.activateWindow()
        geometry=self.app.primaryScreen().availableGeometry()
        self.dialog.move(geometry.center()-self.dialog.rect().center())

    def refresh(self):
        self.worker.reset_requested=True
        self.weather_worker.refresh_requested=True
        self.dashboard.history.clear();self.dashboard.last_received=None
        self.dashboard.snapshot=__import__('telemetry').Snapshot();self.dashboard.update()

    def receive(self,snapshot):
        self.snapshot_count+=1
        self.dashboard.receive(snapshot)
        self.hotspots.sync()
        self.tray.setToolTip(f'GuojamView · CPU {snapshot.cpu:.0f}% · 内存 {snapshot.memory.get("percent",0):.0f}%' if snapshot.cpu is not None else 'GuojamView · 正在采样')
        if self.args.diagnostics:
            record=dict(elapsed=round(time.monotonic()-self.started,3),
                        cpu_percent=self.process.cpu_percent(None)/(psutil.cpu_count() or 1),
                        rss_mb=self.process.memory_info().rss/1024**2,
                        sample_count=self.snapshot_count,system_cpu=snapshot.cpu,
                        memory_percent=snapshot.memory.get('percent'),gpu=snapshot.gpu,
                        paint_ms=self.dashboard.paint_ms[-1] if self.dashboard.paint_ms else None,
                        errors=snapshot.errors)
            self.records.append(record)
            with (Path(self.args.diagnostics)/'samples.jsonl').open('a',encoding='utf-8') as file:
                file.write(json.dumps(record,ensure_ascii=False)+'\n')

    def capture(self):
        if not self.args.diagnostics or not self.target:return
        folder=Path(self.args.diagnostics)
        self.dashboard.grab().save(str(folder/'overlay.png'))
        from PIL import ImageGrab
        x,y,w,h=self.target['rect']
        ImageGrab.grab(bbox=(x,y,x+w,y+h),all_screens=True).save(folder/'desktop.png')
        info=native.window_info(int(self.dashboard.winId()))
        info.update(monitor=self.target,qt_size=[self.dashboard.width(),self.dashboard.height()],dpr=self.dashboard.devicePixelRatioF())
        info['hotspots']={key:native.window_info(int(window.winId())) for key,window in self.hotspots.windows.items()}
        info['cpu_temperature']=self.dashboard.snapshot.cpu_temperature
        info['weather']=__import__('dataclasses').asdict(self.dashboard.weather) if self.dashboard.weather else None
        info['media']={k:getattr(self.dashboard.media,k) for k in ('title','artist','source','position','duration','playing')} if self.dashboard.media else None
        info['lyric_line_count']=len(self.dashboard.lyric_lines)
        (folder/'window.json').write_text(json.dumps(info,indent=2),encoding='utf-8')

    def shutdown(self):
        self.stopping=True
        self.guard.stop();self.clock.stop()
        self.capture()
        self.dashboard.hide();self.tray.hide()
        self.hotspots.close()
        self.worker.requestInterruption();self.worker.wait()
        self.media_worker.requestInterruption();self.media_worker.wait()
        self.weather_worker.requestInterruption();self.lyrics_worker.requestInterruption()
        self.weather_worker.wait();self.lyrics_worker.wait()
        if self.args.diagnostics:
            records=self.records[2:]
            report=dict(version=VERSION,duration_seconds=time.monotonic()-self.started,
                        samples=self.snapshot_count,
                        avg_cpu_percent=statistics.mean(r['cpu_percent'] for r in records) if records else None,
                        peak_rss_mb=max((r['rss_mb'] for r in records),default=None),
                        first_rss_mb=records[0]['rss_mb'] if records else None,
                        final_rss_mb=records[-1]['rss_mb'] if records else None,
                        max_sample_gap=max((b['elapsed']-a['elapsed'] for a,b in zip(self.records,self.records[1:])),default=None),
                        avg_paint_ms=statistics.mean(self.dashboard.paint_ms) if self.dashboard.paint_ms else None,
                        paint_count=self.dashboard.paint_count)
            (Path(self.args.diagnostics)/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description='GuojamView transparent desktop monitor')
    parser.add_argument('--settings',action='store_true')
    parser.add_argument('--preview',action='store_true',help='Standalone interactive QA window')
    parser.add_argument('--diagnostics',help='Opt-in local QA output directory')
    parser.add_argument('--quit-after',type=float,default=0)
    parser.add_argument('--data-dir',type=Path)
    args=parser.parse_args()
    app=QApplication(sys.argv)
    app.setApplicationName('GuojamView');app.setOrganizationName('GuojamView')
    app.setQuitOnLastWindowClosed(False)
    data_dir=args.data_dir or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'GuojamView'
    data_dir.mkdir(parents=True,exist_ok=True)
    handler=RotatingFileHandler(data_dir/'clearview.log',maxBytes=512000,backupCount=2,encoding='utf-8')
    logging.basicConfig(level=logging.INFO,handlers=[handler],format='%(asctime)s %(levelname)s %(message)s')
    def exception_hook(kind,value,tb):
        logging.error('Unhandled error',exc_info=(kind,value,tb))
    sys.excepthook=exception_hook
    server=QLocalServer(app)
    identity='GuojamView.Desktop.'+__import__('hashlib').sha256(str(data_dir.resolve()).encode()).hexdigest()[:16]
    socket=QLocalSocket()
    socket.connectToServer(identity)
    if socket.waitForConnected(300):
        socket.write(b'settings');socket.waitForBytesWritten(500);socket.disconnectFromServer();return 0
    if not server.listen(identity):
        logging.error('Cannot acquire single-instance pipe: %s',server.errorString());return 1
    controller=Controller(app,args,data_dir)
    def incoming():
        connection=server.nextPendingConnection()
        connection.waitForReadyRead(300)
        connection.readAll();connection.disconnectFromServer();connection.deleteLater()
        controller.show_settings()
    server.newConnection.connect(incoming)
    logging.info('GuojamView %s started; desktop=%s',VERSION,controller.target)
    result=app.exec()
    server.close()
    return result


if __name__=='__main__':
    sys.exit(main())
