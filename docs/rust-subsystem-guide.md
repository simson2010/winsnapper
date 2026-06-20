# Rust: 控制台应用 vs 纯视窗应用

## 控制台应用（CMD / PowerShell）

**默认行为**：Rust 程序默认编译为控制台子系统（`console`），运行时会自动分配一个终端窗口。

```rust
// 无需任何特殊属性 — 默认就是控制台应用
fn main() {
    println!("Hello from console");
}
```

- `println!`、`eprintln!` 直接输出到终端。
- 可通过 stdin/stdout 与用户交互。
- 从 CMD/PowerShell 启动时，输出会显示在调用者的窗口中。
- 双击 exe 时会弹出一个新的终端窗口。

## 纯视窗应用（无控制台窗口）

在 `main.rs` 文件头部添加属性：

```rust
#![windows_subsystem = "windows"]

fn main() {
    // Win32 消息循环，无控制台窗口
}
```

- **不会**创建控制台窗口，启动后完全不可见（除非创建窗口）。
- `println!` / `eprintln!` 输出会丢失（没有终端可接收）。
- 适合系统托盘工具、后台服务、纯 Win32 GUI 程序。
- Cargo.toml 不需要额外配置 — 属性宏在编译时告诉链接器使用 `WINDOWS` 子系统而非 `CONSOLE`。

## 常见事项

| 场景 | 做法 |
|------|------|
| 单纯要隐藏黑窗口 | 加 `#![windows_subsystem = "windows"]` |
| 既想无窗口又需控制台输出（调试用） | 条件编译：`#[cfg(debug_assertions)]` 时保留 `console`，release 切换 `windows` |
| 仍需要用 `println!` 调试 | 手工 `AttachConsole` / `AllocConsole` 附加到父控制台 |

## 条件编译示例（调试时有控制台，发布时无）

```rust
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // debug 模式下有控制台窗口，release 模式下无
    println!("Debug output only visible in debug builds");
}
```