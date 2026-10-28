"""Fetch matching timed lyrics with bounded network waits and short negative caching."""
import base64
from bisect import bisect_right
import html
import json
import re
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from PyQt6.QtCore import QThread, pyqtSignal


def normalized(value):
    return re.sub(r'[^\w]', '', value).casefold()


def parse_lrc(text):
    offset = 0
    lines = []
    match = re.search(r'\[offset:([+-]?\d+)\]', text, re.I)
    if match:
        offset = int(match.group(1)) / 1000
    for line in text.splitlines():
        stamps = list(re.finditer(r'\[(\d{1,3}):(\d{2}(?:\.\d+)?)\]', line))
        if not stamps:
            continue
        words = html.unescape(line[stamps[-1].end():]).strip()
        for stamp in stamps:
            lines.append((max(0, int(stamp[1]) * 60 + float(stamp[2]) + offset), words))
    return sorted(lines, key=lambda row: row[0])


def lyric_at(lines, position):
    index = bisect_right([row[0] for row in lines], position) - 1
    return lines[index][1] if index >= 0 else ''


def fetch_json(url, timeout=2.5):
    request = Request(url, headers={'Referer': 'https://y.qq.com/', 'User-Agent': 'Mozilla/5.0 GuojamView/1.2'})
    with urlopen(request, timeout=timeout) as response:
        data = response.read(512001)
    if len(data) > 512000:
        raise ValueError('Lyrics response too large')
    return json.loads(data)


def _song_match(song, title, artist, duration, title_key, artist_key):
    if normalized(song.get('name', song.get('songname', ''))) != title_key:
        return False
    singers = song.get('singer', [])
    if isinstance(singers, str):
        singers = [singers]
    elif isinstance(singers, dict):
        singers = [singers.get('name', '')]
    else:
        singers = [s.get('name', '') if isinstance(s, dict) else str(s) for s in singers]
    if artist_key not in [normalized(singer) for singer in singers]:
        return False
    interval = song.get('interval', song.get('duration'))
    if interval and duration:
        try:
            if abs(float(interval) - duration) > 5:
                return False
        except (TypeError, ValueError):
            pass
    return True


def _get_qq_lyric(mid):
    data = fetch_json('https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?' + urlencode(dict(songmid=mid, format='json', nobase64=1)))
    text = data.get('lyric', '')
    if text and not text.startswith('['):
        try:
            text = base64.b64decode(text).decode('utf-8')
        except (ValueError, UnicodeError):
            text = ''
    return parse_lrc(text)


def fetch_lyrics(title, artist, duration):
    """Try QQ's low-latency suggest API, then legacy search and LRCLIB."""
    title_key = normalized(title)
    artist_key = normalized(artist)
    # SmartBox usually answers in well under a second and supports Chinese titles
    # that frequently fail in the old search endpoint.
    try:
        data = fetch_json('https://c.y.qq.com/splcloud/fcgi-bin/smartbox_new.fcg?' + urlencode(dict(key=title, format='json')))
        songs = data.get('data', {}).get(' เพลง', [])
        if not songs:
            songs = data.get('data', {}).get('song', {}).get('itemlist', [])
        for song in songs:
            if _song_match(song, title, artist, duration, title_key, artist_key):
                mid = song.get('mid') or song.get('songmid')
                if mid:
                    lines = _get_qq_lyric(mid)
                    if lines:
                        return lines
    except (OSError, ValueError, TypeError, KeyError):
        pass
    # Keep the slower legacy route bounded, and only try it if SmartBox found no match.
    try:
        data = fetch_json('https://c.y.qq.com/soso/fcgi-bin/client_search_cp?' + urlencode(dict(w=f'{title} {artist}', p=1, n=8, format='json')), timeout=1.8)
        songs = data.get('data', {}).get('song', {}).get('list', [])
        for song in songs:
            if _song_match(song, title, artist, duration, title_key, artist_key):
                mid = song.get('songmid')
                if mid:
                    lines = _get_qq_lyric(mid)
                    if lines:
                        return lines
    except (OSError, ValueError, TypeError, KeyError):
        pass
    try:
        data = fetch_json('https://lrclib.net/api/get?' + urlencode(dict(track_name=title, artist_name=artist, duration=round(duration))), timeout=1.8)
        if normalized(data.get('trackName', '')) == title_key and normalized(data.get('artistName', '')) == artist_key:
            return parse_lrc(data.get('syncedLyrics') or '')
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return []


class LyricsThread(QThread):
    changed = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.track = None
        self.enabled = True

    def run(self):
        # Cache successful results for this session; retry misses after 8 seconds.
        cache = {}
        last = None
        while not self.isInterruptionRequested():
            track = self.track if self.enabled else None
            if track != last:
                last = track
                if not track:
                    self.changed.emit((None, []))
                elif track in cache and cache[track][0]:
                    self.changed.emit((track, cache[track][1]))
                elif track not in cache or time.monotonic() - cache[track][2] >= 8:
                    lines = fetch_lyrics(*track)
                    cache[track] = (bool(lines), lines, time.monotonic())
                    if len(cache) > 24:
                        cache.pop(next(iter(cache)))
                    if track == self.track and self.enabled:
                        self.changed.emit((track, lines))
            self.msleep(200)

