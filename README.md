# WinSnap

> A lightweight Windows 10/11 window-snapping utility driven entirely by global hotkeys — with configurable shortcuts, incremental sizing, and a Settings window.

Two implementations: **Python** (original) and **Rust** (native Win32 rewrite).

---

## Feature Comparison

| Feature | Python | Rust |
|---------|--------|------|
| **Snap** left/right/top/bottom | ✅ | ✅ |
| **Center** (60% width) | ✅ | ✅ |
| **Full** work area | ✅ | ✅ |
| **Restore** to pre-snap position | ✅ | ✅ |
| **Incremental sizing** 50%→75%→100%→50% | ✅ | ✅ |
| **DWM invisible border** compensation | ✅ | ✅ |
| **DPI awareness** | per-monitor (`SetProcessDpiAwareness(2)`) | system-level (`SetProcessDPIAware`) |
| **Global hotkeys** | `keyboard` library (3rd-party) | Win32 `RegisterHotKey` (native) |
| **System tray** | `pystray` | Win32 `Shell_NotifyIconW` |
| **Settings window** | tkinter | Win32 native controls |
| **Config persistence** | `winsnap_config.json` | `winsnap_config.json` |
| **Key capture in settings** | tkinter `<Key>` bind | `WM_KEYDOWN` + `GetKeyState` |
| **Window identity tracking** `(pid, class, title)` | ✅ | ❌ |
| **Shell window filtering** | 6 window classes | 4 window classes |
| **Stale HWND cleanup** | ✅ | ❌ |
| **Logging** | `winsnap.log` | ❌ |

### Snap hotkeys

| Hotkey | Action | Incremental Sizing |
|--------|--------|--------------------|
| `Ctrl+Alt+Left` | Snap to **left half** | ✅ 50% → 75% → 100% → 50% |
| `Ctrl+Alt+Right` | Snap to **right half** | ✅ 50% → 75% → 100% → 50% |
| `Ctrl+Alt+Up` | Snap to **top half** | ✅ 50% → 75% → 100% → 50% |
| `Ctrl+Alt+Down` | Snap to **bottom half** | ✅ 50% → 75% → 100% → 50% |
| `Ctrl+Alt+C` | **Centre** window (60% width) | ❌ |
| `Ctrl+Alt+F` | **Full work area** | ❌ |
| `Ctrl+Alt+R` | **Restore** to pre-snap position | — |

> Default hotkeys shown. All are fully configurable via the Settings window.

All actions target the **active foreground window**. All sizes are relative to the **monitor's work area** (multi-monitor aware).

### Incremental sizing

When you press the same snap hotkey multiple times in a row, the window cycles through sizes:

- **Left / Right**: 50% → 75% → 100% (width) → back to 50%
- **Top / Bottom**: 50% → 75% → 100% (height) → back to 50%
- **Center / Full**: no incremental sizing

---

## Comparison at a glance

| Metric | Python | Rust |
|--------|--------|------|
| Binary size | ~15 MB (PyInstaller) | ~226 KB (release, LTO+strip) |
| Startup time | ~2 s | <100 ms |
| Memory usage | ~30 MB | ~1 MB |
| Dependencies | pywin32, keyboard, pystray, Pillow | none (Win32 FFI via windows-sys) |
| Environment | Python 3.11+ | Rust 2021 toolchain |
| Window hiding | N/A (console by default) | `#![windows_subsystem = "windows"]` |

---

## Setup

### Python

```powershell
pip install -r requirements.txt
python icon.py
python winsnap.py
```

### Rust

```powershell
cd rust_version/winsnap_rust
cargo build --release
.\target\release\winsnapper.exe
```

## Build standalone .exe

### Python

```powershell
build_exe.bat
# Output: dist/WinSnap.exe
```

### Rust

```powershell
cd rust_version/winsnap_rust
cargo build --release
# Output: target/release/winsnapper.exe
```

---

## Project structure

```
winsnap/
├── winsnap.py                  # Python main program
├── icon.py                     # Python icon generator
├── winsnap_config.json         # Config file (auto-created)
├── requirements.txt            # Python dependencies
├── build_exe.bat               # PyInstaller build script
├── unittests/                  # Python unit tests
├── docs/                       # Documentation
│   ├── bugfix-report-v1.1.0.md
│   └── rust-subsystem-guide.md
├── rust_version/
│   └── winsnap_rust/
│       ├── Cargo.toml
│       ├── src/main.rs         # Rust implementation (~1056 lines)
│       └── spec/
│           └── migration-status.md
└── README.md
```

---

## How it works

1. **DPI awareness** enabled at startup for correct physical pixel coordinates.
2. **Config** loaded from `winsnap_config.json` (auto-created with defaults).
3. **Hotkeys** registered globally — Python via `keyboard` daemon thread, Rust via Win32 `RegisterHotKey` system message loop.
4. On snap trigger: records original window rect, restores if maximized, checks incremental sizing level, queries `GetMonitorInfo` for the work area, calls `MoveWindow` with calculated geometry.
5. **Restore** hotkey reverts to the saved pre-snap position.
6. **Settings window** allows live hotkey reconfiguration — save persists to JSON and re-registers hotkeys immediately.
7. **System tray** — Python via `pystray`, Rust via `Shell_NotifyIconW`; no main window shown.

---

## Requirements

- Windows 10 or 11
- **Python version**: Python 3.11+
- **Rust version**: Rust 2021 edition toolchain (for building)

---

## License

MIT