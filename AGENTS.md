# WinSnap — Agent Guide

## What this is

Single-file Windows system-tray utility (`winsnap.py`, ~1080 lines) that snaps windows to screen edges via global hotkeys. Icon generator in `icon.py`. No tests, no CI.

## Setup

```powershell
pip install -r requirements.txt    # pywin32, keyboard, pystray, Pillow
python icon.py                    # generates icon/icon.ico (required)
python winsnap.py                 # runs (minimizes to tray)
```

Requires **Python 3.11+** and **Windows 10/11**. Some apps require **Run as Administrator** for hotkeys to work.

## Build

```powershell
build_exe.bat                     # or build_exe.ps1
# Output: dist/WinSnap.exe
```

PyInstaller spec: `WinSnap.spec`. The `--hidden-import=tkinter` flag is required. Icon is bundled via `--add-data "icon\icon.ico;."`.

## Key architecture notes

- **Entry point**: `winsnap.py:main()` — enables DPI awareness, loads config, starts hotkey listener on daemon thread, blocks on pystray tray loop.
- **Config path**: `winsnap_config.json` (same dir as script). Gitignored; auto-created on first run with defaults.
- **Shutdown**: Uses `os._exit(0)` with a delay to avoid tkinter `StringVar` GC on non-main thread. Never use `sys.exit()` here.
- **Settings window**: tkinter, opened in a daemon thread via `_open_settings_window()`. Global `_settings_window_open` flag prevents duplicates.
- **DPI**: `SetProcessDpiAwareness(2)` called at startup — all Win32 geometry is in physical pixels.
- **Invisible borders**: Windows 10/11 DWM adds ~7-8px invisible frame. `get_border_offsets()` compensates via `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`.
- **Window identity**: Tracks `(pid, class_name, title)` to detect HWND reuse across processes. Stale state is pruned on each snap.
- **Icon path resolution**: Dev uses `icon/icon.ico`; frozen PyInstaller build uses `icon.ico` in `_MEIPASS`. See `_resolve_icon_path()`.

## Known bug

- `winsnap.py:1057` imports `save_icon` from `icon.py` — but `icon.py` only defines `draw_icon`, `generate_svg`, `generate_all`, `main`. The `save_icon` function doesn't exist. This means auto-generation of the icon at runtime silently fails (caught by bare `except`). To fix: add a `save_icon(path)` wrapper to `icon.py`, or change the import in `winsnap.py`.

## Rules

- **After every code change, follow this sequence** before considering the task done:
  1. Run unit tests — `winsnap-venv\Scripts\python.exe -m unittest discover -s unittests -v`
  2. Run compile/build test — `build_exe.bat`
  3. Git commit (local only, do not push)
- **Unit tests live in `unittests/`** — add new tests there, not scattered elsewhere.

## Gotchas

- `keyboard` library requires root/admin on some systems — hotkeys silently fail otherwise.
- `winsnap_config.json` is in `.gitignore` but a default version is tracked — edits to defaults should go in `DEFAULT_HOTKEYS` dict in code, not the JSON file.
- `tkinter` is stdlib on Windows but must be explicitly included in PyInstaller builds (`--hidden-import=tkinter`).
- The tray icon removal needs ~350ms delay before `os._exit()` or the icon ghosts in the notification area.
