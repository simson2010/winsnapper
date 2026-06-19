# WinSnap v1.1.0 — 问题修复文档

> 日期：2026-06-19  
> 版本：v1.1.0  
> 仓库：https://github.com/simson2010/winsnapper

---

## 一、修复的问题总览

| # | 问题 | 严重度 | 根因 | 修复文件 |
|---|------|--------|------|----------|
| 1 | Save Settings 后崩溃 | Critical | `root.quit()` 在 `root.destroy()` 之前调用，tkinter 状态不一致 | `winsnap.py` |
| 2 | 冻结 .exe 保存配置失败 | Critical | `CONFIG_PATH` 用 `__file__` 定位，冻结后指向临时目录 | `winsnap.py` |
| 3 | 快捷键监听线程静默死亡 | High | keyboard 库 `process()` 无异常处理，一个异常杀死线程 | `winsnap.py` |
| 4 | tray 图标无故退出 | High | pystray `GetMessage` 返回 -1 时静默退出循环 | `winsnap.py` |
| 5 | Monkey-patch 导致快捷键完全失效 | Critical | patch 设在实例上，`Thread()` 捕获的函数缺少 `self` 参数 | `winsnap.py` |

---

## 二、详细分析与修复

### 问题 1：Save Settings 后崩溃

**现象**：点击 Save 按钮后应用崩溃。

**根因**：`_on_settings_close()` 中调用了 `root.quit()` 再调用 `root.destroy()`。

- `root.quit()` 退出 tkinter 主循环但不销毁窗口
- `root.destroy()` 在 tkinter 已退出主循环的状态下尝试清理 → 状态不一致 → 崩溃
- 手动销毁子组件的循环也会触发 StringVar GC，在迭代中途出错

**修复**：

```python
# 修复前
def _on_settings_close(root):
    root.unbind("<Key>")
    for child in root.winfo_children():
        child.destroy()      # ← 触发 StringVar GC
    root.quit()              # ← 退出主循环但不销毁窗口
    root.destroy()           # ← tkinter 状态不一致

# 修复后
def _on_settings_close(root):
    try:
        root.unbind("<Key>")
    except Exception:
        pass
    try:
        root.destroy()       # ← 一个调用完成所有清理
    except Exception:
        pass
```

**教训**：`root.destroy()` 本身就退出主循环并销毁窗口，不需要 `root.quit()`。手动销毁子组件是多余且危险的。

---

### 问题 2：冻结 .exe 配置保存失败

**现象**：将 EXE 复制到其它机器运行，Save Settings 后找不到配置文件。

**根因**：

```python
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "winsnap_config.json")
```

PyInstaller 冻结后 `__file__` 指向 `sys._MEIPASS`（临时解压目录），配置文件保存到该目录，程序退出后被清理。

**修复**：

```python
def _resolve_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)  # .exe 所在目录
    return os.path.dirname(os.path.abspath(__file__))

APP_DIR = _resolve_app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "winsnap_config.json")
```

**教训**：PyInstaller 冻结应用中 `__file__` 不可靠，需要区分 dev 和 frozen 环境。`sys.executable` 才是 .exe 的真实路径。

---

### 问题 3：keyboard 库监听线程静默死亡

**现象**：运行一段时间后快捷键不再响应，但 tray 图标仍在。

**根因**：keyboard 库的 `GenericListener.process()` 方法没有顶层异常处理：

```python
def process(self):
    while True:
        event = self.queue.get()
        if self.pre_process_event(event):
            self.invoke_handlers(event)
        self.queue.task_done()
```

如果 `pre_process_event()` 或 `invoke_handlers()` 中的回调抛出未捕获异常，线程直接死亡。而 `self.listening` 仍为 `True`，`start_if_necessary()` 不会重启线程。快捷键永久失效。

**修复**：

1. **Monkey-patch `GenericListener.process()`**（patch 类，不是实例）：

```python
import keyboard._generic as _keyboard_generic

def _patched_keyboard_process(self):
    while True:
        try:
            event = self.queue.get()
            if self.pre_process_event(event):
                self.invoke_handlers(event)
            self.queue.task_done()
        except Exception:
            traceback.print_exc()

_keyboard_generic.GenericListener.process = _patched_keyboard_process
```

2. **Watchdog 线程**每 3 秒检查 `listening_thread.is_alive()` 和 `processing_thread.is_alive()`，线程死亡时重置 `listening=False` 并重新注册。

**教训**：第三方库的线程安全性不能假设。daemon 线程死亡不会传播到主线程，必须主动监控。

---

### 问题 4：pystray GetMessage 返回 -1 导致退出

**现象**：应用在 tray 中随机退出，日志无异常。

**根因**：pystray 的 `_mainloop` 中：

```python
while True:
    r = win32.GetMessage(lpmsg, None, 0, 0)
    if not r:
        break           # WM_QUIT → 正常退出
    elif r == -1:
        break           # ← 错误时静默退出，无日志！
    else:
        win32.TranslateMessage(lpmsg)
        win32.DispatchMessage(lpmsg)
```

`GetMessage` 返回 -1 时直接 break，`icon.run()` 返回，app 退出。没有任何异常或日志。

**修复**：Monkey-patch `_PystrayIcon._mainloop`，`-1` 时 `continue` 而非 `break`：

```python
elif r == -1:
    logger.warning("GetMessage returned -1, continuing")
    continue
```

同时保留 `_tray_mainloop_with_restart` 作为第二层安全网。

**教训**：Win32 API 错误处理必须显式，不能假设"不会发生"。

---

### 问题 5：Monkey-patch 实例 vs 类导致快捷键完全失效

**现象**：修复问题 3 后，快捷键监听线程存活但回调不触发。

**根因**：

```python
# 错误：patch 实例
keyboard._listener.process = _patched_keyboard_process
```

这把实例上的绑定方法替换为普通函数。`Thread(target=self.process)` 捕获的是无参函数，调用时缺少 `self` → `TypeError` → processing thread 静默死亡。

**修复**：Patch 类而不是实例：

```python
# 正确：patch 类
import keyboard._generic as _keyboard_generic
_keyboard_generic.GenericListener.process = _patched_keyboard_process
```

**教训**：Monkey-patch 方法时必须考虑 `self` 绑定。替换实例属性会破坏方法绑定，应该替换类属性。

---

## 三、注意事项

### 开发环境

1. **Python 3.11+**，Windows 10/11
2. 虚拟环境：`winsnap-venv/`（不要用系统 Python）
3. 依赖安装：`pip install -r requirements.txt`

### 构建流程

每次修改代码后，按顺序执行：

```powershell
# 1. 运行单元测试
winsnap-venv\Scripts\python.exe -m unittest discover -s unittests -v

# 2. 编译 EXE
cmd /c build_exe.bat

# 3. Git commit（本地）
git add <files>
git commit -m "message"
```

### PyInstaller 相关

- `--hidden-import=tkinter` 必须保留
- `--add-data "icon\icon.ico;."` 打包图标
- 冻结后 `__file__` 指向 `_MEIPASS`（临时目录），不要用它定位持久化文件
- 用 `sys.executable` 定位 .exe 同级目录

### 第三方库安全

- **keyboard 库**：监听线程无异常处理，必须 monkey-patch 或外部监控
- **pystray**：`GetMessage` 错误时静默退出，需要 patch 或 restart 机制
- **tkinter**：daemon 线程中的 tkinter 对象 GC 会引发 `RuntimeError`，不要在非主线程创建 tkinter 对象

### 日志

- 日志文件：`winsnap.log`（与 .exe 同级）
- 级别：DEBUG/INFO/WARNING/ERROR
- 关键操作均有日志：启动、配置加载/保存、快捷键注册/失败/重启、snap 操作、设置窗口、退出

---

## 四、测试覆盖

43 个单元测试，5 个测试文件：

| 文件 | 覆盖范围 | 用例数 |
|------|----------|--------|
| `test_config.py` | 配置加载/保存/合并/异常 | 8 |
| `test_hotkeys.py` | 快捷键标准化/去重/常量 | 13 |
| `test_settings_close.py` | 设置窗口关闭生命周期 | 4 |
| `test_snap_logic.py` | 窗口身份/吸附判断/图标路径 | 8 |
| `test_icon.py` | 图标生成 ICO/PNG/SVG | 10 |

---

## 五、v1.1.0 Release Notes

**Release**: https://github.com/simson2010/winsnapper/releases/tag/v1.1.0

### Bug Fixes
- Save Settings 崩溃（tkinter 状态不一致）
- 冻结 .exe 配置文件保存到临时目录
- 快捷键监听线程静默死亡
- tray 图标 GetMessage 错误时静默退出

### Improvements
- 全面的日志记录（winsnap.log）
- 43 个单元测试
- AGENTS.md 开发规范
