"""
icon.py — Generate WinSnap tray icon and save as icon.ico.

The icon is a classic Windows window shape:
  - Dark blue rounded-rectangle border (window frame)
  - Light blue title bar with red/yellow/green buttons
  - White/light-gray content area

Run this script once to produce icon.ico in the same directory.
The icon is drawn entirely with Pillow (no external image files needed).
"""

import os
from PIL import Image, ImageDraw


def create_icon(size: int = 64) -> Image.Image:
    """Draw a window-shaped icon at the given pixel size.

    The icon depicts a classic Windows application window:
    - Dark blue rounded-rectangle border (window frame)
    - Light blue title bar area with three small coloured squares
      (red, yellow, green) representing close / minimise / maximise buttons
    - White / light-gray content area representing the window body

    Args:
        size: Pixel dimensions of the square canvas (default 64).

    Returns:
        A Pillow RGBA Image ready to be saved.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # --- Colour palette ---
    frame_border_color = (20, 50, 120, 255)       # Dark blue border
    frame_fill_color = (30, 80, 180, 255)          # Medium blue fill (frame)
    title_bar_color = (100, 160, 230, 255)         # Light blue title bar
    content_color = (240, 243, 248, 255)            # Light gray-white content
    btn_red = (220, 60, 50, 255)                   # Close button
    btn_yellow = (230, 190, 40, 255)                # Minimise button
    btn_green = (50, 180, 80, 255)                  # Maximise button

    # --- Outer frame (rounded rectangle) ---
    margin = 2
    draw.rounded_rectangle(
        [margin, margin, size - margin - 1, size - margin - 1],
        radius=max(4, size // 10),
        fill=frame_fill_color,
        outline=frame_border_color,
        width=max(1, size // 32),
    )

    # --- Title bar (light blue rectangle at the top) ---
    title_bar_top = margin + max(2, size // 20)
    title_bar_bottom = margin + size // 4 + size // 16
    draw.rounded_rectangle(
        [margin + max(1, size // 32), title_bar_top,
         size - margin - max(1, size // 32) - 1, title_bar_bottom],
        radius=max(2, size // 24),
        fill=title_bar_color,
    )

    # --- Three buttons on the title bar ---
    btn_size = max(3, size // 12)
    btn_gap = max(2, size // 16)
    btn_y = (title_bar_top + title_bar_bottom) // 2 - btn_size // 2
    btn_x_start = margin + max(3, size // 10)

    draw.rectangle(
        [btn_x_start, btn_y, btn_x_start + btn_size, btn_y + btn_size],
        fill=btn_red,
    )
    draw.rectangle(
        [btn_x_start + btn_size + btn_gap, btn_y,
         btn_x_start + 2 * btn_size + btn_gap, btn_y + btn_size],
        fill=btn_yellow,
    )
    draw.rectangle(
        [btn_x_start + 2 * (btn_size + btn_gap), btn_y,
         btn_x_start + 3 * btn_size + 2 * btn_gap, btn_y + btn_size],
        fill=btn_green,
    )

    # --- Content area (white / light gray rectangle) ---
    content_top = title_bar_bottom + max(2, size // 20)
    content_left = margin + max(2, size // 24)
    content_right = size - margin - max(2, size // 24) - 1
    content_bottom = size - margin - max(3, size // 16) - 1
    draw.rectangle(
        [content_left, content_top, content_right, content_bottom],
        fill=content_color,
    )

    # --- Subtle horizontal lines inside content area (decorative) ---
    line_color = (200, 210, 225, 120)
    line_y_start = content_top + (content_bottom - content_top) // 4
    for i in range(3):
        ly = line_y_start + i * (content_bottom - content_top) // 4
        if ly < content_bottom - 2:
            draw.line(
                [(content_left + size // 16, ly), (content_right - size // 16, ly)],
                fill=line_color,
                width=max(1, size // 64),
            )

    return img


def save_icon(dest_path: str = "") -> str:
    """Create the icon and save it as a multi-resolution .ico file.

    Args:
        dest_path: Full path including filename.  If empty, saves
                   icon.ico next to this script.

    Returns:
        The absolute path where the icon was saved.
    """
    if not dest_path:
        dest_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")

    # Build multiple sizes for a proper .ico file
    sizes = [16, 24, 32, 48, 64]
    images = [create_icon(s) for s in sizes]

    # Save as ICO; the first image is the primary size
    images[0].save(
        dest_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    return dest_path


if __name__ == "__main__":
    path = save_icon()
    print(f"Icon saved to: {path}")
