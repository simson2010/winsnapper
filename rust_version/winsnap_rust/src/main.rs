use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use log::{debug, info, warn};
use serde::{Deserialize, Serialize};
use windows_sys::Win32::Foundation::*;
use windows_sys::Win32::Graphics::Dwm::*;
use windows_sys::Win32::Graphics::Gdi::*;
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::UI::Input::KeyboardAndMouse::*;
use windows_sys::Win32::UI::Shell::*;
use windows_sys::Win32::UI::WindowsAndMessaging::*;

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Hotkeys {
    left: String,
    right: String,
    top: String,
    bottom: String,
    center: String,
    full: String,
    restore: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Config {
    hotkeys: Hotkeys,
}

impl Default for Hotkeys {
    fn default() -> Self {
        Self {
            left: "ctrl+alt+left".into(),
            right: "ctrl+alt+right".into(),
            top: "ctrl+alt+up".into(),
            bottom: "ctrl+alt+down".into(),
            center: "ctrl+alt+c".into(),
            full: "ctrl+alt+f".into(),
            restore: "ctrl+alt+r".into(),
        }
    }
}

impl Default for Config {
    fn default() -> Self {
        Self {
            hotkeys: Hotkeys::default(),
        }
    }
}

fn config_path() -> PathBuf {
    let exe = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("."));
    exe.parent()
        .unwrap_or(&PathBuf::from("."))
        .join("winsnap_config.json")
}

fn load_config() -> Config {
    let path = config_path();
    info!("Loading config from {}", path.display());
    match fs::read_to_string(&path) {
        Ok(data) => {
            let config: Config = serde_json::from_str(&data).unwrap_or_default();
            info!("Config loaded: {:?}", config);
            config
        }
        Err(e) => {
            warn!("Failed to load config ({}), creating default", e);
            let config = Config::default();
            let json = serde_json::to_string_pretty(&config).unwrap();
            if let Err(e) = std::fs::write(&path, &json) {
                warn!("Failed to write default config to {}: {}", path.display(), e);
            } else {
                info!("Default config written to {}", path.display());
            }
            config
        }
    }
}

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------

fn log_path() -> PathBuf {
    let exe = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("."));
    exe.parent()
        .unwrap_or(&PathBuf::from("."))
        .join("winsnap.log")
}

fn setup_logging() {
    let path = log_path();
    let _ = fern::Dispatch::new()
        .format(|out, message, record| {
            let now = chrono_free_local_time();
            out.finish(format_args!("{} [{}] {}", now, record.level(), message))
        })
        .level(log::LevelFilter::Debug)
        .chain(fern::Dispatch::new().chain(std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .unwrap()))
        .apply();
}

/// Minimal local-time formatter using chrono.
/// Output: "2026-06-20 14:30:15"
fn chrono_free_local_time() -> String {
    chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string()
}

// ---------------------------------------------------------------------------
// Embedded icon
// ---------------------------------------------------------------------------

const ICON_DATA: &[u8] = include_bytes!("..\\icon\\icon.ico");

/// Parse embedded .ico data and create an HICON.
/// Writes to a temp file and loads via LoadImageW for reliable parsing.
unsafe fn load_embedded_icon() -> HICON {
    let temp_path = std::env::temp_dir().join("winsnap_icon.ico");
    if std::fs::write(&temp_path, ICON_DATA).is_err() {
        return std::ptr::null_mut();
    }
    let wide = to_wide(temp_path.to_str().unwrap_or(""));
    let hicon = LoadImageW(
        std::ptr::null_mut(),
        wide.as_ptr(),
        IMAGE_ICON,
        0,
        0,
        LR_LOADFROMFILE | LR_DEFAULTSIZE,
    ) as HICON;
    let _ = std::fs::remove_file(&temp_path);
    hicon
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ID_LEFT: u32 = 1;
const ID_RIGHT: u32 = 2;
const ID_TOP: u32 = 3;
const ID_BOTTOM: u32 = 4;
const ID_CENTER: u32 = 5;
const ID_FULL: u32 = 6;
const ID_RESTORE: u32 = 7;
const WM_TRAYICON: u32 = WM_USER + 1;
const IDM_ABOUT: u32 = 1001;
const IDM_SETTINGS: u32 = 1003;
const IDM_EXIT: u32 = 1002;

// Settings window control IDs
const IDC_ACTION_BASE: u32 = 2000; // +i: edit control for action i
const IDC_MODIFY_BASE: u32 = 3000; // +i: modify button for action i
const IDC_SAVE: u32 = 4000;
const IDC_CANCEL: u32 = 4001;

#[allow(dead_code)]
const ACTION_ORDER: [&str; 7] = ["left", "right", "top", "bottom", "center", "full", "restore"];

#[allow(dead_code)]
const ACTION_LABELS: [&str; 7] = [
    "Left half",
    "Right half",
    "Top half",
    "Bottom half",
    "Centre (60% width)",
    "Full work area",
    "Restore previous position",
];

// ---------------------------------------------------------------------------
// Window snap state
// ---------------------------------------------------------------------------

struct SnapState {
    original_positions: HashMap<isize, (i32, i32, i32, i32)>,
    last_snap: HashMap<isize, (String, usize)>,
}

impl SnapState {
    fn new() -> Self {
        Self {
            original_positions: HashMap::new(),
            last_snap: HashMap::new(),
        }
    }
}

// ---------------------------------------------------------------------------
// Win32 helpers
// ---------------------------------------------------------------------------

unsafe fn get_work_area(hwnd: HWND) -> (i32, i32, i32, i32) {
    let monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
    let mut mi: MONITORINFO = std::mem::zeroed();
    mi.cbSize = std::mem::size_of::<MONITORINFO>() as u32;
    GetMonitorInfoW(monitor, &mut mi);
    let r = &mut mi.rcWork;
    (r.left, r.top, r.right, r.bottom)
}

unsafe fn get_border_offsets(hwnd: HWND) -> (i32, i32, i32, i32) {
    let mut win_rect: RECT = std::mem::zeroed();
    if GetWindowRect(hwnd, &mut win_rect) == 0 {
        return (0, 0, 0, 0);
    }

    let mut frame: RECT = std::mem::zeroed();
    let hr = DwmGetWindowAttribute(
        hwnd,
        DWMWA_EXTENDED_FRAME_BOUNDS as u32,
        &mut frame as *mut _ as *mut _,
        std::mem::size_of::<RECT>() as u32,
    );
    if hr != 0 {
        return (0, 0, 0, 0);
    }

    let bl = (frame.left - win_rect.left).max(0);
    let bt = (frame.top - win_rect.top).max(0);
    let br = (win_rect.right - frame.right).max(0);
    let bb = (win_rect.bottom - frame.bottom).max(0);
    (bl, bt, br, bb)
}

unsafe fn is_snapifiable(hwnd: HWND) -> bool {
    if hwnd.is_null() {
        return false;
    }
    if IsWindow(hwnd) == 0 {
        return false;
    }
    if IsWindowVisible(hwnd) == 0 {
        return false;
    }
    let mut buf = [0u16; 256];
    GetClassNameW(hwnd, buf.as_mut_ptr(), 256);
    let class = String::from_utf16_lossy(&buf);
    let shell_classes = ["Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"];
    if shell_classes.iter().any(|c| class.starts_with(*c)) {
        return false;
    }
    true
}

// ---------------------------------------------------------------------------
// Snap logic
// ---------------------------------------------------------------------------

const INCREMENT_PCT: [f64; 3] = [0.50, 0.75, 1.00];

unsafe fn snap_window(position: &str, state: &mut SnapState) {
    info!("snap_window({}) triggered", position);
    let hwnd = GetForegroundWindow();
    if !is_snapifiable(hwnd) {
        debug!("snap_window({}): hwnd {:?} not snapifiable, skipping", position, hwnd);
        return;
    }

    let mut rect: RECT = std::mem::zeroed();
    if GetWindowRect(hwnd, &mut rect) != 0 {
        state
            .original_positions
            .insert(hwnd as isize, (rect.left, rect.top, rect.right, rect.bottom));
    }

    let _ = ShowWindow(hwnd, SW_RESTORE);

    let (wx, wy, wr, wb) = get_work_area(hwnd);
    let w = wr - wx;
    let h = wb - wy;
    let (bl, bt, br, bb) = get_border_offsets(hwnd);

    let level = if matches!(position, "left" | "right" | "top" | "bottom") {
        if let Some((prev_dir, prev_level)) = state.last_snap.get(&(hwnd as isize)) {
            if prev_dir == position {
                (prev_level + 1) % 3
            } else {
                0
            }
        } else {
            0
        }
    } else {
        0
    };

    if matches!(position, "left" | "right" | "top" | "bottom") {
        state
            .last_snap
            .insert(hwnd as isize, (position.to_string(), level));
    }

    let (width_pct, height_pct) = match position {
        "left" | "right" => (INCREMENT_PCT[level], 1.0),
        "top" | "bottom" => (1.0, INCREMENT_PCT[level]),
        "center" => (0.60, 1.0),
        "full" => (1.0, 1.0),
        _ => return,
    };

    let pw = (w as f64 * width_pct) as i32;
    let ph = (h as f64 * height_pct) as i32;

    // --- Compensate for the invisible DWM border ---
    // MoveWindow positions the *outer* rect (including the invisible
    // frame). To make the visible content flush with a screen edge we
    // must nudge the window *past* that edge by the border width, and
    // enlarge the window so the visible size remains correct.
    //
    // Diagram (left snap, borders exaggerated):
    //   screen edge  |BL  visible content  BR|
    //   ────────────┤                       │
    //   x = wx - BL │  pw = pw + BL + BR    │
    let (x, y, final_w, final_h) = match position {
        "left" => {
            // Visible left edge flush with screen left
            // y stays at wy (Python does NOT subtract bt for left/right)
            let x = wx - bl;
            (x, wy, pw + bl + br, ph + bt + bb)
        }
        "right" => {
            // Visible right edge flush with screen right
            let pw_adj = pw + bl + br;
            let x = wx + w + br - pw_adj;
            (x, wy, pw_adj, ph + bt + bb)
        }
        "top" => {
            // Visible top edge flush with screen top
            let y = wy - bt;
            (wx, y, pw + bl + br, ph + bt + bb)
        }
        "bottom" => {
            // Visible bottom edge flush with work-area bottom (above taskbar)
            let ph_adj = ph + bt + bb;
            let y = wb + bb - ph_adj;
            (wx, y, pw + bl + br, ph_adj)
        }
        "full" => {
            // All edges flush
            (wx - bl, wy - bt, pw + bl + br, ph + bt + bb)
        }
        "center" => {
            // Centre doesn't touch screen edges, but compensate borders
            (wx + (w - pw) / 2, wy, pw + bl + br, ph + bt + bb)
        }
        _ => return,
    };

    let _ = MoveWindow(hwnd, x, y, final_w, final_h, 1);
    info!(
        "snap_window({}): hwnd={:?} level={} -> ({}, {}, {}, {})",
        position, hwnd, level, x, y, final_w, final_h
    );
}

unsafe fn restore_window(state: &mut SnapState) {
    info!("restore_window() triggered");
    let hwnd = GetForegroundWindow();
    if !is_snapifiable(hwnd) {
        debug!("restore_window: hwnd {:?} not snapifiable, skipping", hwnd);
        return;
    }

    if let Some((left, top, right, bottom)) = state.original_positions.remove(&(hwnd as isize)) {
        state.last_snap.remove(&(hwnd as isize));
        let _ = ShowWindow(hwnd, SW_RESTORE);
        let _ = MoveWindow(hwnd, left, top, right - left, bottom - top, 1);
        info!(
            "restore_window: hwnd={:?} -> ({}, {}, {}, {})",
            hwnd, left, top, right, bottom
        );
    } else {
        debug!("restore_window: hwnd {:?} has no saved position", hwnd);
    }
}

// ---------------------------------------------------------------------------
// Hotkey parsing
// ---------------------------------------------------------------------------

fn parse_hotkey(combo: &str) -> Option<(u32, u32)> {
    let mut modifiers: u32 = 0;
    let mut vk: u32 = 0;

    for part in combo.split('+') {
        match part.to_lowercase().as_str() {
            "ctrl" | "control" => modifiers |= MOD_CONTROL,
            "alt" => modifiers |= MOD_ALT,
            "shift" => modifiers |= MOD_SHIFT,
            "win" | "super" | "windows" => modifiers |= MOD_WIN,
            "left" => vk = VK_LEFT as u32,
            "right" => vk = VK_RIGHT as u32,
            "up" => vk = VK_UP as u32,
            "down" => vk = VK_DOWN as u32,
            "c" => vk = 0x43,
            "f" => vk = 0x46,
            "r" => vk = 0x52,
            "a" => vk = 0x41,
            "b" => vk = 0x42,
            "d" => vk = 0x44,
            "e" => vk = 0x45,
            "g" => vk = 0x47,
            "h" => vk = 0x48,
            "i" => vk = 0x49,
            "j" => vk = 0x4A,
            "k" => vk = 0x4B,
            "l" => vk = 0x4C,
            "m" => vk = 0x4D,
            "n" => vk = 0x4E,
            "o" => vk = 0x4F,
            "p" => vk = 0x50,
            "q" => vk = 0x51,
            "s" => vk = 0x53,
            "t" => vk = 0x54,
            "u" => vk = 0x55,
            "v" => vk = 0x56,
            "w" => vk = 0x57,
            "x" => vk = 0x58,
            "y" => vk = 0x59,
            "z" => vk = 0x5A,
            "enter" | "return" => vk = VK_RETURN as u32,
            "space" => vk = VK_SPACE as u32,
            "escape" | "esc" => vk = VK_ESCAPE as u32,
            "tab" => vk = VK_TAB as u32,
            "delete" | "del" => vk = VK_DELETE as u32,
            "home" => vk = VK_HOME as u32,
            "end" => vk = VK_END as u32,
            "pageup" | "page_up" => vk = VK_PRIOR as u32,
            "pagedown" | "page_down" => vk = VK_NEXT as u32,
            "insert" | "ins" => vk = VK_INSERT as u32,
            "f1" => vk = VK_F1 as u32,
            "f2" => vk = VK_F2 as u32,
            "f3" => vk = VK_F3 as u32,
            "f4" => vk = VK_F4 as u32,
            "f5" => vk = VK_F5 as u32,
            "f6" => vk = VK_F6 as u32,
            "f7" => vk = VK_F7 as u32,
            "f8" => vk = VK_F8 as u32,
            "f9" => vk = VK_F9 as u32,
            "f10" => vk = VK_F10 as u32,
            "f11" => vk = VK_F11 as u32,
            "f12" => vk = VK_F12 as u32,
            _ => return None,
        }
    }

    if modifiers == 0 || vk == 0 {
        return None;
    }

    Some((modifiers, vk))
}

// ---------------------------------------------------------------------------
// VK code to keyboard-library string (inverse of parse_hotkey)
// ---------------------------------------------------------------------------

fn vk_to_string(vk: u32) -> Option<String> {
    let s = match vk as u16 {
        VK_LEFT => "left",
        VK_RIGHT => "right",
        VK_UP => "up",
        VK_DOWN => "down",
        VK_RETURN => "enter",
        VK_SPACE => "space",
        VK_ESCAPE => "esc",
        VK_TAB => "tab",
        VK_DELETE => "delete",
        VK_HOME => "home",
        VK_END => "end",
        VK_PRIOR => "page up",
        VK_NEXT => "page down",
        VK_INSERT => "insert",
        VK_F1 => "f1",
        VK_F2 => "f2",
        VK_F3 => "f3",
        VK_F4 => "f4",
        VK_F5 => "f5",
        VK_F6 => "f6",
        VK_F7 => "f7",
        VK_F8 => "f8",
        VK_F9 => "f9",
        VK_F10 => "f10",
        VK_F11 => "f11",
        VK_F12 => "f12",
        _ => {
            // A-Z (0x41-0x5A) and 0-9 (0x30-0x39)
            if (0x41..=0x5A).contains(&(vk as u16)) {
                return Some(((vk as u8 as char).to_ascii_lowercase()).to_string());
            }
            if (0x30..=0x39).contains(&(vk as u16)) {
                return Some((vk as u8 as char).to_string());
            }
            return None;
        }
    };
    Some(s.to_string())
}

/// Build a hotkey string from a vk code + current modifier state.
/// Returns None if no modifier is pressed (we require at least one).
fn build_hotkey_string(vk: u32) -> Option<String> {
    let mut parts: Vec<String> = Vec::new();

    unsafe {
        if (GetKeyState(VK_CONTROL as i32) as u16) & 0x8000 != 0 {
            parts.push("ctrl".into());
        }
        if (GetKeyState(VK_MENU as i32) as u16) & 0x8000 != 0 {
            parts.push("alt".into());
        }
        if (GetKeyState(VK_SHIFT as i32) as u16) & 0x8000 != 0 {
            parts.push("shift".into());
        }
    }

    // Require at least one modifier
    if parts.is_empty() {
        return None;
    }

    let key_part = vk_to_string(vk)?;
    parts.push(key_part);
    Some(parts.join("+"))
}

// ---------------------------------------------------------------------------
// Settings window state
// ---------------------------------------------------------------------------

struct SettingsState {
    /// Working copy of hotkeys being edited (7 entries)
    working_hotkeys: [String; 7],
    /// Index of action currently being captured (None if not capturing)
    capturing: Option<usize>,
    /// Main window HWND (for re-registering hotkeys on save)
    main_hwnd: HWND,
    /// Edit control HWNDs (for updating display)
    edit_hwnds: [HWND; 7],
    /// Modify button HWNDs (for changing text to "Cancel")
    btn_hwnds: [HWND; 7],
    /// System font handle (deleted on WM_DESTROY)
    font: HFONT,
}

// ---------------------------------------------------------------------------
// Wide string helper
// ---------------------------------------------------------------------------

fn to_wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

fn loword(l: usize) -> u32 {
    (l & 0xFFFF) as u32
}

fn hiword(l: usize) -> u32 {
    ((l >> 16) & 0xFFFF) as u32
}

// ---------------------------------------------------------------------------
// Window procedure
// ---------------------------------------------------------------------------

unsafe extern "system" fn wnd_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match msg {
        WM_TRAYICON => {
            let event = (lparam & 0xFFFF) as u32;
            match event {
                WM_RBUTTONUP => {
                    let menu = CreatePopupMenu();
                    let about = to_wide("About WinSnap");
                    let settings = to_wide("Settings");
                    let exit = to_wide("Exit");
                    AppendMenuW(menu, MF_STRING, IDM_ABOUT as usize, about.as_ptr());
                    AppendMenuW(menu, MF_STRING, IDM_SETTINGS as usize, settings.as_ptr());
                    AppendMenuW(menu, MF_SEPARATOR, 0, std::ptr::null());
                    AppendMenuW(menu, MF_STRING, IDM_EXIT as usize, exit.as_ptr());

                    let mut point = POINT { x: 0, y: 0 };
                    GetCursorPos(&mut point);
                    SetForegroundWindow(hwnd);
                    let cmd = TrackPopupMenu(
                        menu,
                        TPM_RETURNCMD | TPM_RIGHTBUTTON,
                        point.x,
                        point.y,
                        0,
                        hwnd,
                        std::ptr::null(),
                    );
                    let _ = DestroyMenu(menu);

                    match cmd as u32 {
                        IDM_EXIT => {
                            info!("Exit requested, cleaning up");
                            PostQuitMessage(0);
                        }
                        IDM_ABOUT => {
                            let text = to_wide("WinSnap v1.1.0\n\nGlobal hotkeys for window snapping.\n\nhttps://github.com/simson2010/winsnapper");
                            let title = to_wide("About WinSnap");
                            MessageBoxW(hwnd, text.as_ptr(), title.as_ptr(), MB_OK);
                        }
                        IDM_SETTINGS => {
                            info!("Opening settings window");
                            let config = load_config();
                            open_settings_window(hwnd, &config);
                        }
                        _ => {}
                    }
                }
                _ => {}
            }
            0
        }
        WM_HOTKEY => {
            let id = wparam as u32;
            let state_ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA);
            if state_ptr != 0 {
                let state = &mut *(state_ptr as *mut Arc<Mutex<SnapState>>);
                let mut state = state.lock().unwrap();
                match id {
                    ID_LEFT => snap_window("left", &mut state),
                    ID_RIGHT => snap_window("right", &mut state),
                    ID_TOP => snap_window("top", &mut state),
                    ID_BOTTOM => snap_window("bottom", &mut state),
                    ID_CENTER => snap_window("center", &mut state),
                    ID_FULL => snap_window("full", &mut state),
                    ID_RESTORE => restore_window(&mut state),
                    _ => {}
                }
            }
            0
        }
        WM_CREATE => {
            let cs = &*(lparam as *const CREATESTRUCTW);
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, cs.lpCreateParams as isize);
            0
        }
        WM_DESTROY => {
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

/// Get the system default font handle. Caller must call `DeleteObject` when done.
unsafe fn get_system_font() -> HFONT {
    let mut ncm: NONCLIENTMETRICSW = std::mem::zeroed();
    ncm.cbSize = std::mem::size_of::<NONCLIENTMETRICSW>() as u32;
    SystemParametersInfoW(
        SPI_GETNONCLIENTMETRICS,
        ncm.cbSize,
        &mut ncm as *mut _ as *mut _,
        0,
    );
    CreateFontIndirectW(&ncm.lfMessageFont)
}

/// Send WM_SETFONT to a child window.
unsafe fn set_child_font(hwnd: HWND, font: HFONT) {
    SendMessageW(hwnd, WM_SETFONT, font as usize, 1);
}

// ---------------------------------------------------------------------------
// Settings window
// ---------------------------------------------------------------------------

/// Register the settings window class (called once).
unsafe fn register_settings_class() {
    let class_name = to_wide("WinSnapSettings");
    let mut wc: WNDCLASSW = std::mem::zeroed();
    wc.lpfnWndProc = Some(settings_wnd_proc);
    wc.hInstance = GetModuleHandleW(std::ptr::null());
    wc.lpszClassName = class_name.as_ptr();
    wc.hbrBackground = (COLOR_WINDOW + 1) as _;
    RegisterClassW(&wc);
}

/// Open the settings window. `main_hwnd` is needed to re-register hotkeys.
unsafe fn open_settings_window(main_hwnd: HWND, config: &Config) {
    register_settings_class();

    let working_hotkeys = [
        config.hotkeys.left.clone(),
        config.hotkeys.right.clone(),
        config.hotkeys.top.clone(),
        config.hotkeys.bottom.clone(),
        config.hotkeys.center.clone(),
        config.hotkeys.full.clone(),
        config.hotkeys.restore.clone(),
    ];

    let state = Box::new(SettingsState {
        working_hotkeys,
        capturing: None,
        main_hwnd,
        edit_hwnds: [std::ptr::null_mut(); 7],
        btn_hwnds: [std::ptr::null_mut(); 7],
        font: get_system_font(),
    });

    let class_name = to_wide("WinSnapSettings");
    let title = to_wide("WinSnap Settings");
    let win_w = 480i32;
    let win_h = 420i32;
    let screen_w = GetSystemMetrics(SM_CXSCREEN);
    let screen_h = GetSystemMetrics(SM_CYSCREEN);
    let x = (screen_w - win_w) / 2;
    let y = (screen_h - win_h) / 2;
    CreateWindowExW(
        0,
        class_name.as_ptr(),
        title.as_ptr(),
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_VISIBLE,
        x,
        y,
        win_w,
        win_h,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        GetModuleHandleW(std::ptr::null()),
        Box::into_raw(state) as *const _,
    );

    // Force the tray menu to dismiss (standard tray icon practice)
    SetForegroundWindow(main_hwnd);
}

unsafe extern "system" fn settings_wnd_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match msg {
        WM_CREATE => {
            let cs = &*(lparam as *const CREATESTRUCTW);
            let state_ptr = cs.lpCreateParams;
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, state_ptr as isize);

            let state = &mut *(state_ptr as *mut SettingsState);
            let hinst = GetModuleHandleW(std::ptr::null());
            let font = state.font;

            // Header labels
            let headers = ["Action", "Hotkey", ""];
            for (col, text) in headers.iter().enumerate() {
                let w = to_wide(text);
                let h = CreateWindowExW(
                    0,
                    to_wide("STATIC").as_ptr(),
                    w.as_ptr(),
                    WS_CHILD | WS_VISIBLE,
                    15 + (col as i32) * 160,
                    10,
                    150,
                    20,
                    hwnd,
                    (0x9000 + col as usize) as _,
                    hinst,
                    std::ptr::null(),
                );
                set_child_font(h, font);
            }

            // 7 rows: label + edit + modify button
            for i in 0..7 {
                let y = 35 + i as i32 * 32;

                // Action label
                let label = to_wide(ACTION_LABELS[i]);
                let lbl = CreateWindowExW(
                    0,
                    to_wide("STATIC").as_ptr(),
                    label.as_ptr(),
                    WS_CHILD | WS_VISIBLE,
                    15,
                    y + 3,
                    150,
                    20,
                    hwnd,
                    (0x9100 + i) as _,
                    hinst,
                    std::ptr::null(),
                );
                set_child_font(lbl, font);

                // Edit (read-only display of current hotkey)
                let edit_text = to_wide(&state.working_hotkeys[i]);
                let edit_hwnd = CreateWindowExW(
                    WS_EX_CLIENTEDGE,
                    to_wide("EDIT").as_ptr(),
                    edit_text.as_ptr(),
                    WS_CHILD | WS_VISIBLE,
                    175,
                    y,
                    150,
                    24,
                    hwnd,
                    (IDC_ACTION_BASE + i as u32) as _,
                    hinst,
                    std::ptr::null(),
                );
                state.edit_hwnds[i] = edit_hwnd;
                set_child_font(edit_hwnd, font);

                // Modify button
                let btn_text = to_wide("Modify");
                let btn_hwnd = CreateWindowExW(
                    0,
                    to_wide("BUTTON").as_ptr(),
                    btn_text.as_ptr(),
                    WS_CHILD | WS_VISIBLE,
                    335,
                    y,
                    80,
                    24,
                    hwnd,
                    (IDC_MODIFY_BASE + i as u32) as _,
                    hinst,
                    std::ptr::null(),
                );
                state.btn_hwnds[i] = btn_hwnd;
                set_child_font(btn_hwnd, font);
            }

            // Separator
            let sep = CreateWindowExW(
                0,
                to_wide("STATIC").as_ptr(),
                to_wide("").as_ptr(),
                WS_CHILD | WS_VISIBLE,
                10,
                270,
                440,
                2,
                hwnd,
                0x9200 as _,
                hinst,
                std::ptr::null(),
            );
            set_child_font(sep, font);

            // Save and Cancel buttons
            let save_text = to_wide("Save");
            let save_btn = CreateWindowExW(
                0,
                to_wide("BUTTON").as_ptr(),
                save_text.as_ptr(),
                WS_CHILD | WS_VISIBLE,
                280,
                285,
                80,
                28,
                hwnd,
                IDC_SAVE as _,
                hinst,
                std::ptr::null(),
            );
            set_child_font(save_btn, font);
            let cancel_text = to_wide("Cancel");
            let cancel_btn = CreateWindowExW(
                0,
                to_wide("BUTTON").as_ptr(),
                cancel_text.as_ptr(),
                WS_CHILD | WS_VISIBLE,
                370,
                285,
                80,
                28,
                hwnd,
                IDC_CANCEL as _,
                hinst,
                std::ptr::null(),
            );
            set_child_font(cancel_btn, font);

            // Copyright
            let copyright = to_wide("WinSnap v1.1.0  |  MIT License");
            let cpy = CreateWindowExW(
                0,
                to_wide("STATIC").as_ptr(),
                copyright.as_ptr(),
                WS_CHILD | WS_VISIBLE,
                15,
                325,
                400,
                20,
                hwnd,
                0x9300 as _,
                hinst,
                std::ptr::null(),
            );
            set_child_font(cpy, font);

            0
        }
        WM_COMMAND => {
            let cmd_id = loword(wparam) as u32;
            let cmd_type = hiword(wparam) as u32;
            let state_ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA);
            if state_ptr == 0 {
                return 0;
            }
            let state = &mut *(state_ptr as *mut SettingsState);

            // Modify button clicked
            if cmd_type == BN_CLICKED {
                if cmd_id == IDC_SAVE {
                    // Save: write config and re-register hotkeys
                    info!("Settings Save clicked");
                    let config = Config {
                        hotkeys: Hotkeys {
                            left: state.working_hotkeys[0].clone(),
                            right: state.working_hotkeys[1].clone(),
                            top: state.working_hotkeys[2].clone(),
                            bottom: state.working_hotkeys[3].clone(),
                            center: state.working_hotkeys[4].clone(),
                            full: state.working_hotkeys[5].clone(),
                            restore: state.working_hotkeys[6].clone(),
                        },
                    };
                    let json = serde_json::to_string_pretty(&config).unwrap();
                    let _ = std::fs::write(config_path(), json);

                    // Re-register hotkeys on the main window
                    let main_hwnd = state.main_hwnd;
                    // Unregister all
                    for id in [
                        ID_LEFT, ID_RIGHT, ID_TOP, ID_BOTTOM, ID_CENTER, ID_FULL, ID_RESTORE,
                    ] {
                        let _ = UnregisterHotKey(main_hwnd, id as i32);
                    }
                    // Re-register
                    for (i, id) in [
                        ID_LEFT, ID_RIGHT, ID_TOP, ID_BOTTOM, ID_CENTER, ID_FULL, ID_RESTORE,
                    ]
                    .iter()
                    .enumerate()
                    {
                        if let Some((mods, vk)) = parse_hotkey(&state.working_hotkeys[i]) {
                            let _ = RegisterHotKey(main_hwnd, *id as i32, mods, vk);
                            info!("Hotkey registered: {} -> {}", &state.working_hotkeys[i], id);
                        } else {
                            warn!("Invalid hotkey format: {}", &state.working_hotkeys[i]);
                        }
                    }

                    DestroyWindow(hwnd);
                    return 0;
                }
                if cmd_id == IDC_CANCEL {
                    info!("Settings Cancel clicked");
                    DestroyWindow(hwnd);
                    return 0;
                }
                // Modify button for an action
                if (IDC_MODIFY_BASE..IDC_MODIFY_BASE + 7).contains(&cmd_id) {
                    let idx = (cmd_id - IDC_MODIFY_BASE) as usize;
                    if state.capturing == Some(idx) {
                        // Already capturing this one — cancel
                        state.capturing = None;
                        let text = to_wide("Modify");
                        SetWindowTextW(state.btn_hwnds[idx], text.as_ptr());
                        let cur = to_wide(&state.working_hotkeys[idx]);
                        SetWindowTextW(state.edit_hwnds[idx], cur.as_ptr());
                    } else {
                        // Cancel any previous capture
                        if let Some(prev) = state.capturing {
                            let text = to_wide("Modify");
                            SetWindowTextW(state.btn_hwnds[prev], text.as_ptr());
                            let cur = to_wide(&state.working_hotkeys[prev]);
                            SetWindowTextW(state.edit_hwnds[prev], cur.as_ptr());
                        }
                        // Start capturing
                        state.capturing = Some(idx);
                        let text = to_wide("Cancel");
                        SetWindowTextW(state.btn_hwnds[idx], text.as_ptr());
                        let prompt = to_wide("Press new shortcut...");
                        SetWindowTextW(state.edit_hwnds[idx], prompt.as_ptr());
                        SetFocus(hwnd);
                    }
                    return 0;
                }
            }
            0
        }
        WM_KEYDOWN | WM_SYSKEYDOWN => {
            // Capture a new hotkey if in capture mode
            let state_ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA);
            if state_ptr == 0 {
                return 0;
            }
            let state = &mut *(state_ptr as *mut SettingsState);

            if let Some(idx) = state.capturing {
                let vk = wparam as u32;

                // Escape with no modifiers → cancel capture
                let ctrl_down = (GetKeyState(VK_CONTROL as i32) as u16) & 0x8000 != 0;
                let alt_down = (GetKeyState(VK_MENU as i32) as u16) & 0x8000 != 0;
                let shift_down = (GetKeyState(VK_SHIFT as i32) as u16) & 0x8000 != 0;

                if vk == VK_ESCAPE as u32 && !ctrl_down && !alt_down && !shift_down {
                    state.capturing = None;
                    let text = to_wide("Modify");
                    SetWindowTextW(state.btn_hwnds[idx], text.as_ptr());
                    let cur = to_wide(&state.working_hotkeys[idx]);
                    SetWindowTextW(state.edit_hwnds[idx], cur.as_ptr());
                    return 0;
                }

                // Skip standalone modifier presses
                if matches!(
                    vk as u16,
                    VK_CONTROL | VK_LCONTROL | VK_RCONTROL
                        | VK_MENU | VK_LMENU | VK_RMENU
                        | VK_SHIFT | VK_LSHIFT | VK_RSHIFT
                ) {
                    return 0;
                }

                // Build the hotkey string
                if let Some(combo) = build_hotkey_string(vk) {
                    // Validate via parse_hotkey
                    if parse_hotkey(&combo).is_some() {
                        state.working_hotkeys[idx] = combo.clone();
                        state.capturing = None;
                        let text = to_wide("Modify");
                        SetWindowTextW(state.btn_hwnds[idx], text.as_ptr());
                        let display = to_wide(&combo);
                        SetWindowTextW(state.edit_hwnds[idx], display.as_ptr());
                    }
                }
                return 0;
            }
            0
        }
        WM_CLOSE => {
            DestroyWindow(hwnd);
            0
        }
        WM_DESTROY => {
            // Free the SettingsState and font
            let state_ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA);
            if state_ptr != 0 {
                let state = Box::from_raw(state_ptr as *mut SettingsState);
                DeleteObject(state.font as _);
                SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
            }
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

fn main() {
    unsafe {
        setup_logging();
        info!("=== WinSnap v1.1.0 starting ===");
        info!("EXE: {:?}", std::env::current_exe().unwrap_or_default());
        info!("CONFIG: {:?}", config_path());
        info!("LOG: {:?}", log_path());

        // Enable per-monitor DPI awareness — must be done before any Win32
        // geometry calls, otherwise GetWindowRect returns logical (virtualized)
        // pixels while DwmGetWindowAttribute returns physical pixels, causing
        // border offset calculations to be wrong and windows to overflow.
        SetProcessDPIAware();
        info!("DPI awareness: SetProcessDPIAware (system-level)");

        let config = load_config();
        let state = Arc::new(Mutex::new(SnapState::new()));

        let class_name = to_wide("WinSnapMsg");
        let mut wc: WNDCLASSW = std::mem::zeroed();
        wc.lpfnWndProc = Some(wnd_proc);
        wc.hInstance = GetModuleHandleW(std::ptr::null());
        wc.lpszClassName = class_name.as_ptr();
        RegisterClassW(&wc);

        let hwnd = CreateWindowExW(
            0,
            class_name.as_ptr(),
            to_wide("WinSnap").as_ptr(),
            WS_OVERLAPPEDWINDOW,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            GetModuleHandleW(std::ptr::null()),
            Box::into_raw(Box::new(state.clone())) as *const _,
        );

        // Register hotkeys
        let hotkey_map: Vec<(u32, &str)> = vec![
            (ID_LEFT, &config.hotkeys.left),
            (ID_RIGHT, &config.hotkeys.right),
            (ID_TOP, &config.hotkeys.top),
            (ID_BOTTOM, &config.hotkeys.bottom),
            (ID_CENTER, &config.hotkeys.center),
            (ID_FULL, &config.hotkeys.full),
            (ID_RESTORE, &config.hotkeys.restore),
        ];

        for (id, combo) in &hotkey_map {
            if let Some((modifiers, vk)) = parse_hotkey(combo) {
                if RegisterHotKey(hwnd, *id as i32, modifiers, vk) == 0 {
                    warn!("Failed to register hotkey: {} -> {}", combo, id);
                } else {
                    info!("Hotkey registered: {} -> {}", combo, id);
                }
            } else {
                warn!("Invalid hotkey format: {}", combo);
            }
        }

        // Create tray icon
        let hicon = load_embedded_icon();
        if hicon.is_null() {
            warn!("Failed to load embedded icon, using fallback");
        }

        let mut nid: NOTIFYICONDATAW = std::mem::zeroed();
        nid.cbSize = std::mem::size_of::<NOTIFYICONDATAW>() as u32;
        nid.hWnd = hwnd;
        nid.uID = 1;
        nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
        nid.uCallbackMessage = WM_TRAYICON;
        if !hicon.is_null() {
            nid.hIcon = hicon;
        } else {
            // Fallback: draw a simple orange square
            let hdc = GetDC(std::ptr::null_mut());
            let mem_dc = CreateCompatibleDC(hdc);
            let bmp = CreateCompatibleBitmap(hdc, 16, 16);
            let old = SelectObject(mem_dc, bmp);
            let brush = CreateSolidBrush(0x00DD8833);
            let rect = RECT {
                left: 0,
                top: 0,
                right: 16,
                bottom: 16,
            };
            let _ = FillRect(mem_dc, &rect, brush);
            let _ = DeleteObject(brush as _);
            let _ = SelectObject(mem_dc, old);
            nid.hIcon = CreateIconIndirect(&ICONINFO {
                fIcon: 1,
                xHotspot: 0,
                yHotspot: 0,
                hbmMask: bmp,
                hbmColor: bmp,
            });
            let _ = DeleteDC(mem_dc);
            let _ = DeleteObject(bmp as _);
            let _ = ReleaseDC(std::ptr::null_mut(), hdc);
        }

        let tip = to_wide("WinSnap v1.1.0");
        let tip_len = tip.len().min(127);
        nid.szTip[..tip_len].copy_from_slice(&tip[..tip_len]);
        Shell_NotifyIconW(NIM_ADD, &nid);

        // Message loop
        let mut msg: MSG = std::mem::zeroed();
        while GetMessageW(&mut msg, std::ptr::null_mut(), 0, 0) != 0 {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }

        // Cleanup
        info!("Shutting down, cleaning up");
        Shell_NotifyIconW(NIM_DELETE, &nid);
        if !hicon.is_null() {
            DestroyIcon(hicon);
        }
        let _ = UnregisterHotKey(hwnd, ID_LEFT as i32);
        let _ = UnregisterHotKey(hwnd, ID_RIGHT as i32);
        let _ = UnregisterHotKey(hwnd, ID_TOP as i32);
        let _ = UnregisterHotKey(hwnd, ID_BOTTOM as i32);
        let _ = UnregisterHotKey(hwnd, ID_CENTER as i32);
        let _ = UnregisterHotKey(hwnd, ID_FULL as i32);
        let _ = UnregisterHotKey(hwnd, ID_RESTORE as i32);
    }
}
