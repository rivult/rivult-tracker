"""System-tray icon (design P13) — the app hides here instead of closing.

Windows-only, stdlib + ctypes ONLY (no pystray: it drags in Pillow, which
breaks the zero-runtime-dependency rule). A message-only window on its own
thread owns the icon and pumps a blocking ``GetMessageW`` loop — the same
proven shape as ``keybind.py`` and ``inputrec.py``.

The event-translation logic (``on_tray_event`` / ``on_command``) is kept free
of ctypes so it can be unit-tested headless; only ``run`` touches win32. A real
tray CLICK can't be synthesized under the test harness (UIPI blocks injected
input), same caveat as the hotkeys — but everything up to "the OS delivered the
message" is exercised.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, Optional

# -- constants (public so tests can reference them without importing ctypes) --
WM_APP = 0x8000
TRAY_CALLBACK = WM_APP + 1        # our private icon-callback message
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203
WM_COMMAND = 0x0111
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_NULL = 0x0000

# menu item ids
ID_OPEN = 1001
ID_EXIT = 1002

# Adding the icon can fail while the shell is busy — retry before giving up.
ICON_ADD_ATTEMPTS = 5
ICON_ADD_RETRY_S = 0.4
# Cold-starting a frozen build is slower than running from source; 5s was
# tight enough that a timeout returned a tray which had never come up.
TRAY_START_TIMEOUT_S = 15.0

# Shell_NotifyIcon
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10
NIIF_NONE = 0x00

# menu / misc
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
TPM_RIGHTBUTTON = 0x0002
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
IDI_APPLICATION = 32512

_TIP_MAX = 127          # szTip is WCHAR[128] incl. the NUL
_INFO_MAX = 255
_TITLE_MAX = 63


class Tray:
    """A tray icon with an "Open" / "Exit" menu.

    ``on_show`` fires on left-click or the Open menu item; ``on_exit`` on the
    Exit item. Both are invoked on the tray thread — the caller is responsible
    for marshalling to any GUI thread (see app.py).
    """

    def __init__(self, on_show: Callable[[], None], on_exit: Callable[[], None],
                 icon_path: Optional[str] = None,
                 tooltip: str = "Rivult Tracker"):
        self._on_show = on_show
        self._on_exit = on_exit
        self.icon_path = icon_path
        self.tooltip = tooltip[:_TIP_MAX]
        self._hwnd: Optional[int] = None
        self._wndproc = None            # keep the CFUNCTYPE alive (GC guard)
        self._taskbar_created = 0       # RegisterWindowMessage("TaskbarCreated")
        self.started = threading.Event()
        self.error: Optional[str] = None

    # -- testable event translation (no ctypes) ----------------------------
    def on_tray_event(self, mouse_msg: int) -> Optional[str]:
        """The icon posted a mouse event. Returns the action taken (or None)."""
        if mouse_msg in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
            self._safe(self._on_show)
            return "show"
        if mouse_msg == WM_RBUTTONUP:
            return "menu"                # the win32 layer opens the popup
        return None

    def on_command(self, menu_id: int) -> Optional[str]:
        """A menu item was chosen. Returns the action taken (or None)."""
        if menu_id == ID_OPEN:
            self._safe(self._on_show)
            return "show"
        if menu_id == ID_EXIT:
            self._safe(self._on_exit)
            return "exit"
        return None

    @staticmethod
    def _safe(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            pass          # a callback must never kill the tray pump

    # -- win32 lifecycle ---------------------------------------------------
    def run(self) -> None:
        """Create the icon and pump messages. Call on a dedicated thread."""
        if sys.platform != "win32":
            self.error = "system tray is Windows-only"
            self.started.set()
            return
        try:
            self._run_win32()
        except Exception as e:          # never let a tray failure crash the app
            self.error = str(e)
            self.started.set()

    def _run_win32(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        shell32 = ctypes.windll.shell32

        # Pointer-sized types. Without explicit prototypes ctypes assumes c_int
        # (32-bit) for every arg/return, which TRUNCATES 64-bit HWNDs and
        # OVERFLOWS a 64-bit lParam — the classic ctypes-on-win64 trap.
        HWND = ctypes.c_void_p
        WPARAM = ctypes.c_size_t
        LPARAM = ctypes.c_ssize_t
        LRESULT = ctypes.c_ssize_t

        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, wintypes.UINT, WPARAM, LPARAM)

        for fn, restype in (
            (user32.DefWindowProcW, LRESULT),
            (user32.CreateWindowExW, HWND),
            (user32.LoadImageW, HWND),
            (user32.LoadIconW, HWND),
            (user32.CreatePopupMenu, HWND),
            (kernel32.GetModuleHandleW, HWND),
        ):
            fn.restype = restype
        user32.DefWindowProcW.argtypes = [HWND, wintypes.UINT, WPARAM, LPARAM]
        user32.DispatchMessageW.restype = LRESULT
        user32.PostMessageW.argtypes = [HWND, wintypes.UINT, WPARAM, LPARAM]
        # every handle arg must be pointer-sized or a 64-bit HINSTANCE/parent
        # overflows the inferred c_int (arg 11 = hInstance is the one that bit).
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            HWND, HWND, HWND, ctypes.c_void_p]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        user32.LoadImageW.argtypes = [
            HWND, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
            wintypes.UINT]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == TRAY_CALLBACK:
                # the mouse event is the low word of lParam
                action = self.on_tray_event(lparam & 0xFFFF)
                if action == "menu":
                    self._show_menu(user32, hwnd)
                return 0
            if msg == WM_COMMAND:
                self.on_command(wparam & 0xFFFF)
                return 0
            if msg == self._taskbar_created:
                # Explorer restarted — re-add or the icon is gone for good
                self._add_or_modify(NIM_ADD)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(wndproc)     # MUST stay referenced

        hinst = kernel32.GetModuleHandleW(None)
        cls = WNDCLASS()
        cls.lpfnWndProc = self._wndproc
        cls.hInstance = hinst
        cls.lpszClassName = "RivultTrayWindow"
        atom = user32.RegisterClassW(ctypes.byref(cls))
        if not atom:
            raise ctypes.WinError()

        # HWND_MESSAGE (-3) => message-only window: no taskbar, minimal cost
        HWND_MESSAGE = wintypes.HWND(-3)
        self._hwnd = user32.CreateWindowExW(
            0, "RivultTrayWindow", "Rivult", 0, 0, 0, 0, 0,
            HWND_MESSAGE, None, hinst, None)
        if not self._hwnd:
            raise ctypes.WinError()

        self._icon_handle = self._load_icon(user32)
        # Shell_NotifyIcon fails transiently while Explorer is busy (notably
        # just after login or an Explorer restart). Ignoring the result meant
        # we reported a working tray with no icon: closing then hid the window
        # with nothing left to bring it back, and the app looked like it had
        # vanished. Retry, then admit failure so the caller keeps X = quit.
        import time as _time
        for attempt in range(ICON_ADD_ATTEMPTS):
            if self._add_or_modify(NIM_ADD):
                break
            if attempt < ICON_ADD_ATTEMPTS - 1:
                _time.sleep(ICON_ADD_RETRY_S)
        else:
            self.error = "Shell_NotifyIcon refused to add the tray icon"
            self.started.set()
            return
        self.started.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # loop ended (WM_QUIT) — make sure the icon is gone
        self._remove_icon()

    def _load_icon(self, user32):
        import ctypes
        import os
        if self.icon_path and os.path.isfile(self.icon_path):
            h = user32.LoadImageW(
                None, self.icon_path, IMAGE_ICON, 0, 0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                return h
        # fall back to the generic application icon so we always show something
        return user32.LoadIconW(None, ctypes.c_wchar_p(IDI_APPLICATION))

    def _notify_struct(self, flags: int, info: str = "", title: str = ""):
        import ctypes
        from ctypes import wintypes

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", ctypes.c_wchar * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", ctypes.c_wchar * 256),
                ("uVersion", wintypes.UINT),
                ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", wintypes.DWORD),
            ]

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = TRAY_CALLBACK
        nid.hIcon = getattr(self, "_icon_handle", 0)
        nid.szTip = self.tooltip
        if flags & NIF_INFO:
            nid.szInfo = info[:_INFO_MAX]
            nid.szInfoTitle = title[:_TITLE_MAX]
            nid.dwInfoFlags = NIIF_NONE
        return nid

    def _add_or_modify(self, op: int) -> bool:
        import ctypes
        nid = self._notify_struct(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        return bool(ctypes.windll.shell32.Shell_NotifyIconW(op, ctypes.byref(nid)))

    def _remove_icon(self) -> None:
        import ctypes
        try:
            nid = self._notify_struct(0)
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        except Exception:
            pass

    def _show_menu(self, user32, hwnd) -> None:
        import ctypes
        from ctypes import wintypes
        hmenu = user32.CreatePopupMenu()
        user32.AppendMenuW(hmenu, MF_STRING, ID_OPEN, "Open Rivult")
        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(hmenu, MF_STRING, ID_EXIT, "Exit")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        # required or the menu won't dismiss when you click elsewhere
        user32.SetForegroundWindow(hwnd)
        user32.TrackPopupMenu(hmenu, TPM_RIGHTBUTTON, pt.x, pt.y, 0, hwnd, None)
        user32.PostMessageW(hwnd, WM_NULL, 0, 0)   # MSDN post-TrackPopupMenu fix
        user32.DestroyMenu(hmenu)

    def notify(self, title: str, text: str) -> None:
        """Show a balloon. No-op before the icon exists or off-Windows."""
        if sys.platform != "win32" or self._hwnd is None:
            return
        try:
            import ctypes
            nid = self._notify_struct(NIF_INFO, info=text, title=title)
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    def stop(self) -> None:
        """Ask the pump to exit (removes the icon in the run loop's tail)."""
        if sys.platform != "win32" or self._hwnd is None:
            return
        try:
            import ctypes
            ctypes.windll.user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        except Exception:
            pass


def start_tray(on_show: Callable[[], None], on_exit: Callable[[], None],
               icon_path: Optional[str] = None,
               tooltip: str = "Rivult Tracker") -> Optional[Tray]:
    """Start the tray on a daemon thread; None off-Windows or on failure.

    Returning None is a CONTRACT: the caller keeps X closing the app. Handing
    back a tray that isn't really there hides the window with no way to get it
    back. The reason is printed rather than swallowed — it lands in rivult.log,
    which is the only diagnostic a tester can send.
    """
    if sys.platform != "win32":
        return None
    tray = Tray(on_show, on_exit, icon_path=icon_path, tooltip=tooltip)
    threading.Thread(target=tray.run, daemon=True).start()
    if not tray.started.wait(timeout=TRAY_START_TIMEOUT_S):
        print("tray: icon did not come up in time - X will close the app")
        return None
    if tray.error:
        print(f"tray unavailable ({tray.error}) - X will close the app")
        return None
    return tray
