#!/usr/bin/env python3
"""一行结论：编译产物与发布件是否逐字节相同。

用法：
    python summary.py <hekate/output 目录> [--zip <NsToolbox.AutoEmu.zip>]

输出（UTF-8，恰好一行），退出码：
    0  四个 ARM 产物全部与发布件相同
    1  有差异（会列出第一个不同的文件）
    2  无法比对（产物缺失或找不到发布件）
"""
import argparse
import hashlib
import os
import sys
import zipfile

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PAIRS = [
    ("hekate.bin", "payload.bin"),
    ("nyx.bin", "nyx.bin"),
    ("libsys_minerva.bso", "libsys_minerva.bso"),
    ("libsys_lp0.bso", "libsys_lp0.bso"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output")
    ap.add_argument("--zip", default=None)
    a = ap.parse_args()

    zip_path = a.zip or os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "NsToolbox.App", "NsToolbox.AutoEmu.zip"))
    if not os.path.isfile(zip_path):
        print("未比对（找不到发布件 NsToolbox.AutoEmu.zip）")
        return 2
    try:
        z = zipfile.ZipFile(zip_path)
    except Exception as e:
        print(f"未比对（发布件打不开：{type(e).__name__}）")
        return 2

    diffs, missing = [], []
    for out_name, zip_name in PAIRS:
        p = os.path.join(a.output, out_name)
        if not os.path.isfile(p):
            missing.append(out_name)
            continue
        try:
            b = z.read(zip_name)
        except KeyError:
            diffs.append(f"{out_name} 发布件里没有")
            continue
        d = open(p, "rb").read()
        if d != b:
            diffs.append(f"{out_name} 本地 {len(d):,} / 发布件 {len(b):,} 字节")

    if missing:
        print("未比对（产物缺失：" + "、".join(missing) + "）")
        return 2
    if diffs:
        print("与发布件不同：" + "；".join(diffs) + "  ← 改了源码或换了上游属正常")
        return 1
    print(f"四个 ARM 产物与发布件逐字节相同（sha256 前 8 位 "
          f"{hashlib.sha256(open(os.path.join(a.output, 'hekate.bin'), 'rb').read()).hexdigest()[:8]}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
