# -*- coding: utf-8 -*-
"""读取 JPG 基本信息：尺寸、EXIF、文件大小、压缩比。"""
import sys, struct, os

def jpeg_info(path):
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        data = f.read()
    w = h = None
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i+1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h = struct.unpack('>H', data[i+5:i+7])[0]
            w = struct.unpack('>H', data[i+7:i+9])[0]
            break
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seglen = struct.unpack('>H', data[i+2:i+4])[0]
        i += 2 + seglen
    return w, h, size

for p in sys.argv[1:]:
    if not os.path.isfile(p):
        print(f"不存在: {p}")
        continue
    w, h, size = jpeg_info(p)
    mp = (w * h / 1e6) if w and h else 0
    print(f"{os.path.basename(p)}")
    print(f"   尺寸      : {w} x {h}  ({mp:.1f} MP)")
    print(f"   文件大小  : {size/1024/1024:.2f} MB")
    print(f"   字节/像素 : {size/(w*h):.3f}" if w and h else "")
    print(f"   完整路径  : {p}")
    print()
