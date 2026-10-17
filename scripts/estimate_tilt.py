#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Estimate camera tilt from the dominant near-vertical edges in a photo.

Usage:
    python estimate_tilt.py <image> [left] [top] [right] [bottom]

The optional bounds (0..1) restrict the analysis to a region that actually
contains architecture -- a full-frame average is easily dominated by road
markings and converging street lines.

Prints the dominant edge angle near vertical. 90.0 means the verticals are
exactly upright; 92.0 means the frame is rotated 2 degrees and needs -2 of
correction.
"""
import sys

import numpy as np
from PIL import Image


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    path = sys.argv[1]
    img = Image.open(path).convert("L")
    W, H = img.size

    if len(sys.argv) >= 6:
        l, t, r, b = (float(v) for v in sys.argv[2:6])
        img = img.crop((int(l * W), int(t * H), int(r * W), int(b * H)))
    a = np.asarray(img, dtype=np.float32)
    print("analysed region: %dx%d" % (a.shape[1], a.shape[0]))

    gx = np.zeros_like(a)
    gy = np.zeros_like(a)
    gx[:, 1:-1] = a[:, 2:] - a[:, :-2]
    gy[1:-1, :] = a[2:, :] - a[:-2, :]

    mag = np.hypot(gx, gy)
    ang = np.degrees(np.arctan2(gy, gx)) % 180.0   # 0 = horizontal, 90 = vertical

    strong = mag > np.percentile(mag, 96)
    # weight by edge strength so faint texture does not outvote real edges
    w = mag[strong]
    a_strong = ang[strong]

    hist, edges = np.histogram(a_strong, bins=180, range=(0.0, 180.0), weights=w)
    centres = (edges[:-1] + edges[1:]) / 2.0

    # peak inside the vertical band only
    band = (centres >= 75) & (centres <= 105)
    idx = np.argmax(np.where(band, hist, 0))
    peak = centres[idx]

    # parabolic refinement around the peak bin
    if 0 < idx < len(hist) - 1:
        y0, y1, y2 = hist[idx - 1], hist[idx], hist[idx + 1]
        denom = (y0 - 2 * y1 + y2)
        if denom != 0:
            peak += 0.5 * (y0 - y2) / denom * (centres[1] - centres[0])

    tilt = peak - 90.0
    print("dominant near-vertical edge : %.2f deg" % peak)
    print("implied tilt                : %+.2f deg" % tilt)
    print("correction needed           : %+.2f deg of CropAngle" % (-tilt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
