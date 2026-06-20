# WinSnap — Agent Guide

## What this is

Windows system-tray utility that snaps windows to screen edges via global hotkeys. Two implementations:

- **Python** (`winsnap.py`, ~1080 lines) — original version, icon generator in `icon.py`.
- **Rust** (`rust_version/winsnap_rust/src/main.rs`, ~1056 lines) — native Win32 rewrite, no third-party GUI dependencies.

## Setup — Python

```powershell
pip install -r requirements.txt    # pywin32, keyboard, pystray, Pillow
python icon.py                    # generates icon/icon.ico (required)
python winsnap.py                 # runs (minimizes to tray)
```

Requires **Python 3.11+** and **Windows 10/11**. Some apps require **Run as Administrator** for hotkeys to work.

## Setup — Rust

```powershell
cd rust_version/winsnap_rust
cargo build --release
# Output: target/release/winsnapper.exe
```

Requires **Rust 2021 edition** toolchain. Binary is ~226KB (release, LTO+strip).

## Build — Python

```powershell
build_exe.bat                     # or build_exe.ps1
# Output: dist/WinSnap.exe
```

PyInstaller spec: `WinSnap.spec`. The `--hidden-import=tkinter` flag is required. Icon is bundled via `--add-data "icon\icon.ico;."`.

## Build — Rust

```powershell
cd rust_version/winsnap_rust
cargo build --release
# Output: target/release/winsnapper.exe
```

Cargo profile: `opt-level = "s"`, LTO enabled, symbols stripped.

## Key architecture notes

### Python version

- **Entry point**: `winsnap.py:main()` — enables DPI awareness, loads config, starts hotkey listener on daemon thread, blocks on pystray tray loop.
- **Config path**: `winsnap_config.json` (same dir as script). Gitignored; auto-created on first run with defaults.
- **Shutdown**: Uses `os._exit(0)` with a delay to avoid tkinter `StringVar` GC on non-main thread. Never use `sys.exit()` here.
- **Settings window**: tkinter, opened in a daemon thread via `_open_settings_window()`. Global `_settings_window_open` flag prevents duplicates.
- **DPI**: `SetProcessDpiAwareness(2)` called at startup — all Win32 geometry is in physical pixels.
- **Invisible borders**: Windows 10/11 DWM adds ~7-8px invisible frame. `get_border_offsets()` compensates via `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`.
- **Window identity**: Tracks `(pid, class_name, title)` to detect HWND reuse across processes. Stale state is pruned on each snap.
- **Icon path resolution**: Dev uses `icon/icon.ico`; frozen PyInstaller build uses `icon.ico` in `_MEIPASS`. See `_resolve_icon_path()`.

### Rust version

- **Entry point**: `main()` — sets DPI awareness, loads config, creates hidden message window, registers hotkeys via Win32 `RegisterHotKey`, creates tray icon via `Shell_NotifyIconW`, enters message loop.
- **Config path**: `winsnap_config.json` (same dir as exe), resolved via `std::env::current_exe()`.
- **Hotkeys**: Registered via Win32 `RegisterHotKey` — no daemon thread needed, handled by system message loop (`WM_HOTKEY`).
- **Settings window**: Win32 native controls (`CreateWindowExW`), lives in the same thread. State tracked via `SettingsState` struct behind `GWLP_USERDATA`.
- **DPI**: `SetProcessDPIAware()` (system-level DPI awareness, not per-monitor).
- **Invisible borders**: Same `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)` compensation.
- **Snap state**: `SnapState` behind `Arc<Mutex<>>` — stores `original_positions` and `last_snap` keyed by HWND (`isize`).
- **Icon**: GDI-drawn 16x16 orange square, created programmatically (no external .ico file).
- **Dependencies**: `windows-sys` (Win32 FFI), `serde`/`serde_json` (config), `log`/`fern`/`chrono` (logging).

## Migration status

The Rust version has **100% core feature parity** with Python:
- Snap (left/right/top/bottom/center/full), restore, incremental sizing (50%→75%→100%), DWM border compensation, DPI awareness, JSON config, system tray, settings window with key capture.

Not yet migrated (Python-only):
- Window identity tracking `(pid, class_name, title)`
- Full Shell window class filtering (only top-4 classes in Rust vs 6 in Python)
- `SetProcessDpiAwareness(2)` (per-monitor) — Rust uses `SetProcessDPIAware()` (system-level)

Rust advantages: 226KB binary vs ~15MB PyInstaller, <100ms startup vs ~2s, ~1MB RAM vs ~30MB, no monkey-patching needed.

Full comparison: `rust_version/winsnap_rust/spec/migration-status.md`.

## Known bug

- `winsnap.py:1057` imports `save_icon` from `icon.py` — but `icon.py` only defines `draw_icon`, `generate_svg`, `generate_all`, `main`. The `save_icon` function doesn't exist. This means auto-generation of the icon at runtime silently fails (caught by bare `except`). To fix: add a `save_icon(path)` wrapper to `icon.py`, or change the import in `winsnap.py`.

## Rules

- **After every code change, follow this sequence** before considering the task done:
  1. Run unit tests — `winsnap-venv\Scripts\python.exe -m unittest discover -s unittests -v`
  2. Run compile/build test — `build_exe.bat`
  3. Git commit (local only, do not push)
- **For Rust changes**: `cd rust_version/winsnap_rust && cargo build --release` then `cargo clippy` for lint.
- **Unit tests live in `unittests/`** — add new tests there, not scattered elsewhere.

## Gotchas

- `keyboard` library requires root/admin on some systems — hotkeys silently fail otherwise.
- `winsnap_config.json` is in `.gitignore` but a default version is tracked — edits to defaults should go in `DEFAULT_HOTKEYS` dict in code, not the JSON file.
- `tkinter` is stdlib on Windows but must be explicitly included in PyInstaller builds (`--hidden-import=tkinter`).
- The tray icon removal needs ~350ms delay before `os._exit()` or the icon ghosts in the notification area.
- Rust version uses `SetProcessDPIAware()` instead of `SetProcessDpiAwareness(2)` — may behave differently on multi-monitor setups with different DPI.
- Rust version uses `Arc<Mutex<SnapState>>` for thread safety (settings window runs in the same thread but state is shared via `GWLP_USERDATA`).
