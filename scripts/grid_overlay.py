#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Overlay a reference grid on an image so tilt can be judged by eye.

Two automated tilt estimators were built for this session and BOTH failed
synthetic calibration (see level_check.py), so the grid is the honest tool:
it does not claim a number, it just gives the eye a straight reference.

Usage:
    python grid_overlay.py <input> <output> [spacing_px] [rotate_deg] [line_alpha]
"""
import sys

from PIL import Image, ImageDraw

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    src, dest = sys.argv[1], sys.argv[2]
    spacing = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    rotate = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
    alpha = float(sys.argv[5]) if len(sys.argv) > 5 else 0.45

    img = Image.open(src).convert("RGB")
    if rotate:
        img = img.rotate(rotate, resample=Image.BICUBIC, expand=True)

    W, H = img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    a = int(255 * alpha)

    for x in range(0, W, spacing):
        d.line([(x, 0), (x, H)], fill=(0, 255, 255, a), width=1)
    for y in range(0, H, spacing):
        d.line([(0, y), (W, y)], fill=(0, 255, 255, a), width=1)

    # centre cross, brighter, as the primary reference
    cx, cy = W // 2, H // 2
    d.line([(cx, 0), (cx, H)], fill=(255, 80, 80, 255), width=2)
    d.line([(0, cy), (W, cy)], fill=(255, 80, 80, 255), width=2)

    out = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    out.save(dest, quality=92, optimize=True)
    print("%s -> %s (%dx%d, rotate %+.2f deg, grid %dpx)" % (
        src, dest, out.width, out.height, rotate, spacing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
