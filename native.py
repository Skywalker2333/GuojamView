"""Small Windows desktop bridge. Only our own HWND is changed."""
import ctypes as C
from ctypes import wintypes as W

user32 = C.WinDLL('user32', use_last_error=True)
user32.GetParent.argtypes = [W.HWND]
user32.GetParent.restype = W.HWND
user32.GetWindowLongPtrW.argtypes = [W.HWND, C.c_int]
user32.GetWindowLongPtrW.restype = C.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [W.HWND, C.c_int, C.c_ssize_t]
user32.SetWindowLongPtrW.restype = C.c_ssize_t
user32.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT]
user32.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
user32.FindWindowW.restype = W.HWND
user32.FindWindowExW.argtypes = [W.HWND, W.HWND, W.LPCWSTR, W.LPCWSTR]
user32.FindWindowExW.restype = W.HWND
user32.GetWindow.argtypes = [W.HWND, W.UINT]
user32.GetWindow.restype = W.HWND
user32.GetForegroundWindow.restype = W.HWND
user32.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
CALLBACK = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


def dpi_awareness():
    user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))


def class_name(hwnd):
    text = C.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, text, 256)
    return text.value



class MONITORINFOEX(C.Structure):
    _fields_ = [('cbSize', W.DWORD), ('rcMonitor', W.RECT), ('rcWork', W.RECT),
                ('dwFlags', W.DWORD), ('szDevice', W.WCHAR * 32)]


def monitors():
    result = []
    cb_type = C.WINFUNCTYPE(W.BOOL, W.HMONITOR, W.HDC, C.POINTER(W.RECT), W.LPARAM)

    @cb_type
    def visit(handle, dc, rect, param):
        info = MONITORINFOEX()
        info.cbSize = C.sizeof(info)
        user32.GetMonitorInfoW(handle, C.byref(info))
        def values(r):
            return (r.left, r.top, r.right - r.left, r.bottom - r.top)
        result.append(dict(device=info.szDevice, primary=bool(info.dwFlags & 1),
                           rect=values(info.rcMonitor), work=values(info.rcWork)))
        return True

    user32.EnumDisplayMonitors(None, None, visit, 0)
    return result


def attach(hwnd, monitor, click_through=True):
    host = user32.FindWindowW('Progman', None)
    if not host:
        raise RuntimeError('未找到 Windows 桌面，请稍后重试。')
    style = user32.GetWindowLongPtrW(hwnd, -16)
    user32.SetWindowLongPtrW(hwnd, -16, (style & ~0x40000000) | 0x80000000)
    ex = user32.GetWindowLongPtrW(hwnd, -20)
    ex = ex | 0x80000 | 0x80 | 0x08000000
    ex = ex | 0x20 if click_through else ex & ~0x20
    user32.SetWindowLongPtrW(hwnd, -20, ex)
    # Desktop ownership preserves a top-level layered surface. Cross-process
    # SetParent resets DPI and hides Qt's layered surface on current Win11.
    user32.SetWindowLongPtrW(hwnd, -8, host)
    place(hwnd, host, monitor)
    return host


def place(hwnd, host, monitor):
    x, y, width, height = monitor['work']
    # Owned popup stays above its desktop owner, below ordinary applications.
    user32.SetWindowPos(hwnd, W.HWND(1), x, y, width, height, 0x10 | 0x40)


def window_info(hwnd):
    rect = W.RECT()
    user32.GetWindowRect(hwnd, C.byref(rect))
    return dict(hwnd=int(hwnd), parent=user32.GetParent(hwnd),
                rect=[rect.left, rect.top, rect.right, rect.bottom],
                dpi=user32.GetDpiForWindow(hwnd),
                ex_style=user32.GetWindowLongPtrW(hwnd, -20),
                visible=bool(user32.IsWindowVisible(hwnd)))


def open_apps():
    foreground = user32.GetForegroundWindow()
    foreground_pid = W.DWORD()
    user32.GetWindowThreadProcessId(foreground, C.byref(foreground_pid))
    result = {}
    screens = [m['rect'] for m in monitors()]
    dwm = C.WinDLL('dwmapi')
    dwm.DwmGetWindowAttribute.argtypes = [W.HWND, W.DWORD, C.c_void_p, W.DWORD]

    @CALLBACK
    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):
            return True
        ex = user32.GetWindowLongPtrW(hwnd, -20)
        if ex & 0x80 or class_name(hwnd) in ('Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'):
            return True
        title = C.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        if not title.value:
            return True
        rect = W.RECT()
        user32.GetWindowRect(hwnd, C.byref(rect))
        if not user32.IsIconic(hwnd) and not any(
            rect.right > x and rect.left < x+width and rect.bottom > y and rect.top < y+height
            for x,y,width,height in screens):
            return True
        cloaked = W.DWORD()
        dwm.DwmGetWindowAttribute(hwnd, 14, C.byref(cloaked), C.sizeof(cloaked))
        if cloaked.value:
            return True
        pid = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
        if pid.value:
            if pid.value not in result:
                result[pid.value] = dict(pid=pid.value, hwnd=int(hwnd),foreground=pid.value==foreground_pid.value)
        return True

    user32.EnumWindows(visit, 0)
    return list(result.values())


def activate_on_primary(hwnd):
    """A user click restores an existing application and brings it to the main display."""
    if not user32.IsWindow(hwnd):return False
    displays=monitors();main=next((m for m in displays if m['primary']),None)
    if not main:return False
    x,y,width,height=main['work']
    maximized=bool(user32.IsZoomed(hwnd))
    if user32.IsIconic(hwnd) or maximized:user32.ShowWindow(hwnd,9)
    rect=W.RECT();user32.GetWindowRect(hwnd,C.byref(rect))
    w=min(max(300,rect.right-rect.left),width)
    h=min(max(200,rect.bottom-rect.top),height)
    user32.SetWindowPos(hwnd,None,x+(width-w)//2,y+(height-h)//2,w,h,0x10|0x4)
    if maximized:user32.ShowWindow(hwnd,3)
    user32.SetForegroundWindow.argtypes=[W.HWND]
    return bool(user32.SetForegroundWindow(hwnd))


