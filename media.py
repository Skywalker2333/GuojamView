"""Read Windows media sessions without controlling any player or using a server."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time
from queue import SimpleQueue,Empty

from PyQt6.QtCore import QThread, pyqtSignal

LOG=logging.getLogger(__name__)
MAX_COVER_BYTES=4*1024*1024


@dataclass
class MediaSnapshot:
    title: str
    artist: str = ''
    source: str = ''
    position: float = 0
    duration: float = 0
    cover: bytes = b''
    playing: bool = True
    can_previous: bool = True
    can_next: bool = True


def timeline_values(timeline,rate=1.,now=None):
    start=timeline.start_time.total_seconds()
    end=timeline.end_time.total_seconds()
    duration=max(0.,end-start)
    position=timeline.position.total_seconds()-start
    now=now or datetime.now(timezone.utc)
    updated=timeline.last_updated_time
    if updated.tzinfo is None:updated=updated.replace(tzinfo=timezone.utc)
    position+=max(0.,(now-updated).total_seconds())*max(0.,1. if rate is None else rate)
    return max(0.,min(position,duration)) if duration else 0.,duration


def select_playing(manager,playing_status,paused_status=None):
    current=manager.get_current_session()
    sessions=list(manager.get_sessions())
    if current:sessions.insert(0,current)
    playing=[];paused=[]
    for session in sessions:
        try:
            status=session.get_playback_info().playback_status
            if status==playing_status:playing.append(session)
            elif paused_status is not None and status==paused_status:paused.append(session)
        except OSError:continue
    candidates=playing or paused
    return next((s for s in candidates if 'qqmusic' in s.source_app_user_model_id.lower()),next(iter(candidates),None))


async def read_cover(thumbnail):
    if not thumbnail:return b''
    from winrt.windows.storage.streams import InputStreamOptions
    stream=await asyncio.wait_for(thumbnail.open_read_async(),3)
    try:
        size=int(stream.size)
        if size<=0 or size>MAX_COVER_BYTES:return b''
        data=bytearray(size)
        buffer=await asyncio.wait_for(stream.read_async(data,size,InputStreamOptions.NONE),3)
        return bytes(buffer)
    finally:stream.close()


class MediaReader:
    def __init__(self,manager):
        self.manager=manager;self.key=None;self.cover=b'';self.cover_retry=0

    async def sample(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status
        session=select_playing(self.manager,Status.PLAYING,Status.PAUSED)
        if not session:
            self.key=None;self.cover=b''
            return None
        props=await asyncio.wait_for(session.try_get_media_properties_async(),3)
        if not props.title.strip():return None
        source=session.source_app_user_model_id
        key=(source,props.title,props.artist,props.album_title)
        now=time.monotonic()
        if key!=self.key or not self.cover and now-self.cover_retry>10:
            self.cover_retry=now
            try:self.cover=await read_cover(props.thumbnail)
            except (OSError,TimeoutError,RuntimeError):self.cover=b''
            self.key=key
        timeline=session.get_timeline_properties()
        info=session.get_playback_info()
        # The player may have paused/closed during the async metadata request.
        if info.playback_status not in (Status.PLAYING,Status.PAUSED):return None
        playing=info.playback_status==Status.PLAYING
        position,duration=timeline_values(timeline,info.playback_rate if playing else 0.)
        controls=info.controls
        return MediaSnapshot(props.title.strip(),props.artist.strip(),source,position,duration,self.cover,
                             playing,controls.is_previous_enabled,controls.is_next_enabled)


class MediaThread(QThread):
    changed=pyqtSignal(object)
    action_failed=pyqtSignal(str)

    def __init__(self):
        super().__init__();self.commands=SimpleQueue()

    def request(self,source,action):
        if action in ('toggle','previous','next'):self.commands.put((source,action))

    async def command(self,manager,source,action):
        session=next((s for s in manager.get_sessions() if s.source_app_user_model_id==source),None)
        if session is None:return
        method={'toggle':session.try_toggle_play_pause_async,'previous':session.try_skip_previous_async,'next':session.try_skip_next_async}[action]
        if not await asyncio.wait_for(method(),3):self.action_failed.emit('当前播放器未接受此操作')

    def run(self):
        asyncio.run(self.poll())

    async def poll(self):
        reader=None
        last_error=None
        while not self.isInterruptionRequested():
            try:
                if reader is None:
                    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
                    manager=await asyncio.wait_for(Manager.request_async(),5)
                    reader=MediaReader(manager)
                while not self.commands.empty():
                    source,action=self.commands.get_nowait()
                    await self.command(reader.manager,source,action)
                self.changed.emit(await reader.sample())
                last_error=None
            except Exception as exc:
                if str(exc)!=last_error:LOG.info('Media session temporarily unavailable: %s',exc)
                last_error=str(exc);self.changed.emit(None);reader=None
            # Metadata remains in memory only. Polling is also a reconnect path.
            for _ in range(10 if reader else 50):
                if self.isInterruptionRequested():break
                await asyncio.sleep(.1)
