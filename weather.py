"""City-level Open-Meteo current weather; never requests device location."""
from dataclasses import dataclass
import json
import logging
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from pypinyin import lazy_pinyin
from PyQt6.QtCore import QThread,pyqtSignal

LOG=logging.getLogger(__name__)


def get_json(url,timeout=6):
    request=Request(url,headers={'User-Agent':'GuojamView/1.2 (personal desktop widget)'})
    with urlopen(request,timeout=timeout) as response:
        payload=response.read(512001)
    if len(payload)>512000:raise ValueError('Response too large')
    return json.loads(payload)


def resolve_city(city):
    queries=[city]
    if any('\u4e00'<=c<='\u9fff' for c in city):
        queries.append(''.join(lazy_pinyin(city.removesuffix('市'))))
    for query in queries:
        try:data=get_json('https://geocoding-api.open-meteo.com/v1/search?'+urlencode(dict(name=query,count=5,language='zh',format='json')))
        except OSError:continue
        rows=[r for r in data.get('results',[]) if r.get('feature_code','').startswith('PPL')]
        if rows:
            row=max(rows,key=lambda r:r.get('population',0))
            return row
    raise ValueError('未找到城市，可使用城市名或拼音')


def condition(code):
    if code==0:return '晴'
    if code in (1,2):return '多云'
    if code==3:return '阴'
    if code in (45,48):return '雾'
    if code in (51,53,55,56,57):return '毛毛雨'
    if code in (61,63,65,66,67,80,81,82):return '雨'
    if code in (71,73,75,77,85,86):return '雪'
    if code in (95,96,99):return '雷雨'
    return '天气'


@dataclass
class WeatherSnapshot:
    city: str
    temperature: float | None = None
    code: int = -1
    is_day: bool = True
    updated: float = 0
    error: str = ''
    region: str = ''
    description: str = ''
    source: str = '腾讯天气'


def tencent_weather(city,locations):
    if city not in locations or 'province' not in locations[city]:
        result=get_json('https://wis.qq.com/city/like?'+urlencode(dict(source='pc',city=city)))
        choices=list((result.get('data') or {}).values())
        parsed=[tuple(p.strip() for p in row.split(',')) for row in choices if isinstance(row,str)]
        exact=[r for r in parsed if len(r)>=2 and city.removesuffix('市') in (r[1],r[-1])]
        location=next(iter(exact or parsed),None)
        if not location or len(location)<2:raise ValueError('未找到城市')
        locations[city]=dict(province=location[0],city=location[1],district=location[2] if len(location)>2 else '')
    location=locations[city]
    result=get_json('https://wis.qq.com/weather/common?'+urlencode(dict(source='pc',weather_type='observe',province=location['province'],city=location['city'],county=location.get('district',''))))
    current=result['data']['observe'];temperature=float(current['degree'])
    if not -100<=temperature<=70:raise ValueError('Invalid temperature')
    raw=int(current['weather_code'])
    code={0:0,1:2,2:3,3:80,4:95,5:96,6:71,7:61,8:63,9:65,10:65,11:65,12:65,13:85,14:71,15:73,16:75,17:75,18:45,19:66,20:45,21:61,22:63,23:65,24:65,25:65,26:71,27:73,28:75,29:45,30:45,31:45,53:45}.get(raw,3)
    night='/heiye/' in (current.get('weather_url','')+current.get('weather_bg_pag',''))
    return WeatherSnapshot(city,temperature,code,not night,time.time(),region=location['province'],description=current.get('weather_short') or current.get('weather') or condition(code))


class WeatherThread(QThread):
    changed=pyqtSignal(object)

    def __init__(self,city):
        super().__init__();self.city=city;self.enabled=True;self.refresh_requested=False

    def run(self):
        locations={}
        last_city=None;next_fetch=0;last=None
        while not self.isInterruptionRequested():
            city=self.city.strip()[:80]
            if city!=last_city:
                self.changed.emit(WeatherSnapshot(city));last=None;next_fetch=0;last_city=city
            if self.enabled and city and (time.monotonic()>=next_fetch or self.refresh_requested):
                self.refresh_requested=False
                try:
                    if len(locations)>8:locations.clear()
                    try:last=tencent_weather(city,locations)
                    except (OSError,ValueError,KeyError,TypeError):
                        location=resolve_city(city)
                        data=get_json('https://api.open-meteo.com/v1/forecast?'+urlencode(dict(
                            latitude=location['latitude'],longitude=location['longitude'],
                            current='temperature_2m,weather_code,is_day',timezone='auto',forecast_days=1)))
                        current=data['current'];temperature=float(current['temperature_2m'])
                        if not -100<=temperature<=70:raise ValueError('Invalid temperature')
                        last=WeatherSnapshot(city,temperature,int(current['weather_code']),bool(current['is_day']),time.time(),region=location.get('admin1',''),source='Open-Meteo')
                    if city==self.city.strip():self.changed.emit(last)
                    next_fetch=time.monotonic()+600
                except Exception as exc:
                    LOG.info('Weather unavailable for %s: %s',city,exc)
                    if city==self.city.strip():
                        if last and time.time()-last.updated<3600:last.error='更新暂不可用';self.changed.emit(last)
                        else:self.changed.emit(WeatherSnapshot(city,error='天气暂不可用'))
                    next_fetch=time.monotonic()+60
            self.msleep(200)
