# -*- coding: utf-8 -*-
"""分析照片直方图：判断高光/暗部是否溢出（没有细节可救）。"""
import sys, os, struct, zlib

def read_jpeg_pixels(path, max_side=600):
    """优先用 PIL，没有就退化为只读文件头。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    im = Image.open(path).convert('RGB')
    im.thumbnail((max_side, max_side))
    return im

def rgb_triples(im):
    """取出 [(r, g, b), ...]。

    Pillow 12 起 Image.getdata() 被标记弃用（Pillow 14 会移除），而它的替代品
    get_flattened_data() 返回的是「扁平的通道序列」、且旧版 Pillow 里根本不存在。
    直接用 tobytes() 最稳：各版本行为一致，也比 getdata() 快。
    """
    raw = im.tobytes()
    return list(zip(raw[0::3], raw[1::3], raw[2::3]))


def analyze(path):
    print(f"=== {os.path.basename(path)} ===")
    im = read_jpeg_pixels(path)
    if im is None:
        print("  (无 PIL，无法分析像素)")
        return
    w, h = im.size
    px = rgb_triples(im)
    n = len(px)
    # 亮度
    lum = [0.2126*r + 0.7152*g + 0.0722*b for r, g, b in px]
    lum.sort()
    def pct(p):
        return lum[min(n-1, int(n*p/100))]
    print(f"  尺寸(缩略): {w}x{h}  像素数: {n}")
    print(f"  亮度分位:  p1={pct(1):.0f}  p5={pct(5):.0f}  p50={pct(50):.0f}  "
          f"p95={pct(95):.0f}  p99={pct(99):.0f}  max={lum[-1]:.0f}")

    # 高光溢出统计（三通道同时 >=250 视为死白）
    blown_any = sum(1 for r, g, b in px if r >= 250 and g >= 250 and b >= 250)
    blown_all = sum(1 for r, g, b in px if r >= 254 and g >= 254 and b >= 254)
    near_white = sum(1 for r, g, b in px if min(r, g, b) >= 240)
    dark = sum(1 for r, g, b in px if max(r, g, b) <= 12)
    print(f"  死白像素(>=250): {blown_any/n*100:.1f}%   纯白(254+): {blown_all/n*100:.1f}%")
    print(f"  近白(>=240)    : {near_white/n*100:.1f}%   死黑(<=12): {dark/n*100:.1f}%")

    # 分区平均色（判断冷暖）
    regions = {}
    for name, box in {
        "上部(天空)": (0, 0, w, int(h*0.25)),
        "中部(建筑)": (0, int(h*0.30), w, int(h*0.60)),
        "下部(路面)": (0, int(h*0.65), w, h),
    }.items():
        crop = im.crop(box)
        cp = rgb_triples(crop)
        if not cp:
            continue
        ar = sum(p[0] for p in cp)/len(cp)
        ag = sum(p[1] for p in cp)/len(cp)
        ab = sum(p[2] for p in cp)/len(cp)
        regions[name] = (ar, ag, ab)
        warm = "暖" if ar > ab else "冷"
        print(f"  {name}: R={ar:.0f} G={ag:.0f} B={ab:.0f}  → {warm}(R-B={ar-ab:+.0f})")

for p in sys.argv[1:]:
    if os.path.isfile(p):
        analyze(p)
        print()
    else:
        print(f"不存在: {p}")
