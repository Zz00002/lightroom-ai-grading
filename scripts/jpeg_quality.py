# -*- coding: utf-8 -*-
"""Report the actual JPEG quality of a file by reading its quantisation tables.

The encoder's quality setting is not stored anywhere in the file, but the
quantisation tables it produced are, and the standard IJG scaling can be
inverted to recover an equivalent quality figure. This is the only honest way
to tell whether a "quality 100" export really was one.

Usage:
    python jpeg_quality.py <file.jpg> [...]
"""
import os
import sys

# IJG Annex K baseline luminance table, the reference the scaling is defined against
STD_LUMA = [
    16, 11, 10, 16, 24, 40, 51, 61,
    12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77,
    24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99,
]


def read_dqt(data):
    """Return the list of quantisation tables found in the JPEG byte stream."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    i = 2
    tables = []
    while i < len(data) - 1:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = (data[i + 2] << 8) | data[i + 3]
        if marker == 0xDB:                       # DQT
            p = i + 4
            end = i + 2 + seg_len
            while p < end:
                pq, tq = data[p] >> 4, data[p] & 0x0F
                p += 1
                n = 64 * (2 if pq else 1)
                if pq:
                    vals = [(data[p + 2 * k] << 8) | data[p + 2 * k + 1] for k in range(64)]
                else:
                    vals = list(data[p:p + 64])
                p += n
                tables.append((tq, vals))
        elif marker == 0xDA:                     # start of scan -> stop
            break
        i += 2 + seg_len
    return tables


def estimate_quality(table):
    """Invert the IJG scaling from a luminance quantisation table."""
    best, best_err = None, None
    for q in range(1, 101):
        scale = 5000 // q if q < 50 else 200 - 2 * q
        err = 0.0
        for std, got in zip(STD_LUMA, table):
            want = max(1, min(255, (std * scale + 50) // 100))
            err += (want - got) ** 2
        if best_err is None or err < best_err:
            best, best_err = q, err
    return best, best_err


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    for path in sys.argv[1:]:
        with open(path, "rb") as fh:
            data = fh.read()
        tables = read_dqt(data)
        luma = next((t for tq, t in tables if tq == 0), None)
        if luma is None:
            print("%-34s no luminance DQT found" % os.path.basename(path))
            continue
        q, err = estimate_quality(luma)
        print("%-34s %8.2f MB   luminance table AC[1]=%3d  DC=%3d   => approx quality %d"
              % (os.path.basename(path), len(data) / 1048576.0,
                 luma[1], luma[0], q))
    return 0


if __name__ == "__main__":
    sys.exit(main())
