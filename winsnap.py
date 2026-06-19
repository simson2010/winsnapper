"""
winsnap.py — Windows window-snapping utility with global hotkeys.

Features
--------
- Snap windows to left/right/top/bottom halves, centre, or full work area
- Incremental sizing: press the same snap hotkey repeatedly to cycle
  50% → 75% → 100% → 50% (left/right/top/bottom only)
- Configurable hotkeys via the Settings window
- Settings persisted to winsnap_config.json
- System-tray icon with About / Settings / Exit menu

The application runs headless, residing in the system tray.
"""

import os
import sys
import json
import time
import logging
import threading
import traceback
import ctypes
from typing import Dict, Optional, Tuple, List

import tkinter as tk
from tkinter import ttk, messagebox

import win32gui
import win32api
import win32con
import win32process
import keyboard
import pystray
from pystray._win32 import Icon as _PystrayIcon
from ctypes import wintypes
from pystray._util import win32 as _pystray_win32
from PIL import Image

# ---------------------------------------------------------------------------
# Monkey-patch pystray: GetMessage returning -1 should NOT kill the app.
# The stock _mainloop breaks out of the loop on -1 (an error), which causes
# icon.run() to return silently and the process to exit.  We replace it
# with a version that logs the error and continues the message pump.
# ---------------------------------------------------------------------------
_original_mainloop = _PystrayIcon._mainloop


def _patched_mainloop(self):
    """pystray mainloop that survives GetMessage errors (-1)."""
    try:
        msg = wintypes.MSG()
        lpmsg = ctypes.byref(msg)
        while True:
            r = _pystray_win32.GetMessage(lpmsg, None, 0, 0)
            if not r:
                break
            elif r == -1:
                logger.warning("GetMessage returned -1 (error), continuing message loop")
                continue
            else:
                _pystray_win32.TranslateMessage(lpmsg)
                _pystray_win32.DispatchMessage(lpmsg)
    except Exception:
        logger.exception("Error in patched mainloop")
    finally:
        try:
            self._hide()
            del self._HWND_TO_ICON[self._hwnd]
        except Exception:
            pass
        _pystray_win32.DestroyWindow(self._hwnd)
        _pystray_win32.DestroyWindow(self._menu_hwnd)
        if self._menu_handle:
            hmenu, callbacks = self._menu_handle
            _pystray_win32.DestroyMenu(hmenu)
        self._unregister_class(self._atom)


_PystrayIcon._mainloop = _patched_mainloop

# ---------------------------------------------------------------------------
# Monkey-patch keyboard library: make process() survive callback exceptions.
# The stock process() has no try/except — one bad callback kills the thread
# and hotkeys stop working forever with no way to restart.
# Patch the CLASS, not the instance, so Thread(target=self.process) works.
# ---------------------------------------------------------------------------
import keyboard._generic as _keyboard_generic


def _patched_keyboard_process(self):
    """keyboard listener process loop that survives callback exceptions."""
    while True:
        try:
            event = self.queue.get()
            if self.pre_process_event(event):
                self.invoke_handlers(event)
            self.queue.task_done()
        except Exception:
            traceback.print_exc()


_keyboard_generic.GenericListener.process = _patched_keyboard_process

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_NAME: str = "WinSnap"
APP_VERSION: str = "1.1.0"
# Time for the shell to process tray-icon removal before os._exit (seconds)
_TRAY_REMOVE_DELAY_S: float = 0.35
_SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))


def _resolve_icon_path() -> str:
    """Dev: ``icon/icon.ico``; frozen one-file: ``icon.ico`` in ``_MEIPASS``."""
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", _SCRIPT_DIR), "icon.ico")
    return os.path.join(_SCRIPT_DIR, "icon", "icon.ico")


ICON_PATH: str = _resolve_icon_path()


def _resolve_app_dir() -> str:
    """Dev: script directory; frozen one-file: directory containing the .exe."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR: str = _resolve_app_dir()
CONFIG_PATH: str = os.path.join(APP_DIR, "winsnap_config.json")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_PATH: str = os.path.join(APP_DIR, "winsnap.log")
logger = logging.getLogger("winsnap")
logger.setLevel(logging.DEBUG)
_log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
_log_file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
_log_file_handler.setFormatter(_log_formatter)
logger.addHandler(_log_file_handler)

# Default hotkey configuration  {action_key: hotkey_string}
DEFAULT_HOTKEYS: Dict[str, str] = {
    "left":   "ctrl+alt+left",
    "right":  "ctrl+alt+right",
    "top":    "ctrl+alt+up",
    "bottom": "ctrl+alt+down",
    "center": "ctrl+alt+c",
    "full":   "ctrl+alt+f",
    "restore": "ctrl+alt+r",
}

# Human-readable action labels (for Settings / About)
ACTION_LABELS: Dict[str, str] = {
    "left":    "Left half",
    "right":   "Right half",
    "top":     "Top half",
    "bottom":  "Bottom half",
    "center":  "Centre (60% width)",
    "full":    "Full work area",
    "restore": "Restore previous position",
}

# Window identity: (pid, class_name, title) — detects HWND reuse across processes
WindowIdentity = Tuple[int, str, str]

# hwnd -> (identity, rect) saved before the last snap (for restore)
original_positions: Dict[int, Tuple[WindowIdentity, Tuple[int, int, int, int]]] = {}

# hwnd -> (identity, (direction, level)); direction in left/right/top/bottom; level 0..2
last_snap_state: Dict[int, Tuple[WindowIdentity, Tuple[str, int]]] = {}

# Protects original_positions / last_snap_state (keyboard thread vs settings thread)
_state_lock = threading.Lock()

# Percentage multipliers for incremental sizing
INCREMENT_WIDTH_PCT: List[float]  = [0.50, 0.75, 1.00]
INCREMENT_HEIGHT_PCT: List[float] = [0.50, 0.75, 1.00]

# Currently loaded hotkey config (mutated at runtime)
current_hotkeys: Dict[str, str] = {}

# Reference to the tray icon (set after build_tray_icon)
_tray_icon: Optional[pystray.Icon] = None

# Reference to the settings window (to prevent duplicates)
_settings_window_open: bool = False

# ---------------------------------------------------------------------------
# Configuration persistence
# ---------------------------------------------------------------------------

def load_config() -> Dict[str, str]:
    """Load hotkey configuration from winsnap_config.json.

    If the file does not exist or is invalid, return the defaults.

    Returns:
        A dict mapping action keys to hotkey strings.
    """
    logger.info("Loading config from %s", CONFIG_PATH)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "hotkeys" in data:
            # Merge with defaults so any missing key falls back
            merged = dict(DEFAULT_HOTKEYS)
            raw = data["hotkeys"]
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if key in DEFAULT_HOTKEYS and isinstance(value, str) and value.strip():
                        merged[key] = value.strip()
            logger.info("Config loaded: %s", merged)
            return merged
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load config (%s), using defaults", e)
    return dict(DEFAULT_HOTKEYS)


def save_config(hotkeys: Dict[str, str]) -> None:
    """Save hotkey configuration to winsnap_config.json.

    Args:
        hotkeys: A dict mapping action keys to hotkey strings.
    """
    logger.info("Saving config to %s: %s", CONFIG_PATH, hotkeys)
    data = {"hotkeys": hotkeys}
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    logger.info("Config saved successfully")


# ---------------------------------------------------------------------------
# DPI awareness — required for correct geometry on high-DPI displays
# ---------------------------------------------------------------------------

def _enable_dpi_awareness() -> None:
    """Set per-monitor DPI awareness so win32 geometry calls are accurate."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        logger.info("DPI awareness: PROCESS_PER_MONITOR_DPI_AWARE")
    except AttributeError:
        # Windows 7 / early Win8 — fall back to system DPI aware
        ctypes.windll.user32.SetProcessDPIAware()
        logger.info("DPI awareness: fallback SetProcessDPIAware")


# ---------------------------------------------------------------------------
# Window identity & stale-state pruning
# ---------------------------------------------------------------------------

# Shell window classes that must never be snapped (stable across HWND reuse)
_SHELL_WINDOW_CLASSES: frozenset = frozenset({
    "Progman",
    "WorkerW",
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "DV2ControlHost",
    "MsgrIMEWindowClass",
})

# Desktop / Shell HWNDs refreshed at runtime (WorkerW instances come and go)
_SHELL_HWNDS: frozenset = frozenset()


def _init_shell_hwnds() -> None:
    """Populate the initial set of shell HWNDs (refreshed again on each snap)."""
    _refresh_shell_hwnds()


def _refresh_shell_hwnds() -> None:
    """Re-scan for Progman, WorkerW, and taskbar HWNDs."""
    global _SHELL_HWNDS
    hwnds: set = set()
    for class_name, title in (
        ("Progman", None),
        ("Shell_TrayWnd", None),
        ("Shell_SecondaryTrayWnd", None),
    ):
        try:
            h = win32gui.FindWindow(class_name, title)
            if h:
                hwnds.add(h)
        except Exception:
            pass
    try:
        h = win32gui.FindWindowEx(0, 0, "WorkerW", None)
        while h:
            hwnds.add(h)
            h = win32gui.FindWindowEx(0, h, "WorkerW", None)
    except Exception:
        pass
    _SHELL_HWNDS = frozenset(hwnds)  # type: ignore[assignment]


def _window_identity(hwnd: int) -> Optional[WindowIdentity]:
    """Return (pid, class_name, title) for *hwnd*, or None if unavailable."""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        class_name = win32gui.GetClassName(hwnd)
        title = win32gui.GetWindowText(hwnd)
        return (pid, class_name, title)
    except Exception:
        return None


def _identities_match(stored: WindowIdentity, current: WindowIdentity) -> bool:
    """True if *stored* and *current* refer to the same logical window."""
    return stored == current


def _is_snapifiable(hwnd: int) -> bool:
    """Return True if *hwnd* is a valid, visible window we can snap.

    Filters out:
      - The null HWND
      - Destroyed / invalid HWNDs (``IsWindow`` returns False)
      - Desktop / Shell windows (class name and known HWNDs)
      - Invisible windows
    """
    if not hwnd:
        return False
    if not win32gui.IsWindow(hwnd):
        return False
    if not win32gui.IsWindowVisible(hwnd):
        return False
    try:
        class_name = win32gui.GetClassName(hwnd)
    except Exception:
        return False
    if class_name in _SHELL_WINDOW_CLASSES:
        return False
    if hwnd in _SHELL_HWNDS:
        return False
    return True


def _prune_stale_hwnds() -> None:
    """Remove state for destroyed HWNDs or HWND reuse (identity mismatch).

    Must be called with ``_state_lock`` held.
    """
    def _is_stale(h: int) -> bool:
        if not win32gui.IsWindow(h):
            return True
        identity = _window_identity(h)
        if identity is None:
            return True
        if h in original_positions:
            stored_id, _ = original_positions[h]
            if not _identities_match(stored_id, identity):
                return True
        if h in last_snap_state:
            stored_id, _ = last_snap_state[h]
            if not _identities_match(stored_id, identity):
                return True
        return False

    for h in [k for k in original_positions if _is_stale(k)]:
        del original_positions[h]
    for h in [k for k in last_snap_state if _is_stale(k)]:
        del last_snap_state[h]


def _clear_window_state(hwnd: int) -> None:
    """Drop all snap/restore state for *hwnd* (lock must be held)."""
    original_positions.pop(hwnd, None)
    last_snap_state.pop(hwnd, None)


# ---------------------------------------------------------------------------
# Monitor helpers
# ---------------------------------------------------------------------------

def get_work_area(hwnd: int) -> Tuple[int, int, int, int]:
    """Return the work area (excluding taskbar) for the monitor containing *hwnd*.

    Args:
        hwnd: Handle to the window whose monitor should be queried.

    Returns:
        A 4-tuple (left, top, right, bottom) in screen coordinates.
    """
    monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
    info = win32api.GetMonitorInfo(monitor)
    return tuple(info["Work"])  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Invisible-border compensation (Windows 10/11 DWM shadow frame)
# ---------------------------------------------------------------------------

class _RECT(ctypes.Structure):
    """Minimal RECT struct for DWM API calls."""
    _fields_ = [
        ("left",   ctypes.c_long),
        ("top",    ctypes.c_long),
        ("right",  ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def get_border_offsets(hwnd: int) -> Tuple[int, int, int, int]:
    """Return the invisible border offsets (left, top, right, bottom).

    On Windows 10/11 every top-level window has a thin invisible frame
    (≈ 7-8 px sides/bottom, ≈ 1 px top) reserved by DWM for the drop
    shadow and resize handles.  ``MoveWindow`` positions the *outer*
    rect (including this frame), so the visible content ends up a few
    pixels away from the screen edge.

    This function queries ``DwmGetWindowAttribute`` with
    ``DWMWA_EXTENDED_FRAME_BOUNDS`` to measure the difference between
    the outer rect and the visible frame, then returns per-side offsets
    that should be *added* to position/size to compensate.

    Returns:
        A 4-tuple ``(left, top, right, bottom)`` in pixels.  Each value
        is the number of invisible pixels on that side (always ≥ 0).
        If the DWM call fails, returns ``(0, 0, 0, 0)`` as a safe
        fallback.
    """
    # Get the window rect reported by Win32 (includes invisible frame)
    try:
        win_rect = win32gui.GetWindowRect(hwnd)
    except Exception:
        return (0, 0, 0, 0)

    # Get the extended frame bounds (visible content area) from DWM
    frame = _RECT()
    hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        hwnd,
        9,  # DWMWA_EXTENDED_FRAME_BOUNDS
        ctypes.byref(frame),
        ctypes.sizeof(frame),
    )
    if hr != 0:  # S_OK == 0
        return (0, 0, 0, 0)

    # The invisible border on each side = win32_rect - visible_frame
    bl = frame.left   - win_rect[0]
    bt = frame.top    - win_rect[1]
    br = win_rect[2]  - frame.right
    bb = win_rect[3]  - frame.bottom

    # Clamp to non-negative (sanity)
    return (max(bl, 0), max(bt, 0), max(br, 0), max(bb, 0))


# ---------------------------------------------------------------------------
# Core snap logic (with incremental sizing)
# ---------------------------------------------------------------------------

def snap_window(position: str) -> None:
    """Move the foreground window to the requested snap position.

    Supports incremental sizing for left/right/top/bottom:
      - Same direction twice → width/height increases to 75%
      - Three times → 100%
      - Four times → back to 50% (cycle)

    Saves the window's current rect to *original_positions* before moving so
    Ctrl+Alt+R can restore it.

    Args:
        position: One of ``'left'``, ``'right'``, ``'top'``, ``'bottom'``,
                  ``'center'``, ``'full'``.
    """
    logger.info("snap_window(%s) triggered", position)
    _refresh_shell_hwnds()
    hwnd: int = win32gui.GetForegroundWindow()
    if not _is_snapifiable(hwnd):
        logger.debug("snap_window(%s): hwnd %d not snapifiable, skipping", position, hwnd)
        return

    identity = _window_identity(hwnd)
    if identity is None:
        logger.debug("snap_window(%s): hwnd %d identity is None, skipping", position, hwnd)
        return

    with _state_lock:
        _prune_stale_hwnds()
        original_positions[hwnd] = (identity, win32gui.GetWindowRect(hwnd))

    # Restore from maximised/minimised before repositioning
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    work = get_work_area(hwnd)
    wx, wy, wr, wb = work
    w: int = wr - wx   # work-area width
    h: int = wb - wy   # work-area height

    # --- Get invisible border offsets for edge-flush positioning ---
    bl, bt, br, bb = get_border_offsets(hwnd)

    # --- Determine incremental level ---
    level: int = 0
    if position in ("left", "right", "top", "bottom"):
        with _state_lock:
            entry = last_snap_state.get(hwnd)
            if entry is not None:
                stored_id, (prev_direction, prev_level) = entry
                if _identities_match(stored_id, identity) and prev_direction == position:
                    level = (prev_level + 1) % 3
            last_snap_state[hwnd] = (identity, (position, level))

    # --- Compute width/height multipliers based on direction and level ---
    width_pct: float = 0.50
    height_pct: float = 1.00

    if position == "left":
        width_pct = INCREMENT_WIDTH_PCT[level]
        height_pct = 1.00
    elif position == "right":
        width_pct = INCREMENT_WIDTH_PCT[level]
        height_pct = 1.00
    elif position == "top":
        width_pct = 1.00
        height_pct = INCREMENT_HEIGHT_PCT[level]
    elif position == "bottom":
        width_pct = 1.00
        height_pct = INCREMENT_HEIGHT_PCT[level]
    elif position == "center":
        width_pct = 0.60
        height_pct = 1.00
    elif position == "full":
        width_pct = 1.00
        height_pct = 1.00
    else:
        return  # unknown position

    # --- Compute final geometry ---
    pw: int = int(w * width_pct)
    ph: int = int(h * height_pct)

    # Base snap positions (before border compensation)
    snap_positions: Dict[str, Tuple[int, int]] = {
        "left":   (wx, wy),
        "right":  (wx + w - pw, wy),
        "top":    (wx, wy),
        "bottom": (wx, wy + h - ph),
        "center": (wx + (w - pw) // 2, wy),
        "full":   (wx, wy),
    }

    x, y = snap_positions[position]

    # --- Compensate for the invisible DWM border ---
    # MoveWindow positions the *outer* rect (including the invisible
    # frame).  To make the visible content flush with a screen edge we
    # must nudge the window *past* that edge by the border width, and
    # enlarge the window so the visible size remains correct.
    #
    # Diagram (left snap, borders exaggerated):
    #   screen edge  |BL  visible content  BR|
    #   ────────────┤                       │
    #   x = wx - BL │  pw = pw + BL + BR    │
    #
    if position == "left":
        # Visible left edge flush with screen left
        x = wx - bl
        pw += bl + br
        ph += bt + bb
    elif position == "right":
        # Visible right edge flush with screen right
        # After widening: outer_right = x + (pw + bl + br) must land
        # at wx + w + br (past screen right by right border)
        pw_adj = pw + bl + br
        x = wx + w + br - pw_adj
        pw = pw_adj
        ph += bt + bb
    elif position == "top":
        # Visible top edge flush with screen top
        y = wy - bt
        pw += bl + br
        ph += bt + bb
    elif position == "bottom":
        # Visible bottom edge flush with work-area bottom (above taskbar)
        # After heightening: outer_bottom = y + (ph + bt + bb) must land
        # at wb + bb (past work-area bottom by bottom border)
        ph_adj = ph + bt + bb
        y = wb + bb - ph_adj
        pw += bl + br
        ph = ph_adj
    elif position == "full":
        # All edges flush
        x = wx - bl
        y = wy - bt
        pw += bl + br
        ph += bt + bb
    elif position == "center":
        # Centre doesn't touch screen edges, but compensate borders
        # so the visible size matches the intended percentage
        pw += bl + br
        ph += bt + bb

    logger.info("snap_window(%s): hwnd=%d level=%d -> (%d, %d, %d, %d)",
                position, hwnd, level, x, y, pw, ph)
    win32gui.MoveWindow(hwnd, x, y, pw, ph, True)


def restore_window() -> None:
    """Restore the foreground window to its position before the last snap.

    If no previous position is recorded for this window, the call is a no-op.
    Clears snap state for this window so incremental sizing restarts at 50%.
    """
    logger.info("restore_window() triggered")
    _refresh_shell_hwnds()
    hwnd: int = win32gui.GetForegroundWindow()
    if not _is_snapifiable(hwnd):
        logger.debug("restore_window: hwnd %d not snapifiable, skipping", hwnd)
        return

    identity = _window_identity(hwnd)
    if identity is None:
        logger.debug("restore_window: hwnd %d identity is None, skipping", hwnd)
        return

    with _state_lock:
        _prune_stale_hwnds()
        entry = original_positions.get(hwnd)
        if entry is None:
            logger.debug("restore_window: hwnd %d has no saved position", hwnd)
            return
        stored_id, rect = entry
        if not _identities_match(stored_id, identity):
            _clear_window_state(hwnd)
            return
        _clear_window_state(hwnd)

    left, top, right, bottom = rect
    logger.info("restore_window: hwnd=%d -> (%d, %d, %d, %d)", hwnd, left, top, right, bottom)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.MoveWindow(hwnd, left, top, right - left, bottom - top, True)


# ---------------------------------------------------------------------------
# Hotkey registration
# ---------------------------------------------------------------------------

def register_hotkeys() -> None:
    """Register all global hotkeys using the *keyboard* library.

    Each handler runs on the keyboard listener thread; win32 calls are
    thread-safe for window manipulation so this is acceptable.

    If a hotkey combo is invalid, falls back to the default.  If the
    default also fails, the action is silently skipped (user will see
    it not working but the app won't crash).
    """
    action_map: Dict[str, object] = {
        "left":    lambda: snap_window("left"),
        "right":   lambda: snap_window("right"),
        "top":     lambda: snap_window("top"),
        "bottom":  lambda: snap_window("bottom"),
        "center":  lambda: snap_window("center"),
        "full":    lambda: snap_window("full"),
        "restore": lambda: restore_window(),
    }

    for action, handler in action_map.items():
        combo = current_hotkeys.get(action, DEFAULT_HOTKEYS[action])
        try:
            keyboard.add_hotkey(combo, handler, suppress=False)
            logger.info("Hotkey registered: %s -> %s", combo, action)
        except (ValueError, KeyError):
            # Invalid combo — fall back to default
            default_combo = DEFAULT_HOTKEYS.get(action)
            if default_combo and default_combo != combo:
                try:
                    keyboard.add_hotkey(default_combo, handler, suppress=False)
                    logger.info("Hotkey registered (fallback): %s -> %s", default_combo, action)
                except (ValueError, KeyError):
                    logger.warning("Hotkey failed for %s: %s and default %s", action, combo, default_combo)


def register_hotkeys_with_fallback() -> None:
    """Re-register hotkeys, falling back to defaults for any invalid combos.

    If the default combo also fails, the action is silently skipped.
    """
    global current_hotkeys
    action_map: Dict[str, object] = {
        "left":    lambda: snap_window("left"),
        "right":   lambda: snap_window("right"),
        "top":     lambda: snap_window("top"),
        "bottom":  lambda: snap_window("bottom"),
        "center":  lambda: snap_window("center"),
        "full":    lambda: snap_window("full"),
        "restore": lambda: restore_window(),
    }
    for action, handler in action_map.items():
        combo = current_hotkeys.get(action, DEFAULT_HOTKEYS[action])
        try:
            keyboard.add_hotkey(combo, handler, suppress=False)
            logger.info("Hotkey registered: %s -> %s", combo, action)
        except (ValueError, KeyError):
            default_combo = DEFAULT_HOTKEYS[action]
            try:
                keyboard.add_hotkey(default_combo, handler, suppress=False)
                current_hotkeys[action] = default_combo
                logger.info("Hotkey registered (fallback): %s -> %s", default_combo, action)
            except (ValueError, KeyError):
                logger.warning("Hotkey failed for %s: %s and default %s", action, combo, default_combo)


def reregister_hotkeys() -> None:
    """Unregister all hotkeys and re-register from current_hotkeys."""
    logger.info("Re-registering all hotkeys")
    keyboard.unhook_all_hotkeys()
    register_hotkeys()


def _normalize_hotkey(combo: str) -> str:
    """Normalize a hotkey string for duplicate comparison."""
    return "+".join(part.strip().lower() for part in combo.split("+") if part.strip())


def _find_duplicate_hotkeys(hotkeys: Dict[str, str]) -> List[Tuple[str, str]]:
    """Return pairs of action keys that share the same hotkey combo."""
    by_combo: Dict[str, str] = {}
    duplicates: List[Tuple[str, str]] = []
    for action in DEFAULT_HOTKEYS:
        combo = _normalize_hotkey(hotkeys.get(action, ""))
        if not combo:
            continue
        if combo in by_combo:
            duplicates.append((by_combo[combo], action))
        else:
            by_combo[combo] = action
    return duplicates


# ---------------------------------------------------------------------------
# Settings window (tkinter)
# ---------------------------------------------------------------------------

def _open_settings_window() -> None:
    """Open a non-modal tkinter Settings window.

    The window is non-blocking so the hotkey listener and tray icon continue
    to function while the settings dialog is visible.
    """
    global _settings_window_open

    if _settings_window_open:
        logger.debug("Settings window already open, skipping")
        return  # Already open — don't create a duplicate

    _settings_window_open = True
    logger.info("Opening settings window")

    try:
        _open_settings_window_inner()
    except Exception:  # pylint: disable=broad-except
        # If anything goes wrong, ensure the flag is reset so
        # the settings window can be opened again.
        logger.exception("Settings window error")
        _settings_window_open = False


def _open_settings_window_inner() -> None:
    """Inner implementation of the Settings window.

    Called by ``_open_settings_window`` inside a try/except guard so that
    the ``_settings_window_open`` flag is always reset on failure.
    """
    # ---- Build window ----
    root = tk.Tk()
    root.title(f"{APP_NAME} Settings")
    root.resizable(False, False)
    root.protocol("WM_DELETE_WINDOW", lambda: _on_settings_close(root))

    # ---- Working copy of hotkeys ----
    working_hotkeys: Dict[str, str] = dict(current_hotkeys)

    # ---- Capture state ----
    capturing_row: Dict[str, bool] = {}  # {action: True} when that row is capturing

    # ---- Top section: hotkey table ----
    top_frame = ttk.LabelFrame(root, text="Shortcut Keys", padding=10)
    top_frame.pack(fill="x", padx=10, pady=(10, 5))

    # Header
    for col, header in enumerate(["Action", "Hotkey", ""], start=0):
        ttk.Label(top_frame, text=header, font=("", 10, "bold")).grid(
            row=0, column=col, sticky="w", padx=(0, 10), pady=2
        )

    action_order = ["left", "right", "top", "bottom", "center", "full", "restore"]
    row_widgets: Dict[str, Dict[str, object]] = {}

    for i, action in enumerate(action_order, start=1):
        label_text = ACTION_LABELS.get(action, action)
        ttk.Label(top_frame, text=label_text).grid(row=i, column=0, sticky="w", pady=2)

        hotkey_var = tk.StringVar(value=working_hotkeys.get(action, ""))
        hotkey_label = ttk.Label(top_frame, textvariable=hotkey_var, width=20, anchor="w")
        hotkey_label.grid(row=i, column=1, sticky="w", padx=(10, 10), pady=2)

        modify_btn = ttk.Button(
            top_frame, text="Modify", width=8,
            command=lambda a=action: _start_capture(a)
        )
        modify_btn.grid(row=i, column=2, pady=2)

        row_widgets[action] = {
            "var": hotkey_var,
            "label": hotkey_label,
            "button": modify_btn,
        }

    # ---- Capture helpers ----
    def _start_capture(action: str) -> None:
        """Begin capturing a new hotkey for *action*."""
        # If another row is already capturing, cancel it
        for a in list(capturing_row.keys()):
            if a != action:
                _cancel_capture(a)

        capturing_row[action] = True
        widgets = row_widgets[action]
        hotkey_var = widgets["var"]  # type: ignore[index]
        btn = widgets["button"]  # type: ignore[index]
        hotkey_var.set("Press new shortcut...")
        btn.config(text="Cancel", command=lambda: _cancel_capture(action))

        # Bind key events to the root window
        root.bind("<Key>", lambda e, a=action: _on_key_press(e, a))
        root.focus_set()

    def _cancel_capture(action: str) -> None:
        """Cancel capturing for *action* and restore the original value."""
        if action in capturing_row:
            del capturing_row[action]
        widgets = row_widgets[action]
        hotkey_var = widgets["var"]  # type: ignore[index]
        btn = widgets["button"]  # type: ignore[index]
        hotkey_var.set(working_hotkeys.get(action, ""))
        btn.config(text="Modify", command=lambda: _start_capture(action))

    # Modifier keysyms reported by tkinter — must be skipped because
    # the keyboard library does not accept names like "control_l".
    _MODIFIER_KEYSYMS = frozenset({
        "control_l", "control_r", "shift_l", "shift_r",
        "alt_l", "alt_r", "super_l", "super_r", "caps_lock",
    })

    # Mapping from tkinter keysym (lowercase) → keyboard-library key name
    _TK_TO_KEYBOARD = {
        "left": "left", "right": "right", "up": "up", "down": "down",
        "return": "enter", "backspace": "backspace", "space": "space",
        "tab": "tab", "escape": "esc", "delete": "delete",
        "home": "home", "end": "end",
        "prior": "page up", "next": "page down",
        "insert": "insert", "num_lock": "num lock",
        "scroll_lock": "scroll lock", "print": "print screen",
        "pause": "pause", "windows_l": "windows", "windows_r": "windows",
        "menu": "menu",
    }

    def _on_key_press(event: object, action: str) -> None:
        """Handle a key press during capture mode.

        Builds a keyboard-library-compatible hotkey string from the
        Tkinter event's modifier keys and key symbol.
        """
        if action not in capturing_row:
            return

        if not isinstance(event, tk.Event):
            return

        # Escape with no modifiers → cancel capture
        keysym: str = event.keysym.lower()
        if keysym == "escape" and event.state == 0:
            _cancel_capture(action)
            return "break"

        # Skip standalone modifier key presses (Ctrl/Alt/Shift alone)
        # We only capture when a *non-modifier* key is pressed alongside modifiers
        if keysym in _MODIFIER_KEYSYMS:
            return  # Wait for the actual key

        # Build modifier list from event.state bitmask
        mods: List[str] = []
        if event.state & 0x4:   # Ctrl
            mods.append("ctrl")
        if event.state & 0x1:   # Shift
            mods.append("shift")
        if event.state & 0x20000 or event.state & 0x8:  # Alt (Linux mask | Win mask)
            mods.append("alt")

        # Normalize the main key to keyboard-library format
        if keysym in _TK_TO_KEYBOARD:
            key_part = _TK_TO_KEYBOARD[keysym]
        elif len(keysym) == 1 and keysym.isalpha():
            key_part = keysym
        elif len(keysym) == 1 and keysym.isdigit():
            key_part = keysym
        elif keysym.startswith("f") and keysym[1:].isdigit():
            key_part = keysym  # F1-F12 pass through as-is
        else:
            # Unknown key — skip rather than risk a ValueError later
            return

        # Only accept if there's at least one modifier (prevent accidental single-key binds)
        if not mods:
            return  # Ignore bare key presses — require at least one modifier

        combo_parts = mods + [key_part]
        new_hotkey = "+".join(combo_parts)

        # Validate the hotkey string with the keyboard library before accepting
        try:
            keyboard.parse_hotkey(new_hotkey)
        except (ValueError, KeyError):
            return  # Invalid combo — skip silently

        # Update the working copy
        working_hotkeys[action] = new_hotkey
        capturing_row.pop(action, None)

        widgets = row_widgets[action]
        hotkey_var = widgets["var"]  # type: ignore[index]
        btn = widgets["button"]  # type: ignore[index]
        hotkey_var.set(new_hotkey)
        btn.config(text="Modify", command=lambda: _start_capture(action))

        # Unbind key capture
        root.unbind("<Key>")

    # ---- Bottom section: Save / Cancel buttons ----
    btn_frame = ttk.Frame(root)
    btn_frame.pack(fill="x", padx=10, pady=5)

    def _on_save() -> None:
        """Persist the working hotkeys and re-register."""
        global current_hotkeys
        logger.info("Settings Save clicked")
        duplicates = _find_duplicate_hotkeys(working_hotkeys)
        if duplicates:
            a, b = duplicates[0]
            label_a = ACTION_LABELS.get(a, a)
            label_b = ACTION_LABELS.get(b, b)
            combo = working_hotkeys.get(b, "")
            logger.warning("Duplicate hotkey detected: %s used by both %s and %s", combo, a, b)
            messagebox.showerror(
                "Duplicate shortcut",
                f"The shortcut \"{combo}\" is assigned to both\n"
                f"\"{label_a}\" and \"{label_b}\".\n\n"
                "Please give each action a unique shortcut before saving.",
                parent=root,
            )
            return
        current_hotkeys = dict(working_hotkeys)
        save_config(current_hotkeys)
        # Re-register hotkeys — wrapped in try/except to prevent
        # a bad combo from crashing the app
        try:
            reregister_hotkeys()
        except (ValueError, KeyError):
            # If any combo is invalid, fall back to defaults and retry
            register_hotkeys_with_fallback()
        _on_settings_close(root)

    def _on_cancel() -> None:
        """Discard changes and close."""
        _on_settings_close(root)

    ttk.Button(btn_frame, text="Save", command=_on_save, width=10).pack(side="right", padx=(5, 0))
    ttk.Button(btn_frame, text="Cancel", command=_on_cancel, width=10).pack(side="right")

    # ---- Copyright section ----
    sep = ttk.Separator(root, orient="horizontal")
    sep.pack(fill="x", padx=10, pady=(10, 5))

    copyright_frame = ttk.Frame(root)
    copyright_frame.pack(fill="x", padx=10, pady=(0, 10))

    ttk.Label(copyright_frame, text=f"{APP_NAME} v{APP_VERSION}").pack(anchor="w")
    ttk.Label(copyright_frame, text="Copyright \u00a9 2026 WinSnap Contributors").pack(anchor="w")
    ttk.Label(copyright_frame, text="Licensed under the MIT License.").pack(anchor="w")

    # ---- Present window ----
    root.geometry("+300+200")
    root.wait_window(root)


def _on_settings_close(root: object) -> None:
    """Handle the Settings window being closed.

    Properly cleans up tkinter objects to avoid 'main thread is not in
    main loop' errors when StringVar objects are garbage-collected on
    the wrong thread.
    """
    global _settings_window_open
    logger.info("Closing settings window")
    _settings_window_open = False
    if isinstance(root, tk.Tk):
        # root.destroy() alone is sufficient — it exits the mainloop
        # and destroys all widgets atomically. Do NOT call root.quit()
        # first (it exits the mainloop without destroying the window,
        # leaving tkinter in an inconsistent state), and do NOT destroy
        # children manually (triggers StringVar GC mid-iteration).
        try:
            root.unbind("<Key>")
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            root.destroy()
        except Exception:  # pylint: disable=broad-except
            pass


# ---------------------------------------------------------------------------
# Tray icon
# ---------------------------------------------------------------------------

def _load_tray_image() -> Image.Image:
    """Load the tray icon from *ICON_PATH*, or generate a fallback on the fly.

    Returns:
        A Pillow Image suitable for *pystray*.
    """
    if os.path.isfile(ICON_PATH):
        with Image.open(ICON_PATH) as im:
            return im.convert("RGBA").copy()

    # Fallback: generate programmatically
    try:
        from icon import create_icon  # type: ignore[import]
        return create_icon(64)
    except ImportError:
        # Last resort: plain blue square
        img = Image.new("RGBA", (64, 64), (30, 120, 220, 255))
        return img


def _show_about(icon: pystray.Icon, item: pystray.MenuItem) -> None:  # noqa: ARG001
    """Display a MessageBox with application information.

    Reads the current hotkey configuration so the displayed shortcuts
    always match what is actually registered.
    """
    # Build hotkey list from current config
    action_order = ["left", "right", "top", "bottom", "center", "full", "restore"]
    hotkey_lines: List[str] = []
    for action in action_order:
        combo = current_hotkeys.get(action, DEFAULT_HOTKEYS[action])
        label = ACTION_LABELS.get(action, action)
        hotkey_lines.append(f"  {combo:<20s} \u2192 {label}")

    hotkey_text = "\n".join(hotkey_lines)

    ctypes.windll.user32.MessageBoxW(
        0,
        (
            f"{APP_NAME} v{APP_VERSION}\n\n"
            "Global hotkeys:\n"
            f"{hotkey_text}\n\n"
            "Tip: press the same snap hotkey repeatedly\n"
            "to cycle 50% \u2192 75% \u2192 100% \u2192 50%"
        ),
        f"About {APP_NAME}",
        0x40,  # MB_ICONINFORMATION
    )


def _show_settings(icon: pystray.Icon, item: pystray.MenuItem) -> None:  # noqa: ARG001
    """Open the Settings window in a separate thread (tkinter mainloop)."""
    threading.Thread(target=_open_settings_window, daemon=True).start()


def _shutdown_process(delay_s: float = _TRAY_REMOVE_DELAY_S) -> None:
    """Exit the process after giving Windows time to remove the tray icon.

    ``os._exit()`` avoids tkinter ``StringVar`` GC on a non-main thread.
    A short delay lets pystray's message loop run ``NIM_DELETE`` before
    the process is killed (immediate ``os._exit`` leaves a ghost tray icon).
    """
    logger.info("Shutting down in %.2fs", delay_s)
    if delay_s > 0:
        time.sleep(delay_s)
    logger.info("Exiting process")
    os._exit(0)


def _exit_app(icon: pystray.Icon, item: pystray.MenuItem) -> None:  # noqa: ARG001
    """Stop the tray icon and terminate the process.

    Cleans up in the correct order:
      1. Unregister keyboard hooks (best-effort)
      2. Hide and stop the tray icon (must return from this callback first)
      3. Deferred ``os._exit`` so the shell can refresh the notification area

    ``os._exit()`` is still required (rather than ``sys.exit()``) because
    tkinter objects created in a daemon thread will cause
    ``RuntimeError: main thread is not in main loop`` during normal
    shutdown.
    """
    logger.info("Exit requested, cleaning up")
    # Best-effort: unhook keyboard before stopping the tray.
    # If this raises (e.g. hook already removed), just continue.
    try:
        keyboard.unhook_all_hotkeys()
    except Exception:  # pylint: disable=broad-except
        pass

    # Attempt to clean up any open settings window before exit.
    global _settings_window_open
    if _settings_window_open:
        _settings_window_open = False

    try:
        icon.visible = False
    except Exception:  # pylint: disable=broad-except
        pass
    icon.stop()
    # Do not os._exit here — the menu callback runs inside pystray's loop;
    # exiting immediately prevents Shell_NotifyIcon delete from being processed.
    threading.Thread(
        target=_shutdown_process,
        name="winsnap-shutdown",
        daemon=True,
    ).start()


def build_tray_icon() -> pystray.Icon:
    """Construct and return the pystray Icon object.

    Returns:
        A configured *pystray.Icon* instance (not yet running).
    """
    image = _load_tray_image()
    menu = pystray.Menu(
        pystray.MenuItem(f"About {APP_NAME}", _show_about),
        pystray.MenuItem("Settings", _show_settings),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", _exit_app),
    )
    return pystray.Icon(APP_NAME, image, APP_NAME, menu)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_hotkey_thread: Optional[threading.Thread] = None


def _run_hotkey_listener() -> None:
    """Register hotkeys and keep the listener alive.

    Monitors the keyboard library's internal threads (listening_thread and
    processing_thread). If either dies, reset the listener state and
    re-register all hotkeys.
    """
    global _hotkey_thread
    register_hotkeys()
    logger.info("Hotkey listener started")

    while True:
        time.sleep(3)
        if _hotkey_thread is not threading.current_thread():
            break  # A new thread replaced us — stop the old keep-alive

        listener = keyboard._listener
        lt_alive = listener.listening_thread.is_alive() if listener.listening_thread else False
        pt_alive = listener.processing_thread.is_alive() if listener.processing_thread else False

        if not lt_alive or not pt_alive:
            logger.warning("Keyboard listener thread died (listening=%s, processing=%s), restarting",
                           lt_alive, pt_alive)
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass
            # Force reset so start_if_necessary() will create new threads
            listener.listening = False
            try:
                register_hotkeys()
                logger.info("Hotkey listener restarted successfully")
            except Exception:
                logger.exception("Failed to restart hotkey listener")


def _start_hotkey_listener() -> None:
    """Start (or restart) the hotkey listener daemon thread."""
    global _hotkey_thread
    _hotkey_thread = threading.Thread(target=_run_hotkey_listener, daemon=True, name="hotkey-listener")
    _hotkey_thread.start()


def _tray_mainloop_with_restart() -> None:
    """Run the pystray tray icon event loop with automatic restart.

    pystray's internal ``_mainloop`` calls ``GetMessage`` which can return
    -1 on error.  When that happens the loop exits silently — no exception,
    no log — and ``icon.run()`` returns as if the user clicked Exit.  This
    function detects that case and recreates the tray icon so the app
    continues running.
    """
    global _tray_icon
    restart_count = 0
    max_restarts = 5

    while True:
        try:
            logger.info("Starting tray icon event loop (attempt %d)", restart_count + 1)
            _tray_icon.run()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Tray icon raised an exception")

        # If _exit_app was called, _shutdown_process will os._exit soon.
        # Don't restart in that case.
        if restart_count >= max_restarts:
            logger.error("Tray icon restarted %d times, giving up", max_restarts)
            break

        restart_count += 1
        logger.warning("Tray icon exited unexpectedly, restarting in 1s (attempt %d/%d)",
                        restart_count, max_restarts)
        time.sleep(1)

        try:
            _tray_icon = build_tray_icon()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to rebuild tray icon")
            break


def main() -> None:
    """Application entry point.

    1. Enables per-monitor DPI awareness.
    2. Loads configuration (or defaults).
    3. Generates icon.ico if not present.
    4. Registers global hotkeys on a background daemon thread.
    5. Runs the system-tray event loop (blocks until Exit is chosen).
    """
    global current_hotkeys, _tray_icon

    logger.info("=== %s v%s starting ===", APP_NAME, APP_VERSION)
    logger.info("APP_DIR: %s", APP_DIR)
    logger.info("CONFIG_PATH: %s", CONFIG_PATH)
    logger.info("ICON_PATH: %s", ICON_PATH)
    logger.info("LOG_PATH: %s", LOG_PATH)
    logger.info("Frozen: %s", getattr(sys, "frozen", False))

    _enable_dpi_awareness()
    _init_shell_hwnds()

    # Load saved configuration (or use defaults)
    current_hotkeys = load_config()

    # Generate icon.ico next to the executable / script if missing
    if not os.path.isfile(ICON_PATH):
        logger.info("Icon not found at %s, attempting generation", ICON_PATH)
        try:
            from icon import save_icon  # type: ignore[import]
            save_icon(ICON_PATH)
            logger.info("Icon generated at %s", ICON_PATH)
        except Exception:  # pylint: disable=broad-except
            logger.warning("Icon generation failed, fallback image will be used")

    # Start hotkey listener on a daemon thread so it doesn't block the tray
    _start_hotkey_listener()

    # Block on the tray icon loop (with auto-restart on silent exit)
    _tray_icon = build_tray_icon()
    _tray_mainloop_with_restart()

    # Normal exit path: icon.stop() returned (e.g. after Exit menu).
    logger.info("Tray icon stopped, shutting down")
    try:
        keyboard.unhook_all_hotkeys()
    except Exception:  # pylint: disable=broad-except
        pass
    _shutdown_process()


if __name__ == "__main__":
    main()
