#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lay N images out side by side in one contact sheet, with labels.

Every tile is scaled to the same height so different crops still compare
fairly. Use it to put several candidate grades of the same shot next to each
other in a single file.

Usage:
    python contact_sheet.py <out.jpg> <height> label1=path1 label2=path2 ...
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont


def font(size):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        return 2

    out = sys.argv[1]
    tile_h = int(sys.argv[2])
    items = []
    for spec in sys.argv[3:]:
        label, _, path = spec.partition("=")
        if not path or not os.path.exists(path):
            raise SystemExit("missing or bad spec: %r" % spec)
        items.append((label, path))

    tiles = []
    for label, path in items:
        im = Image.open(path).convert("RGB")
        s = tile_h / float(im.height)
        im = im.resize((max(1, round(im.width * s)), tile_h), Image.LANCZOS)
        tiles.append((label, im))

    pad = 10
    bar = 56
    W = sum(t.width for _, t in tiles) + pad * (len(tiles) - 1)
    canvas = Image.new("RGB", (W, tile_h + bar), (22, 22, 24))
    d = ImageDraw.Draw(canvas)
    f = font(30)

    x = 0
    for label, t in tiles:
        canvas.paste(t, (x, bar))
        d.text((x + 12, 13), label, font=f, fill=(240, 240, 240))
        x += t.width + pad

    canvas.save(out, quality=94, optimize=True)
    print("wrote %s (%dx%d, %.2f MB)" % (out, canvas.width, canvas.height,
                                         os.path.getsize(out) / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
