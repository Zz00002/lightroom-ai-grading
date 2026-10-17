#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stack an original and a graded render of the same photo into one
side-by-side comparison JPEG, so the difference is impossible to miss.

Usage:
    python make_compare.py <original.jpg> <graded.jpg> <output.jpg> [label_a] [label_b]

Both inputs are normalised to the same width and stacked vertically:
the original on top, the graded version below, each with a label bar.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont


MAX_WIDTH = 1800


def load_font(size):
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",      # Microsoft YaHei (CJK)
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def fit_width(img, width):
    if img.width == width:
        return img
    height = max(1, round(img.height * width / img.width))
    return img.resize((width, height), Image.LANCZOS)


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2

    src_a, src_b, dest = sys.argv[1], sys.argv[2], sys.argv[3]
    label_a = sys.argv[4] if len(sys.argv) > 4 else "原片 BEFORE"
    label_b = sys.argv[5] if len(sys.argv) > 5 else "修后 AFTER"

    a = Image.open(src_a).convert("RGB")
    b = Image.open(src_b).convert("RGB")

    # Cap the comparison width: full-resolution exports are 6000px wide, which
    # would make a stacked pair absurdly large and slow to open.
    width = min(max(a.width, b.width), MAX_WIDTH)
    a, b = fit_width(a, width), fit_width(b, width)

    pad = 14
    bar = 64
    height = bar + a.height + pad + bar + b.height + pad

    canvas = Image.new("RGB", (width, height), (22, 22, 24))
    draw = ImageDraw.Draw(canvas)
    font = load_font(36)

    y = 0
    draw.rectangle([0, y, width, y + bar], fill=(38, 38, 42))
    draw.text((22, y + 14), label_a, font=font, fill=(235, 235, 235))
    y += bar

    canvas.paste(a, (0, y))
    y += a.height

    draw.rectangle([0, y, width, y + bar], fill=(38, 38, 42))
    draw.text((22, y + 14), label_b, font=font, fill=(255, 214, 110))
    y += bar

    canvas.paste(b, (0, y))

    canvas.save(dest, quality=92, optimize=True)
    print("%s  ->  %s  (%dx%d, %.2f MB)" % (
        os.path.basename(src_a), dest, canvas.width, canvas.height,
        os.path.getsize(dest) / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
