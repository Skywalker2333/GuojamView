"""Local CPU, RAM, NVIDIA telemetry and open-application process families."""
import logging
import os
from pathlib import Path
import time
import warnings
from dataclasses import dataclass, field

import psutil
from PyQt6.QtCore import QThread, pyqtSignal
from native import open_apps
from sensors import CpuSensor

LOG=logging.getLogger(__name__)


@dataclass
class Snapshot:
    timestamp: float = 0
    cpu: float | None = None
    cpu_detail: str = ''
    cpu_temperature: float | None = None
    memory: dict = field(default_factory=dict)
    gpu: dict = field(default_factory=dict)
    processes: list = field(default_factory=list)
    errors: list = field(default_factory=list)


class Sampler:
    def __init__(self):
        self.last_time=None;self.last_apps=-10.;self.apps=[];self.app_processes={}
        self.nvml=None;self.gpu_handle=None;self.last_gpu_retry=-30.
        physical=psutil.cpu_count(logical=False)
        logical=psutil.cpu_count()
        self.cpu_detail=f'{physical} 核 / {logical} 线程' if physical else f'{logical or "—"} 线程'
        self.sensor=CpuSensor()
        psutil.cpu_percent(None)

    def gpu_sample(self,now):
        if not self.nvml and now-self.last_gpu_retry>=30:
            self.last_gpu_retry=now
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    import pynvml
                pynvml.nvmlInit();self.nvml=pynvml
                self.gpu_handle=pynvml.nvmlDeviceGetHandleByIndex(0)
            except Exception as exc:
                LOG.info('NVML unavailable: %s',exc);self.nvml=None
        if not self.nvml:return {}
        n,h=self.nvml,self.gpu_handle
        def read(fn,*args):
            try:return fn(h,*args)
            except n.NVMLError:return None
        name=read(n.nvmlDeviceGetName);util=read(n.nvmlDeviceGetUtilizationRates)
        mem=read(n.nvmlDeviceGetMemoryInfo)
        if name is None:
            try:n.nvmlShutdown()
            except n.NVMLError:pass
            self.nvml=None
        return dict(name=name.decode() if isinstance(name,bytes) else name,
                    load=util.gpu if util else None,used=mem.used if mem else None,
                    total=mem.total if mem else None,
                    temperature=read(n.nvmlDeviceGetTemperature,0))

    def application_sample(self):
        rows=[];keep={};logical=psutil.cpu_count() or 1
        known={'chrome':'Google Chrome','msedge':'Microsoft Edge','codex':'Codex',
               'qq':'QQ','code':'Visual Studio Code','explorer':'文件资源管理器',
               'notepad':'记事本','taskmgr':'任务管理器','wallpaperui':'Wallpaper Engine',
               'steamwebhelper':'Steam','steam':'Steam'}
        for window in open_apps():
            if window['pid']==os.getpid():continue
            try:
                root=psutil.Process(window['pid']);exe=root.exe();name=Path(exe).stem
                # Explorer owns unrelated launched programs; those are separate apps.
                family=[root] if name.lower()=='explorer' else [root]+root.children(recursive=True)
                cpu=0.;memory=0;primed=False
                for process in family:
                    try:
                        identity=(process.pid,process.create_time())
                        old=self.app_processes.get(identity)
                        process=old if old is not None else process
                        value=process.cpu_percent(None)
                        if old is not None:cpu+=value;primed=True
                        memory+=process.memory_info().rss
                        keep[identity]=process
                    except (psutil.NoSuchProcess,psutil.AccessDenied,OSError):continue
                rows.append(dict(pid=root.pid,name=known.get(name.lower(),name),exe=exe,
                                 hwnd=window.get('hwnd'),
                                 foreground=window['foreground'],cpu=min(100.,cpu/logical) if primed else None,
                                 memory=memory))
            except (psutil.NoSuchProcess,psutil.AccessDenied,OSError):continue
        self.app_processes=keep
        return rows

    def sample(self,now=None):
        now=time.monotonic() if now is None else now
        elapsed=now-self.last_time if self.last_time is not None else 0
        raw_cpu=psutil.cpu_percent(None)
        s=Snapshot(timestamp=time.time(),cpu=raw_cpu if 0<elapsed<=5 else None,cpu_detail=self.cpu_detail)
        s.cpu_temperature=self.sensor.sample(now)
        if elapsed>5:self.reset()
        try:s.memory=psutil.virtual_memory()._asdict()
        except OSError:s.errors.append('内存')
        try:s.gpu=self.gpu_sample(now)
        except Exception as exc:LOG.debug('GPU: %s',exc);s.errors.append('GPU')
        if now-self.last_apps>=2:
            self.apps=self.application_sample();self.last_apps=now
        s.processes=self.apps
        self.last_time=now
        return s

    def reset(self):
        self.last_time=None;self.last_apps=-10.;self.app_processes={}
        psutil.cpu_percent(None)

    def close(self):
        self.sensor.close()
        if self.nvml:
            try:self.nvml.nvmlShutdown()
            except self.nvml.NVMLError:pass


class SamplingThread(QThread):
    sampled=pyqtSignal(object)
    failed=pyqtSignal(str)

    def __init__(self):
        super().__init__();self.reset_requested=False

    def run(self):
        sampler=None
        try:
            sampler=Sampler()
            while not self.isInterruptionRequested():
                start=time.monotonic()
                try:
                    if self.reset_requested:sampler.reset();self.reset_requested=False
                    self.sampled.emit(sampler.sample())
                except Exception:
                    LOG.exception('Sampling failed');self.failed.emit('采集暂时不可用，正在重试');sampler.reset()
                while time.monotonic()-start<1 and not self.isInterruptionRequested():self.msleep(50)
        except Exception:
            LOG.exception('Sampler initialization failed');self.failed.emit('采集初始化失败，请检查日志')
        finally:
            if sampler:sampler.close()
