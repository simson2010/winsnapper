# WinSnap

> 一款轻量级 Windows 10/11 窗口贴靠工具，完全通过全局热键驱动——支持可配置快捷键、递增尺寸调节和设置窗口。

WinSnap 通过全局热键将活动窗口贴靠到屏幕边缘（左/右/上/下）、居中或全工作区。重复按同一热键可递增调节尺寸（50%→75%→100%），并支持一键还原。完整的多显示器支持，以及通过设置窗口实时重新配置热键。无冗余功能、无遥测、无需联网——只有一个托盘图标和即时键盘驱动的窗口管理。

---

## 功能对比

| 功能 | Python | Rust |
|------|--------|------|
| **贴靠** 左/右/上/下 | ✅ | ✅ |
| **居中**（60% 宽度） | ✅ | ✅ |
| **全屏**工作区 | ✅ | ✅ |
| **还原**到贴靠前位置 | ✅ | ✅ |
| **递增尺寸** 50%→75%→100%→50% | ✅ | ✅ |
| **DWM 不可见边框**补偿 | ✅ | ✅ |
| **DPI 感知** | 每显示器 (`SetProcessDpiAwareness(2)`) | 系统级 (`SetProcessDPIAware`) |
| **全局热键** | `keyboard` 库（第三方） | Win32 `RegisterHotKey`（原生） |
| **系统托盘** | `pystray` | Win32 `Shell_NotifyIconW` |
| **设置窗口** | tkinter | Win32 原生控件 |
| **配置持久化** | `winsnap_config.json` | `winsnap_config.json` |
| **热键捕获** | tkinter `<Key>` 绑定 | `WM_KEYDOWN` + `GetKeyState` |
| **窗口身份追踪** `(pid, class, title)` | ✅ | ❌ |
| **Shell 窗口过滤** | 6 个窗口类 | 4 个窗口类 |
| **过期 HWND 清理** | ✅ | ❌ |
| **日志** | `winsnap.log` | ❌ |

### 贴靠热键

| 热键 | 操作 | 递增尺寸 |
|------|------|---------|
| `Ctrl+Alt+Left` | 贴靠到**左半屏** | ✅ 50% → 75% → 100% → 50% |
| `Ctrl+Alt+Right` | 贴靠到**右半屏** | ✅ 50% → 75% → 100% → 50% |
| `Ctrl+Alt+Up` | 贴靠到**上半屏** | ✅ 50% → 75% → 100% → 50% |
| `Ctrl+Alt+Down` | 贴靠到**下半屏** | ✅ 50% → 75% → 100% → 50% |
| `Ctrl+Alt+C` | **居中**窗口（60% 宽度） | ❌ |
| `Ctrl+Alt+F` | **全屏**工作区 | ❌ |
| `Ctrl+Alt+R` | **还原**到贴靠前位置 | — |

> 以上为默认热键。所有热键均可通过设置窗口完全自定义。

所有操作针对**活动前台窗口**。所有尺寸均相对于**显示器的工作区**（支持多显示器）。

### 递增尺寸

当连续按同一贴靠热键时，窗口会循环切换尺寸：

- **左 / 右**：50% → 75% → 100%（宽度）→ 回到 50%
- **上 / 下**：50% → 75% → 100%（高度）→ 回到 50%
- **居中 / 全屏**：无递增尺寸

---

## 快速对比

| 指标 | Python | Rust |
|------|--------|------|
| 二进制体积 | ~15 MB（PyInstaller） | ~226 KB（release, LTO+strip） |
| 启动时间 | ~2 秒 | <100 毫秒 |
| 内存占用 | ~30 MB | ~1 MB |
| 依赖项 | pywin32, keyboard, pystray, Pillow | 无（Win32 FFI 通过 windows-sys） |
| 环境 | Python 3.11+ | Rust 2021 工具链 |
| 窗口隐藏 | 无（默认控制台） | `#![windows_subsystem = "windows"]` |

---

## 设置

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

## 构建独立 .exe

### Python

```powershell
build_exe.bat
# 输出：dist/WinSnap.exe
```

### Rust

```powershell
cd rust_version/winsnap_rust
cargo build --release
# 输出：target/release/winsnapper.exe
```

---

## 项目结构

```
winsnap/
├── winsnap.py                  # Python 主程序
├── icon.py                     # Python 图标生成器
├── winsnap_config.json         # 配置文件（自动创建）
├── requirements.txt            # Python 依赖
├── build_exe.bat               # PyInstaller 构建脚本
├── unittests/                  # Python 单元测试
├── docs/                       # 文档
│   ├── bugfix-report-v1.1.0.md
│   └── rust-subsystem-guide.md
├── rust_version/
│   └── winsnap_rust/
│       ├── Cargo.toml
│       ├── src/main.rs         # Rust 实现（约 1056 行）
│       └── spec/
│           └── migration-status.md
└── README.md
```

---

## 工作原理

1. 启动时启用 **DPI 感知**，确保物理像素坐标正确。
2. 从 `winsnap_config.json` 加载**配置**（首次自动创建默认配置）。
3. **全局注册热键**——Python 通过 `keyboard` 守护线程，Rust 通过 Win32 `RegisterHotKey` 系统消息循环。
4. 触发贴靠时：记录原始窗口位置，若已最大化则恢复，检查递增尺寸级别，查询 `GetMonitorInfo` 获取工作区，用计算好的几何参数调用 `MoveWindow`。Windows 10/11 通过 DWM 添加了不可见的透明边框（约 7-8 像素）——使用 `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)` 进行补偿，确保窗口精确对齐到工作区边缘。
5. **还原**热键恢复到保存的贴靠前位置。
6. **设置窗口**支持实时热键重配置——保存后持久化到 JSON 并立即重新注册热键。
7. **系统托盘**——Python 通过 `pystray`，Rust 通过 `Shell_NotifyIconW`；不显示主窗口。

---

## 系统要求

- Windows 10 或 11
- **Python 版本**：Python 3.11+
- **Rust 版本**：Rust 2021 版工具链（用于构建）

---

## 许可证

MIT