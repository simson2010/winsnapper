# WinSnap v2

> A lightweight Windows 10/11 window-snapping utility driven entirely by global hotkeys — now with configurable shortcuts, incremental sizing, and a Settings window.

---

## Features

### Snap Hotkeys

| Hotkey | Action | Incremental Sizing |
|--------|--------|--------------------|
| `Ctrl+Alt+Left`  | Snap to **left half** | ✅ 50% → 75% → 100% → 50% |
| `Ctrl+Alt+Right` | Snap to **right half** | ✅ 50% → 75% → 100% → 50% |
| `Ctrl+Alt+Up`    | Snap to **top half** | ✅ 50% → 75% → 100% → 50% |
| `Ctrl+Alt+Down`  | Snap to **bottom half** | ✅ 50% → 75% → 100% → 50% |
| `Ctrl+Alt+C`     | **Centre** window (60% width) | ❌ |
| `Ctrl+Alt+F`     | **Full work area** | ❌ |
| `Ctrl+Alt+R`     | **Restore** to pre-snap position | — |

> **Default hotkeys shown above.** All hotkeys are fully configurable via the Settings window (see below).

All actions target the **currently active (foreground) window**.
All sizes are relative to the **work area of the monitor the window is on**, so multi-monitor setups are handled correctly.

### Incremental Sizing

When you press the same snap hotkey multiple times in a row, the window size increases progressively:

**Left / Right half:**
| Press | Width |
|-------|-------|
| 1st | 50% of screen width |
| 2nd | 75% of screen width |
| 3rd | 100% (full width) |
| 4th | Back to 50% (cycle) |

**Top / Bottom half:**
| Press | Height |
|-------|--------|
| 1st | 50% of screen height |
| 2nd | 75% of screen height |
| 3rd | 100% (full height) |
| 4th | Back to 50% (cycle) |

> Centre and Full are not affected by incremental sizing.

### Settings Window

- Open via the system-tray right-click menu → **Settings**
- View and modify all 7 hotkey bindings
- Click **Modify** next to any action, then press your desired key combination
- **Save** to persist changes to `winsnap_config.json` and re-register hotkeys immediately
- **Cancel** to discard changes
- Copyright info displayed at the bottom of the window

---

## Requirements

- Windows 10 or 11
- Python 3.11+

---

## Installation

```powershell
# 1. Clone / download the project
cd C:\Users\EricPan\WorkBuddy\2026-05-17-task-1\winsnap

# 2. Install dependencies
pip install -r requirements.txt

# 3. Generate the tray icon
python icon.py

# 4. Run WinSnap
python winsnap.py
```

The program minimises to the system tray immediately.
Right-click the tray icon for **About WinSnap**, **Settings**, or **Exit**.

---

## Configuration

WinSnap v2 stores hotkey configuration in `winsnap_config.json` (in the same directory as `winsnap.py`). On first launch the file is created automatically with default settings.

Example `winsnap_config.json`:
```json
{
  "hotkeys": {
    "left": "ctrl+alt+left",
    "right": "ctrl+alt+right",
    "top": "ctrl+alt+up",
    "bottom": "ctrl+alt+down",
    "center": "ctrl+alt+c",
    "full": "ctrl+alt+f",
    "restore": "ctrl+alt+r"
  }
}
```

You can edit this file directly (then restart WinSnap) or use the Settings window for a live update.

---

## Building a standalone .exe

```powershell
build_exe.bat
```

The compiled executable will be at `dist\WinSnap.exe`.
You can place it in your Startup folder to launch it automatically at login.

> Note: `tkinter` is included via `--hidden-import=tkinter` in the build script.

---

## Project structure

```
winsnap/
├── winsnap.py            # Main program — hotkeys, snap logic, tray icon, settings
├── icon.py               # Icon generator (Pillow) → produces icon.ico (window shape)
├── winsnap_config.json   # Persisted hotkey configuration (auto-created)
├── requirements.txt      # Python dependencies
├── build_exe.bat         # PyInstaller build script
└── README.md             # This file
```

---

## How it works

1. **DPI awareness** is enabled at startup so that all Win32 geometry calls return physical pixel coordinates on high-DPI displays.
2. **Configuration** is loaded from `winsnap_config.json` (or defaults if the file doesn't exist).
3. **Hotkeys** are registered globally via the `keyboard` library on a background daemon thread.
4. When a snap hotkey fires, WinSnap:
   - Records the window's current rect in `original_positions[hwnd]`.
   - Calls `ShowWindow(hwnd, SW_RESTORE)` to un-maximise if needed.
   - Checks `last_snap_state[hwnd]` to determine incremental sizing level.
   - Queries `GetMonitorInfo` for the **work area** of the monitor containing the window.
   - Calls `MoveWindow` with the calculated geometry (50%/75%/100% depending on level).
5. `Ctrl+Alt+R` (or the configured restore hotkey) looks up `original_positions[hwnd]` and calls `MoveWindow` to revert.
6. The **Settings window** (tkinter) allows live reconfiguration of hotkeys; saving writes `winsnap_config.json` and immediately re-registers hotkeys.
7. The **system tray** is powered by `pystray`; no main window is shown.

---

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| Hotkeys don't fire | Run WinSnap as Administrator (some apps capture keys at higher privilege) |
| Window snaps to wrong monitor | Ensure the window is actually in the foreground on that monitor before pressing the hotkey |
| `icon.ico` missing warning | Run `python icon.py` once to regenerate it |
| Build fails | Make sure `pyinstaller` is installed: `pip install pyinstaller` |
| Settings window doesn't open | Ensure `tkinter` is available (it ships with standard Python on Windows) |

---

## License

MIT — free to use, modify, and distribute.
