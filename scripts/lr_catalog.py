#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lightroom 目录参数分析工具（只读，绝不写入目录文件）

用途：不启动 Lightroom、不通过 MCP，直接读取 .lrcat 里的调色参数。
适合归纳风格、排查参数、验证 AI 写入结果。

用法:
    python lr_catalog.py list            # 列出目录内照片概览
    python lr_catalog.py show <id...>    # 打印指定照片动过的参数
    python lr_catalog.py dump <id>       # 导出完整顶层参数（含曲线原始值）
    python lr_catalog.py style           # 归纳整个目录的参数使用分布
    python lr_catalog.py hist <路径...>  # 分析 JPG 直方图（死白/死黑/冷暖）

注意：读取时加 immutable=1，不与运行中的 Lightroom 抢锁。
"""
import sqlite3
import sys
import os
import re
from collections import defaultdict

# 默认目录路径，可按需改或设环境变量 LR_CATALOG
CATALOG = os.environ.get(
    "LR_CATALOG",
    os.path.expanduser("~/Pictures/Lightroom/Lightroom Catalog.lrcat"),
)

# ---------------------------------------------------------------- 参数分组

GROUPS = {
    "影调": ["Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012",
             "Whites2012", "Blacks2012", "Texture", "Clarity2012", "Dehaze",
             "Vibrance", "Saturation"],
    "白平衡": ["Temperature", "Tint", "WhiteBalance"],
    "颜色分级(3-way)": [f"ColorGrade{p}{s}" for p in ("Shadow", "Midtone", "Highlight")
                        for s in ("Hue", "Sat", "Lum")] +
                       ["ColorGradeGlobalHue", "ColorGradeGlobalSat", "ColorGradeGlobalLum",
                        "ColorGradeBlending"],
    "分离色调(旧)": ["SplitToningShadowHue", "SplitToningShadowSaturation",
                     "SplitToningHighlightHue", "SplitToningHighlightSaturation",
                     "SplitToningBalance"],
    "相机校准": ["ShadowTint", "RedHue", "RedSaturation", "GreenHue", "GreenSaturation",
                 "BlueHue", "BlueSaturation"],
    "效果": ["PostCropVignetteAmount", "PostCropVignetteMidpoint", "GrainAmount"],
}

ZONES = ["Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta"]
GROUPS["HSL 八区"] = [f"{p}Adjustment{z}" for p in ("Hue", "Saturation", "Luminance")
                       for z in ZONES]

# Lightroom 默认值（用于判断"是否动过"）
DEFAULTS = {
    "Exposure2012": 0, "Contrast2012": 0, "Highlights2012": 0, "Shadows2012": 0,
    "Whites2012": 0, "Blacks2012": 0, "Texture": 0, "Clarity2012": 0, "Dehaze": 0,
    "Vibrance": 0, "Saturation": 0, "Tint": 0,
    "ColorGradeBlending": 50, "SplitToningBalance": 0,
    "PostCropVignetteAmount": 0, "PostCropVignetteMidpoint": 50, "GrainAmount": 0,
    "ShadowTint": 0, "RedHue": 0, "RedSaturation": 0, "GreenHue": 0,
    "GreenSaturation": 0, "BlueHue": 0, "BlueSaturation": 0,
}
for z in ZONES:
    for p in ("Hue", "Saturation", "Luminance"):
        DEFAULTS[f"{p}Adjustment{z}"] = 0
for part in ("Shadow", "Midtone", "Highlight"):
    for s in ("Hue", "Sat", "Lum"):
        DEFAULTS[f"ColorGrade{part}{s}"] = 0
DEFAULTS.update({"ColorGradeGlobalHue": 0, "ColorGradeGlobalSat": 0,
                 "ColorGradeGlobalLum": 0, "SplitToningShadowHue": 0,
                 "SplitToningShadowSaturation": 0, "SplitToningHighlightHue": 0,
                 "SplitToningHighlightSaturation": 0})


# ---------------------------------------------------------------- 目录读取

def connect(catalog=None):
    path = (catalog or CATALOG).replace("\\", "/")
    if not os.path.isfile(path):
        sys.exit(f"目录文件不存在: {path}\n可用 LR_CATALOG 环境变量指定")
    return sqlite3.connect(f"file:///{path}?immutable=1", uri=True)


def top_level(text):
    """把 Lightroom 存的 Lua 表文本解析成扁平 dict（只取顶层标量）。"""
    out, depth = {}, 0
    for ln in (text or "").split("\n"):
        s = ln.strip().rstrip(",")
        if not s or s.startswith("s ="):
            continue
        op, cl = s.count("{"), s.count("}")
        if depth == 0 and "=" in s:
            k, _, v = s.partition("=")
            out[k.strip()] = v.strip().rstrip("}")
        depth += op - cl
    return out


def fetch(con, sql, args=()):
    cur = con.cursor()
    cur.execute(sql, args)
    return cur.fetchall()


# ---------------------------------------------------------------- 子命令

def cmd_list(con):
    print("=== 目录概览 ===")
    n = fetch(con, "SELECT COUNT(*) FROM Adobe_images")[0][0]
    print(f"照片总数: {n}")
    rows = fetch(con, """
        SELECT i.fileFormat, COUNT(*) c FROM Adobe_images i
        GROUP BY i.fileFormat ORDER BY c DESC
    """)
    for fmt, c in rows:
        print(f"  {fmt or '(未知)'}: {c}")
    rows = fetch(con, """
        SELECT image, COUNT(*) c FROM Adobe_libraryImageDevelopHistoryStep
        WHERE name NOT LIKE '导入%' GROUP BY image ORDER BY c DESC
    """)
    print(f"\n有编辑历史的照片: {len(rows)} 张")
    if rows:
        print("编辑最深的 8 张:")
        for img, c in rows[:8]:
            print(f"    image {img}: {c} 步")
    # 相机/镜头
    try:
        rows = fetch(con, "SELECT DISTINCT value FROM AgInternedExifCameraModel")
        print("\n机身:", ", ".join(r[0] for r in rows if r[0]))
        rows = fetch(con, "SELECT DISTINCT value FROM AgInternedExifLens")
        print("镜头:", ", ".join(r[0] for r in rows if r[0]))
    except sqlite3.Error:
        pass


def cmd_show(con, ids):
    for pid in ids:
        row = fetch(con, "SELECT text FROM Adobe_imageDevelopSettings WHERE image = ?", (pid,))
        print("=" * 62)
        print(f"照片 id={pid}")
        print("=" * 62)
        if not row or not row[0] or not row[0][0]:
            print("  (无设置)")
            continue
        text = row[0][0]
        s = top_level(text)
        printed = False
        for gname, keys in GROUPS.items():
            moved = []
            for k in keys:
                if k not in s:
                    continue
                try:
                    val = float(s[k])
                except ValueError:
                    moved.append((k, s[k]))
                    continue
                dv = DEFAULTS.get(k)
                if dv is None or abs(val - dv) > 1e-6:
                    moved.append((k, s[k]))
            if moved:
                printed = True
                print(f"\n[{gname}]")
                for k, v in moved:
                    print(f"    {k:<32} = {v}")
        # 曲线
        for ck, label in (("ToneCurvePV2012", "主曲线"), ("ToneCurvePV2012Red", "红曲线"),
                          ("ToneCurvePV2012Green", "绿曲线"), ("ToneCurvePV2012Blue", "蓝曲线")):
            m = re.search(rf"{ck}\s*=\s*\{{([^}}]*)\}}", text)
            if m:
                pts = re.findall(r'"([^"]+)"', m.group(1))
                if len(pts) > 4:
                    print(f"\n[{label}] {len(pts)//2} 点: {pts}")


def cmd_dump(con, pid):
    row = fetch(con, "SELECT text FROM Adobe_imageDevelopSettings WHERE image = ?", (pid,))
    if not row or not row[0]:
        print("(无设置)")
        return
    print(f"# image {pid} 完整顶层参数")
    depth = 0
    for ln in row[0].split("\n"):
        s = ln.strip().rstrip(",")
        if not s or s.startswith("s ="):
            continue
        op, cl = s.count("{"), s.count("}")
        if depth == 0 and "=" in s:
            print(s)
        depth += op - cl


def cmd_style(con):
    """归纳整个目录的参数使用分布。"""
    rows = fetch(con, "SELECT image, text FROM Adobe_imageDevelopSettings WHERE text IS NOT NULL")
    all_s = [(img, top_level(t)) for img, t in rows]
    print(f"分析 {len(all_s)} 张照片\n")

    stats = defaultdict(list)
    for _, s in all_s:
        for k, v in s.items():
            try:
                stats[k].append(float(v))
            except (ValueError, TypeError):
                pass

    print(f"{'参数':<38}{'改动张数':>8}{'最小':>10}{'最大':>10}{'中位':>10}")
    print("-" * 78)
    changed = []
    for k, vals in stats.items():
        dv = DEFAULTS.get(k, 0.0)
        mod = [v for v in vals if abs(v - dv) > 0.001]
        if len(mod) >= 3:
            sv = sorted(mod)
            changed.append((len(mod), k, min(mod), max(mod), sv[len(sv)//2]))
    for n, k, lo, hi, med in sorted(changed, reverse=True):
        print(f"{k:<38}{n:>8}{lo:>10.2f}{hi:>10.2f}{med:>10.2f}")

    profs = defaultdict(int)
    lens = defaultdict(int)
    for _, s in all_s:
        if "CameraProfile" in s:
            profs[s["CameraProfile"]] += 1
        if "LensProfileName" in s:
            lens[s["LensProfileName"]] += 1
    for name, d in (("相机配置文件", profs), ("镜头配置文件", lens)):
        if d:
            print(f"\n{name}:")
            for k, v in sorted(d.items(), key=lambda x: -x[1]):
                print(f"   {v:3d} 张  {k}")


def cmd_hist(paths):
    try:
        from PIL import Image
    except ImportError:
        sys.exit("需要 Pillow：pip install Pillow")
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)

    for path in paths:
        if not os.path.isfile(path):
            print(f"不存在: {path}")
            continue
        print(f"=== {os.path.basename(path)} ===")
        im = Image.open(path).convert("RGB")
        ow, oh = im.size
        im.thumbnail((600, 600))
        px = list(im.getdata())
        n = len(px)
        lum = sorted(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in px)

        def pct(p):
            return lum[min(n - 1, int(n * p / 100))]

        print(f"  原尺寸 {ow}x{oh}")
        print(f"  亮度分位: p1={pct(1):.0f} p5={pct(5):.0f} p50={pct(50):.0f} "
              f"p95={pct(95):.0f} p99={pct(99):.0f}")
        blown = sum(1 for r, g, b in px if min(r, g, b) >= 250)
        pure = sum(1 for r, g, b in px if min(r, g, b) >= 254)
        dark = sum(1 for r, g, b in px if max(r, g, b) <= 12)
        print(f"  死白(>=250): {blown/n*100:.1f}%   纯白(254+): {pure/n*100:.1f}%   "
              f"死黑(<=12): {dark/n*100:.1f}%")

        w, h = im.size
        for name, box in {"上部(天空)": (0, 0, w, int(h * 0.25)),
                          "中部(建筑)": (0, int(h * 0.30), w, int(h * 0.60)),
                          "下部(路面)": (0, int(h * 0.65), w, h)}.items():
            cp = list(im.crop(box).getdata())
            if not cp:
                continue
            ar = sum(p[0] for p in cp) / len(cp)
            ag = sum(p[1] for p in cp) / len(cp)
            ab = sum(p[2] for p in cp) / len(cp)
            print(f"  {name}: R={ar:.0f} G={ag:.0f} B={ab:.0f}  "
                  f"{'暖' if ar > ab else '冷'}(R-B={ar-ab:+.0f})")
        print()


# ---------------------------------------------------------------- 入口

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "hist":
        if not args:
            sys.exit("用法: lr_catalog.py hist <jpg路径...>")
        cmd_hist(args)
        return
    con = connect()
    if cmd == "list":
        cmd_list(con)
    elif cmd == "show":
        cmd_show(con, [int(a) for a in args] or [])
    elif cmd == "dump":
        if not args:
            sys.exit("用法: lr_catalog.py dump <id>")
        cmd_dump(con, int(args[0]))
    elif cmd == "style":
        cmd_style(con)
    else:
        print(__doc__)
    con.close()


if __name__ == "__main__":
    main()
