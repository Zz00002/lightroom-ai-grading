#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Estimate image tilt by maximising axis-aligned edge energy.

When a strong edge lines up with the pixel grid, the finite-difference
gradient across it is concentrated in one column, so sum(gx^2) peaks. When the
same edge is tilted, that energy spreads over many columns and the sum drops.
Sweeping the rotation and taking the argmax therefore recovers the angle that
makes the architecture upright.

The previous version of this file used a gradient-orientation histogram peak.
That approach was calibrated against known rotations and FAILED (readings moved
by <0.15 deg for a 4 deg span), so it has been replaced.

Usage:
    python level_check.py <image> [--calibrate] [--range 3] [--step 0.25]

--calibrate rotates the input by known angles first and re-runs the estimate,
proving the method actually tracks rotation before you trust its number.
"""
import sys

import numpy as np
from PIL import Image

CENTER_KEEP = 0.7


def axis_edge_energy(img, angle):
    """sum(gx^2) per pixel after rotating by `angle`, centre-cropped."""
    rot = img.rotate(angle, resample=Image.BICUBIC, expand=True)
    W, H = rot.size
    mx, my = int(W * (1 - CENTER_KEEP) / 2), int(H * (1 - CENTER_KEEP) / 2)
    rot = rot.crop((mx, my, W - mx, H - my))
    a = np.asarray(rot.convert("L"), dtype=np.float32)
    gx = a[:, 2:] - a[:, :-2]
    return float((gx ** 2).sum()) / float(a.size)


def best_angle(img, span=3.0, step=0.25):
    angles = np.arange(-span, span + 1e-9, step)
    scores = [axis_edge_energy(img, float(a)) for a in angles]
    i = int(np.argmax(scores))
    # parabolic refinement
    if 0 < i < len(scores) - 1:
        y0, y1, y2 = scores[i - 1], scores[i], scores[i + 1]
        denom = y0 - 2 * y1 + y2
        if denom != 0:
            return float(angles[i] + 0.5 * (y0 - y2) / denom * step), scores, angles
    return float(angles[i]), scores, angles


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    path = sys.argv[1]
    span = 3.0
    step = 0.25
    if "--range" in sys.argv:
        span = float(sys.argv[sys.argv.index("--range") + 1])
    if "--step" in sys.argv:
        step = float(sys.argv[sys.argv.index("--step") + 1])

    img = Image.open(path).convert("RGB")

    if "--calibrate" in sys.argv:
        print("=== calibration: rotate by a known angle, does the estimate follow? ===")
        ok = True
        for truth in (-2.0, -1.0, 1.0, 2.0):
            test = img.rotate(truth, resample=Image.BICUBIC, expand=True)
            est, _, _ = best_angle(test, span, step)
            # an image rotated by `truth` is levelled by rotating back by -truth
            residual = est + truth
            verdict = "OK" if abs(residual) < 0.5 else "FAIL"
            if verdict == "FAIL":
                ok = False
            print("  truth %+5.2f  ->  estimated levelling angle %+6.2f  "
                  "(residual %+5.2f)  %s" % (truth, est, residual, verdict))
        print("calibration: %s" % ("PASSED" if ok else "FAILED - do not trust the number"))
        print()

    est, scores, angles = best_angle(img, span, step)
    spread = max(scores) - min(scores)
    peak = max(scores)
    print("best levelling angle : %+.2f deg" % est)
    print("  -> set CropAngle to (current + %.2f)" % est)
    print("  score contrast     : %.4f%% of peak" % (100.0 * spread / peak if peak else 0.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
