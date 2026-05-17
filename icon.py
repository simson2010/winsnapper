"""
SnapEdge App Icon Generator
============================
Windows 系统托盘应用图标生成器
应用功能：注册快捷键，按下后将当前窗口吸附到对应屏幕边缘

生成产物（默认输出到脚本同级的 icon/ 目录）：
  - icon.ico (Blue 默认)
  - icon_dark.ico (深色托盘适配)
  - icon_green.ico (绿色备选)
  - snapedge_{variant}_{size}x{size}.png
  - snapedge.svg

用法：
  python icon.py [--output DIR] [--variant blue|green|dark|all] [--format ico|png|svg|all]
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw


# ── 配色方案 ──────────────────────────────────────────────

COLOR_SCHEMES = {
    "blue": {
        "primary": (55, 138, 221),      # #378ADD - Windows 蓝
        "light": (181, 212, 244),        # #B5D4F4 - 浅蓝填充
        "dark": (24, 95, 165),           # #185FA5 - 边缘吸附指示条
        "accent": (92, 163, 232),        # #5CA3E8 - 中蓝箭头
        "bg": (230, 241, 251),           # #E6F1FB - 标题栏按钮底色
    },
    "green": {
        "primary": (29, 158, 117),       # #1D9E75
        "light": (159, 225, 203),        # #9FE1CB
        "dark": (15, 110, 86),           # #0F6E56
        "accent": (64, 191, 149),        # #40BF95
        "bg": (225, 245, 238),           # #E1F5EE
    },
    "dark": {
        "primary": (133, 194, 240),      # #85C2F0 - 浅蓝（深色托盘用）
        "light": (181, 212, 244),        # #B5D4F4
        "dark": (200, 220, 245),         # #C8DCF5
        "accent": (160, 208, 248),       # #A0D0F8
        "bg": (40, 50, 70),             # #283246
    },
}

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
PNG_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]

SVG_TEMPLATE = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
  <rect x="14" y="14" width="228" height="228" rx="24" fill="none" stroke="{primary}" stroke-width="8"/>
  <line x1="128" y1="22" x2="128" y2="234" stroke="{primary}" stroke-width="3" stroke-dasharray="12 8"/>
  <rect x="22" y="22" width="100" height="212" rx="12" fill="{light}" stroke="{primary}" stroke-width="5"/>
  <rect x="28" y="28" width="88" height="24" rx="6" fill="{primary}"/>
  <circle cx="38" cy="40" r="3" fill="{bg}"/>
  <circle cx="48" cy="40" r="3" fill="{bg}"/>
  <circle cx="58" cy="40" r="3" fill="{bg}"/>
  <rect x="22" y="34" width="12" height="200" fill="{dark}"/>
  <polyline points="152,108 140,128 152,148" fill="none" stroke="{accent}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
  <polyline points="172,108 184,128 172,148" fill="none" stroke="{accent}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
</svg>'''


# ── 图标绘制核心 ──────────────────────────────────────────

def draw_icon(size, variant="blue"):
    """
    绘制 SnapEdge 图标。

    图形结构：
      ┌─────────────────────┐
      │ ┌─────────┐  ·  ·  │  圆角屏幕框
      │ │ ■ ■ ■  │   < >   │  左半窗口（已吸附）+ 标题栏三按钮
      │ │         │         │  中央虚线分隔
      │ │ █       │  ·  ·  │  左侧深色吸附指示条
      │ └─────────┘         │  右侧方向箭头（< >）
      └─────────────────────┘

    参数:
        size: 图标尺寸（像素）
        variant: 配色方案名 (blue/green/dark)

    返回:
        PIL.Image (RGBA)
    """
    c = COLOR_SCHEMES[variant]
    s = size

    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # ── 布局参数（按比例缩放）──
    pad = max(1, round(s * 0.06))        # 外边距
    corner_r = max(1, round(s * 0.1))    # 圆角半径
    line_w = max(1, round(s * 0.04))     # 边框线宽
    inset = max(1, round(s * 0.03))      # 窗口内缩

    # ── 屏幕框 ──
    sl, st = pad, pad
    sr, sb = s - 1 - pad, s - 1 - pad
    d.rounded_rectangle([sl, st, sr, sb], radius=corner_r,
                        outline=c["primary"], width=line_w)

    # ── 中央虚线分隔 ──
    cx = (sl + sr) // 2
    dash = max(2, round(s * 0.06))
    gap = max(1, round(s * 0.04))
    y = st + line_w
    while y < sb - line_w:
        y2 = min(y + dash, sb - line_w)
        d.line([(cx, y), (cx, y2)], fill=c["primary"],
               width=max(1, line_w // 2))
        y = y2 + gap

    # ── 吸附窗口（左半） ──
    wl = sl + inset
    wt = st + inset
    wr = cx - max(1, round(s * 0.02))
    wb = sb - inset
    wr = max(wl + 2, wr)
    win_r = max(1, round(s * 0.06))

    d.rounded_rectangle([wl, wt, wr, wb], radius=win_r,
                        fill=c["light"], outline=c["primary"],
                        width=max(1, round(s * 0.03)))

    # ── 标题栏 ──
    bar_h = max(2, round(s * 0.1))
    bi = max(1, round(s * 0.02))
    d.rounded_rectangle([wl + bi, wt + bi, wr - bi, wt + bi + bar_h],
                        radius=max(1, round(s * 0.03)),
                        fill=c["primary"])

    # ── 标题栏窗口控制按钮（三圆点） ──
    if size >= 24:
        dot_r = max(1, round(s * 0.015))
        dot_y = wt + bi + bar_h // 2
        dot_x0 = wl + bi + max(2, round(s * 0.04))
        dot_gap = max(3, round(s * 0.05))
        for i in range(3):
            dx = dot_x0 + i * dot_gap
            if dx < wr - bi:
                d.ellipse([dx - dot_r, dot_y - dot_r,
                           dx + dot_r, dot_y + dot_r],
                          fill=c["bg"])

    # ── 左侧吸附指示条（深色强调） ──
    accent_w = max(1, round(s * 0.05))
    d.rectangle([wl, wt + win_r, wl + accent_w, wb - win_r],
                fill=c["dark"])

    # ── 方向箭头（右侧空间） ──
    if size >= 24:
        ay = (st + sb) // 2
        ch = max(2, round(s * 0.05))
        clw = max(1, round(s * 0.03))

        # 左箭头 <
        ax1 = cx + max(2, round(s * 0.08))
        d.line([(ax1 + ch, ay - ch), (ax1, ay)], fill=c["accent"], width=clw)
        d.line([(ax1, ay), (ax1 + ch, ay + ch)], fill=c["accent"], width=clw)

        # 右箭头 >
        ax2 = cx + max(2, round(s * 0.18))
        d.line([(ax2 - ch, ay - ch), (ax2, ay)], fill=c["accent"], width=clw)
        d.line([(ax2, ay), (ax2 - ch, ay + ch)], fill=c["accent"], width=clw)

    return img


def generate_svg(variant="blue"):
    """生成 SVG 矢量源文件。"""
    c = COLOR_SCHEMES[variant]
    return SVG_TEMPLATE.format(
        primary="#%02X%02X%02X" % c["primary"],
        light="#%02X%02X%02X" % c["light"],
        dark="#%02X%02X%02X" % c["dark"],
        accent="#%02X%02X%02X" % c["accent"],
        bg="#%02X%02X%02X" % c["bg"],
    )


# ── 批量生成 ──────────────────────────────────────────────

def generate_all(output_dir, variants=None, formats=None):
    """
    批量生成图标文件。

    参数:
        output_dir: 输出目录
        variants: 配色方案列表，默认 ["blue", "green", "dark"]
        formats: 格式列表，默认 ["ico", "png", "svg"]
    """
    if variants is None:
        variants = ["blue", "green", "dark"]
    if formats is None:
        formats = ["ico", "png", "svg"]

    os.makedirs(output_dir, exist_ok=True)

    for variant in variants:
        tag = variant

        # ── PNG ──
        if "png" in formats:
            for sz in PNG_SIZES:
                img = draw_icon(sz, variant)
                path = os.path.join(output_dir,
                                    f"snapedge_{tag}_{sz}x{sz}.png")
                img.save(path)
                print(f"  [PNG] {os.path.basename(path)}")

        # ── ICO ──
        if "ico" in formats:
            images = [draw_icon(sz, variant) for sz in ICO_SIZES]
            suffix = "" if variant == "blue" else f"_{variant}"
            path = os.path.join(output_dir, f"icon{suffix}.ico")
            images[-1].save(
                path,
                format="ICO",
                sizes=[(sz, sz) for sz in ICO_SIZES],
                append_images=images[:-1],
            )
            print(f"  [ICO] {os.path.basename(path)}  "
                  f"({os.path.getsize(path):,} bytes)")

        # ── SVG ──
        if "svg" in formats:
            svg = generate_svg(variant)
            suffix = "" if variant == "blue" else f"_{variant}"
            path = os.path.join(output_dir, f"snapedge{suffix}.svg")
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg)
            print(f"  [SVG] {os.path.basename(path)}")


# ── CLI ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="WinSnap App Icon Generator"
    )
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    parser.add_argument(
        "--output", "-o",
        default=os.path.join(_script_dir, "icon"),
        help="输出目录 (默认: 脚本所在目录下的 icon/)",
    )
    parser.add_argument(
        "--variant", "-v",
        choices=["blue", "green", "dark", "all"],
        default="all",
        help="配色方案 (默认: all)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["ico", "png", "svg", "all"],
        default="all",
        help="输出格式 (默认: all)",
    )

    args = parser.parse_args()

    variants = ["blue", "green", "dark"] if args.variant == "all" else [args.variant]
    formats = ["ico", "png", "svg"] if args.format == "all" else [args.format]

    print(f"SnapEdge Icon Generator")
    print(f"  Output: {args.output}")
    print(f"  Variants: {', '.join(variants)}")
    print(f"  Formats: {', '.join(formats)}")
    print()

    generate_all(args.output, variants, formats)

    print()
    print("Done.")


if __name__ == "__main__":
    main()
