#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Crop (and optionally rotate) an image by normalised bounds.

Usage:
    python crop_image.py <input> <output> <left> <top> <right> <bottom>
                         [long_edge] [--rotate DEG]

Bounds are 0..1 fractions of width/height, e.g. a tight centre band:
    python crop_image.py in.jpg out.jpg 0 0.1 1 0.8

--rotate follows PIL's convention: POSITIVE turns the picture
counter-clockwise. Lightroom's CropAngle uses the same visual sense, so
"match Lightroom CropAngle +0.75" means --rotate 0.75 here.

`long_edge` (default 1600) rescales the result so crops of different shapes
stay comparable; pass 0 to keep native resolution.
"""
import os
import sys

from PIL import Image


def main():
    args = sys.argv[1:]
    if len(args) < 6:
        print(__doc__)
        return 2

    rotate = 0.0
    if "--rotate" in args:
        i = args.index("--rotate")
        rotate = float(args[i + 1])
        del args[i:i + 2]

    src, dest = args[0], args[1]
    l, t, r, b = (float(v) for v in args[2:6])
    long_edge = float(args[6]) if len(args) > 6 else 1600.0

    img = Image.open(src).convert("RGB")
    if rotate:
        img = img.rotate(rotate, resample=Image.BICUBIC, expand=True)

    W, H = img.size
    box = (int(l * W), int(t * H), int(r * W), int(b * H))
    if box[2] <= box[0] or box[3] <= box[1]:
        raise SystemExit("empty crop box: %r" % (box,))

    crop = img.crop(box)
    if long_edge > 0:
        scale = long_edge / float(max(crop.size))
        crop = crop.resize(
            (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
            Image.LANCZOS,
        )

    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    crop.save(dest, quality=95, optimize=True)
    print("%s -> %s (%dx%d, aspect %.3f:1%s%s, %.2f MB)" % (
        os.path.basename(src), dest, crop.width, crop.height,
        crop.width / float(crop.height),
        ", rotated %+.2f deg" % rotate if rotate else "",
        "", os.path.getsize(dest) / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
