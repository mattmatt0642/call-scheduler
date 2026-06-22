#!/usr/bin/env python3
"""Generate PWA icons for Call Scheduler."""
import os
from PIL import Image, ImageDraw, ImageFont

FRONTEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONS_DIR = os.path.join(FRONTEND, 'icons')

BG_COLOR = (15, 15, 21)
ACCENT_BLUE = (79, 143, 247)
ACCENT_GREEN = (52, 211, 153)
WHITE = (228, 228, 235)
LIGHT_GRAY = (160, 160, 180)

def draw_calendar_icon(size, output_path):
    """Draw a calendar/schedule icon matching the app aesthetic."""
    img = Image.new('RGBA', (size, size), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Icon design: a clipboard with calendar grid and checkmarks
    margin = int(size * 0.15)
    header_h = int(size * 0.22)
    body_top = margin + header_h

    # Clipboard body
    clipboard_body = [margin, margin + header_h, size - margin, size - margin]
    draw.rounded_rectangle(clipboard_body, radius=int(size * 0.06), fill=(28, 28, 40))

    # Clipboard header bar
    header_rect = [margin, margin, size - margin, margin + header_h]
    draw.rounded_rectangle(header_rect, radius=int(size * 0.06), fill=ACCENT_BLUE)
    # Cover bottom corners of header
    draw.rectangle([margin, margin + header_h - int(size * 0.08), size - margin, margin + header_h], fill=ACCENT_BLUE)

    # Header text lines (simulated)
    line_w = int(size * 0.25)
    line_h = int(size * 0.04)
    header_text_x = int(size * 0.22)
    header_text_y = margin + int(header_h * 0.35)
    draw.rounded_rectangle([header_text_x, header_text_y, header_text_x + line_w, header_text_y + line_h], radius=int(size * 0.02), fill=WHITE)

    # Clipboard clip at top
    clip_w = int(size * 0.28)
    clip_h = int(size * 0.08)
    clip_x = int((size - clip_w) / 2)
    clip_y = margin - int(size * 0.02)
    draw.rounded_rectangle([clip_x, clip_y, clip_x + clip_w, clip_y + clip_h], radius=int(size * 0.03), fill=LIGHT_GRAY)

    # Calendar grid inside body
    grid_left = int(size * 0.20)
    grid_right = size - int(size * 0.20)
    grid_top = body_top + int(size * 0.06)
    grid_bottom = size - int(size * 0.12)
    rows = 4
    cols = 3
    cell_w = (grid_right - grid_left) // cols
    cell_h = (grid_bottom - grid_top) // rows

    for r in range(rows):
        for c in range(cols):
            x = grid_left + c * cell_w
            y = grid_top + r * cell_h
            cell_rect = [x + int(cell_w * 0.1), y + int(cell_h * 0.1),
                         x + int(cell_w * 0.7), y + int(cell_h * 0.65)]
            draw.rounded_rectangle(cell_rect, radius=int(size * 0.02), fill=(39, 39, 53))

            # Add a colored dot or checkmark to some cells
            if (r + c) % 3 != 0:
                dot_x = (cell_rect[0] + cell_rect[2]) // 2
                dot_y = (cell_rect[1] + cell_rect[3]) // 2
                dot_r = max(2, int(size * 0.03))
                color = ACCENT_BLUE if (r + c) % 2 == 0 else ACCENT_GREEN
                draw.ellipse([dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r], fill=color)

    img.save(output_path, 'PNG')
    print(f"Created: {output_path}")

for size, name in [(72, 'icon-72'), (96, 'icon-96'), (128, 'icon-128'), (144, 'icon-144'), (152, 'icon-152'), (192, 'icon-192'), (384, 'icon-384'), (512, 'icon-512')]:
    draw_calendar_icon(size, os.path.join(ICONS_DIR, f'{name}.png'))

# Also create apple-touch-icon (180x180)
draw_calendar_icon(180, os.path.join(ICONS_DIR, 'apple-touch-icon.png'))

# Create a simple maskable icon version (pad with transparent so safe zone is clear)
for size, name in [(192, 'icon-maskable-192'), (512, 'icon-maskable-512')]:
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    inner_size = int(size * 0.8)
    offset = (size - inner_size) // 2
    inner_img = Image.new('RGBA', (inner_size, inner_size), BG_COLOR)
    i_draw = ImageDraw.Draw(inner_img)

    # Mini version of the icon
    m = int(inner_size * 0.15)
    h_h = int(inner_size * 0.22)
    header_rect = [m, m, inner_size - m, m + h_h]
    i_draw.rounded_rectangle(header_rect, radius=int(inner_size * 0.06), fill=ACCENT_BLUE)
    i_draw.rectangle([m, m + h_h - int(inner_size * 0.08), inner_size - m, m + h_h], fill=ACCENT_BLUE)

    body_top = m + h_h
    grid_left = int(inner_size * 0.20)
    grid_right = inner_size - int(inner_size * 0.20)
    grid_top = body_top + int(inner_size * 0.06)
    grid_bottom = inner_size - int(inner_size * 0.12)
    rows, cols = 4, 3
    cell_w = (grid_right - grid_left) // cols
    cell_h = (grid_bottom - grid_top) // rows
    for r in range(rows):
        for c in range(cols):
            x = grid_left + c * cell_w
            y = grid_top + r * cell_h
            cell_rect = [x + int(cell_w * 0.1), y + int(cell_h * 0.1),
                         x + int(cell_w * 0.7), y + int(cell_h * 0.65)]
            i_draw.rounded_rectangle(cell_rect, radius=int(inner_size * 0.02), fill=(39, 39, 53))
            if (r + c) % 3 != 0:
                dot_x = (cell_rect[0] + cell_rect[2]) // 2
                dot_y = (cell_rect[1] + cell_rect[3]) // 2
                dot_r = max(2, int(inner_size * 0.03))
                color = ACCENT_BLUE if (r + c) % 2 == 0 else ACCENT_GREEN
                i_draw.ellipse([dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r], fill=color)

    img.paste(inner_img, (offset, offset))
    img.save(os.path.join(ICONS_DIR, f'{name}.png'), 'PNG')
    print(f"Created: {os.path.join(ICONS_DIR, f'{name}.png')}")

print("Done!")