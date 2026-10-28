"""Use existing hardware-monitor WMI providers; never invent a CPU temperature."""
import math


def cpu_temperature(rows):
    values=[];package=[]
    for row in rows:
        if str(row.get('SensorType','')).lower()!='temperature':continue
        identity=(str(row.get('Identifier',''))+' '+str(row.get('Parent',''))).lower()
        if 'cpu' not in identity:continue
        try:value=float(row['Value'])
        except (TypeError,ValueError,KeyError):continue
        if not math.isfinite(value) or not -30<=value<=140:continue
        values.append(value)
        if any(s in str(row.get('Name','')).lower() for s in ('package','tctl','tdie')):package.append(value)
    return max(package or values) if package or values else None


class CpuSensor:
    def __init__(self):
        self.connection=None;self.last_try=-60.;self.last_poll=-10.;self.value=None
        self.com=None

    def sample(self,now):
        if now-self.last_poll<5:return self.value
        self.last_poll=now
        if self.connection is None and now-self.last_try>=30:
            self.last_try=now
            try:
                import pythoncom
                import win32com.client
                if self.com is None:pythoncom.CoInitialize();self.com=pythoncom
                locator=win32com.client.Dispatch('WbemScripting.SWbemLocator')
                for namespace in (r'root\LibreHardwareMonitor',r'root\OpenHardwareMonitor'):
                    try:self.connection=locator.ConnectServer('.',namespace);break
                    except pythoncom.com_error:continue
            except (ImportError,OSError):pass
        if self.connection is not None:
            try:
                rows=[]
                for sensor in self.connection.ExecQuery("SELECT Identifier,Parent,Name,Value,SensorType FROM Sensor WHERE SensorType='Temperature'"):
                    rows.append({k:getattr(sensor,k,None) for k in ('Identifier','Parent','Name','Value','SensorType')})
                self.value=cpu_temperature(rows)
            except Exception:self.connection=None;self.value=None
        return self.value

    def close(self):
        self.connection=None
        if self.com:self.com.CoUninitialize();self.com=None
