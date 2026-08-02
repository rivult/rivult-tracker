"""Bridging input recorder (Windows, stdlib ctypes).

Records ONLY a fixed allowlist of eight game inputs — W A S D, Shift, Space,
and the two mouse buttons — with millisecond timestamps, so bridging
technique can be analysed in the viewer (speed bridging first: shift-pulse
length, shift-release -> place latency, blocks per second).

Guardrails, deliberately hard-coded — do NOT widen these:

* the allowlist is FIXED: there is no code path that records any other key,
  and never text. Polling reads key *state* via GetAsyncKeyState — no global
  hook is installed, nothing is injected into other processes.
* recording starts only from an explicit user action (the API route the
  viewer button calls) and stops itself when Minecraft loses focus for
  FOCUS_GRACE_S seconds, or after MAX_SESSION_S.
* events are buffered and written to the local SQLite file only.
"""

from __future__ import annotations

import datetime
import sqlite3
import sys
import threading
import time
from typing import Callable, Optional

# Virtual-key codes -> the only names this module will ever record.
VK_KEYS = {
    0x57: "W",
    0x41: "A",
    0x53: "S",
    0x44: "D",
    0x10: "SHIFT",   # generic VK_SHIFT: covers left and right
    0x20: "SPACE",
    0x01: "LMB",
    0x02: "RMB",
}

POLL_HZ = 250            # 4 ms resolution — plenty for 100-300 ms shift pulses
FOCUS_CHECK_S = 0.25
FOCUS_GRACE_S = 30.0     # unfocused this long -> auto-stop (reason focus_lost)
MAX_SESSION_S = 600.0    # hard cap per session (reason time_cap)
FLUSH_EVERY = 100        # buffered events per DB write

_FOCUS_TITLES = ("minecraft", "lunar", "badlion")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS input_sessions (
    id         INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    reason     TEXT
);
CREATE TABLE IF NOT EXISTS input_events (
    session_id INTEGER REFERENCES input_sessions(id) ON DELETE CASCADE,
    t_ms       INTEGER NOT NULL,
    key        TEXT NOT NULL,
    action     TEXT NOT NULL CHECK (action IN ('down','up'))
);
CREATE INDEX IF NOT EXISTS input_events_by_session
    ON input_events(session_id, t_ms);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA)
    return conn


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# -- Windows probes (swapped out by tests via constructor injection) ---------

def _win_poll() -> dict:
    """Held state AND whether the key was pressed since the previous poll.

    ``GetAsyncKeyState`` returns two bits that matter here:

    * ``0x8000`` — the key is down RIGHT NOW.
    * ``0x0001`` — the key was pressed at some point since the last call.

    Only reading 0x8000 loses any click whose press *and* release both land
    between two samples. At 250 Hz that's a 4 ms blind spot, and drag clicks
    last 1-3 ms, so a drag clicker's placements vanished entirely. The low bit
    is the only way to see them without raising the poll rate (which would
    cost CPU for a background app).

    It reports "at least one press", not how many — a true count above roughly
    60 CPS is not obtainable by polling at all. Callers must treat a recovered
    click as a floor, never as an exact rate.

    Still the same eight keys, still state reads, still no hook.
    """
    import ctypes
    user32 = ctypes.windll.user32
    fn = user32.GetAsyncKeyState
    fn.argtypes = [ctypes.c_int]
    fn.restype = ctypes.c_short      # SHORT: without this the upper bits are junk
    out = {}
    for vk, name in VK_KEYS.items():
        state = fn(vk)
        out[name] = (bool(state & 0x8000), bool(state & 0x0001))
    return out


def _as_sample(raw: dict) -> dict:
    """Normalise a poll result to ``{name: (held, pressed_since_last)}``.

    Accepts a plain ``{name: bool}`` too, so a test double that only models
    held state keeps working and simply never reports a recovered click.
    """
    out = {}
    for name, value in raw.items():
        if isinstance(value, tuple):
            out[name] = (bool(value[0]), bool(value[1]))
        else:
            out[name] = (bool(value), False)
    return out


def _win_focused() -> bool:
    """True when the foreground window looks like a Minecraft client."""
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    title = buf.value.lower()
    return any(t in title for t in _FOCUS_TITLES)


class InputRecorder:
    """One recorder per process; a session is one start..stop span."""

    def __init__(self, db_path: str,
                 poll_fn: Optional[Callable[[], dict]] = None,
                 focus_fn: Optional[Callable[[], bool]] = None,
                 max_session_s: float = MAX_SESSION_S,
                 focus_grace_s: float = FOCUS_GRACE_S):
        self.db_path = db_path
        self._poll = poll_fn or _win_poll
        self._focus = focus_fn or _win_focused
        self.max_session_s = max_session_s
        self.focus_grace_s = focus_grace_s
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._session_id: Optional[int] = None
        self._started_at: Optional[str] = None
        self._t0 = 0.0
        self._events_captured = 0
        self._last_focused = True

    # -- public API ---------------------------------------------------------
    def start(self) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("already recording")
            if self._poll is _win_poll and sys.platform != "win32":
                raise RuntimeError("input recording is Windows-only")
            conn = _connect(self.db_path)
            try:
                self._started_at = _now_iso()
                cur = conn.execute(
                    "INSERT INTO input_sessions (started_at) VALUES (?)",
                    (self._started_at,))
                conn.commit()
                self._session_id = cur.lastrowid
            finally:
                conn.close()
            self._events_captured = 0
            self._stop_event.clear()
            self._t0 = time.monotonic()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return {"ok": True, "session_id": self._session_id,
                    "started_at": self._started_at}

    def stop(self) -> dict:
        with self._lock:
            if not (self._thread and self._thread.is_alive()):
                return {"ok": False, "error": "not recording"}
            self._stop_event.set()
            thread = self._thread
        thread.join(timeout=3)
        return {"ok": True, "session": session_detail(
            self.db_path, self._session_id, include_events=False)}

    def status(self) -> dict:
        recording = bool(self._thread and self._thread.is_alive())
        return {
            "recording": recording,
            "session_id": self._session_id if recording else None,
            "started_at": self._started_at if recording else None,
            "elapsed_s": round(time.monotonic() - self._t0, 1) if recording else 0,
            "events_captured": self._events_captured,
            "focused": self._last_focused if recording else None,
        }

    # -- capture loop -------------------------------------------------------
    def _run(self) -> None:
        conn = _connect(self.db_path)   # sqlite connections are per-thread
        buffer: list = []
        prev = {name: False for name in VK_KEYS.values()}
        reason = "user_stop"
        unfocused_since: Optional[float] = None
        last_focus_check = 0.0
        interval = 1.0 / POLL_HZ

        def flush() -> None:
            if not buffer:
                return
            conn.executemany(
                "INSERT INTO input_events (session_id, t_ms, key, action) "
                "VALUES (?,?,?,?)", buffer)
            conn.commit()
            buffer.clear()

        try:
            while not self._stop_event.is_set():
                now = time.monotonic()
                if now - self._t0 >= self.max_session_s:
                    reason = "time_cap"
                    break
                if now - last_focus_check >= FOCUS_CHECK_S:
                    last_focus_check = now
                    self._last_focused = self._focus()
                    if self._last_focused:
                        unfocused_since = None
                    elif unfocused_since is None:
                        unfocused_since = now
                    elif now - unfocused_since >= self.focus_grace_s:
                        reason = "focus_lost"
                        break
                if self._last_focused:
                    t_ms = int((now - self._t0) * 1000)
                    for name, (down, pressed) in _as_sample(self._poll()).items():
                        if down != prev[name]:
                            prev[name] = down
                            buffer.append((self._session_id, t_ms, name,
                                           "down" if down else "up"))
                            self._events_captured += 1
                        elif pressed and not down:
                            # A full press+release happened between two samples
                            # and is already over. Record it as a zero-length
                            # click so it isn't silently lost — see _win_poll.
                            buffer.append((self._session_id, t_ms, name, "down"))
                            buffer.append((self._session_id, t_ms, name, "up"))
                            self._events_captured += 2
                    if len(buffer) >= FLUSH_EVERY:
                        flush()
                time.sleep(interval)
        finally:
            flush()
            conn.execute(
                "UPDATE input_sessions SET ended_at=?, reason=? WHERE id=?",
                (_now_iso(), reason, self._session_id))
            conn.commit()
            conn.close()


# -- reads (viewer API) ------------------------------------------------------

def list_sessions(db_path: str, limit: int = 50) -> list:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT s.id, s.started_at, s.ended_at, s.reason,
                      COUNT(e.rowid) AS events,
                      COALESCE(SUM(e.key = 'RMB' AND e.action = 'down'), 0)
                          AS placements,
                      COALESCE(MAX(e.t_ms), 0) AS span_ms
                 FROM input_sessions s
                 LEFT JOIN input_events e ON e.session_id = s.id
                GROUP BY s.id ORDER BY s.id DESC LIMIT ?""",
            (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def session_detail(db_path: str, session_id: Optional[int],
                   include_events: bool = True) -> Optional[dict]:
    if session_id is None:
        return None
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM input_sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        if include_events:
            d["events"] = [dict(r) for r in conn.execute(
                "SELECT t_ms, key, action FROM input_events "
                "WHERE session_id=? ORDER BY t_ms", (session_id,))]
        return d
    finally:
        conn.close()


# -- process-wide singleton (the server shares one recorder) -----------------

_recorder: Optional[InputRecorder] = None
_recorder_lock = threading.Lock()


def get_recorder(db_path: str) -> InputRecorder:
    global _recorder
    with _recorder_lock:
        if _recorder is None or _recorder.db_path != db_path:
            _recorder = InputRecorder(db_path)
        return _recorder
