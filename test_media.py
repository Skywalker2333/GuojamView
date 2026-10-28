"""Read-only media logic tests; no player controls or real audio are touched."""
import asyncio
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import Mock,patch

from media import timeline_values,select_playing,MediaReader


class MediaTests(unittest.TestCase):
    def test_progress_uses_windows_timestamp_and_clamps(self):
        now=datetime.now(timezone.utc)
        t=Obj(start_time=timedelta(seconds=10),end_time=timedelta(seconds=110),
              position=timedelta(seconds=40),last_updated_time=now-timedelta(seconds=3))
        self.assertEqual(timeline_values(t,1.,now),(33.,100.))
        self.assertEqual(timeline_values(t,1.,now+timedelta(hours=2)),(100.,100.))
        t.end_time=t.start_time
        self.assertEqual(timeline_values(t,1.,now),(0.,0.))

    def test_current_playing_session_wins(self):
        paused=Mock();paused.get_playback_info.return_value=Obj(playback_status=5)
        playing=Mock();playing.get_playback_info.return_value=Obj(playback_status=4)
        playing.source_app_user_model_id='Chrome'
        manager=Mock();manager.get_current_session.return_value=paused;manager.get_sessions.return_value=[paused,playing]
        self.assertIs(select_playing(manager,4),playing)
        manager.get_current_session.return_value=playing
        self.assertIs(select_playing(manager,4),playing)

    def test_qq_music_preferred_over_browser(self):
        browser=Mock(source_app_user_model_id='Chrome');browser.get_playback_info.return_value=Obj(playback_status=4)
        qq=Mock(source_app_user_model_id='QQMusic.exe');qq.get_playback_info.return_value=Obj(playback_status=4)
        manager=Mock();manager.get_current_session.return_value=browser;manager.get_sessions.return_value=[browser,qq]
        self.assertIs(select_playing(manager,4),qq)
        qq.get_playback_info.return_value=Obj(playback_status=5)
        self.assertIs(select_playing(manager,4),browser)

    def test_no_playback_clears_previous_artwork(self):
        manager=Mock();manager.get_current_session.return_value=None;manager.get_sessions.return_value=[]
        reader=MediaReader(manager);reader.cover=b'old-art';reader.key=('old',)
        self.assertIsNone(asyncio.run(reader.sample()))
        self.assertEqual(reader.cover,b'')
        self.assertIsNone(reader.key)


if __name__=='__main__':unittest.main(verbosity=2)
