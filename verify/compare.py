#!/usr/bin/env python3
"""比对"编译产物"与"EXE 内嵌资源"，并推算 ready.flag 应该是什么。

用法：
    python compare.py <hekate/output 目录> [--zip <NsToolbox.AutoEmu.zip>] [--original-payload <file>]

默认 zip 取仓库里的 src/NsToolbox.App/NsToolbox.AutoEmu.zip。
退出码：全部逐字节相同 = 0，否则 1。
"""
import argparse
import hashlib
import json
import os
import sys
import zipfile

# 输出固定 UTF-8：build.cmd 会先把控制台切到 65001 再调用本脚本，
# 不固定的话 Windows 上会跟随代码页，中文在切换前后不一致。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 编译产物文件名 -> 资源内文件名
PAIRS = [
    ("hekate.bin", "payload.bin"),
    ("nyx.bin", "nyx.bin"),
    ("libsys_minerva.bso", "libsys_minerva.bso"),
    ("libsys_lp0.bso", "libsys_lp0.bso"),
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output", help="hekate/output 目录")
    ap.add_argument("--zip", default=None, help="NsToolbox.AutoEmu.zip 路径")
    ap.add_argument("--original-payload", default=None,
                    help="卡上原本的 payload.bin（用来推算 ready.flag 的 payload_hash）")
    args = ap.parse_args()

    zip_path = args.zip or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "NsToolbox.App", "NsToolbox.AutoEmu.zip")
    zip_path = os.path.normpath(zip_path)
    if not os.path.isfile(zip_path):
        print(f"找不到资源包：{zip_path}", file=sys.stderr)
        return 2

    z = zipfile.ZipFile(zip_path)
    listed = json.loads(z.read("sha256.json"))

    print(f"资源包：{zip_path}  ({os.path.getsize(zip_path):,} 字节)")
    print()
    print(f"{'产物':22s}{'大小':>10s}{'资源大小':>10s}  逐字节  {'SHA-256':64s}{'清单 '}")
    print("-" * 130)

    same_all = True
    for out_name, zip_name in PAIRS:
        p = os.path.join(args.output, out_name)
        if not os.path.isfile(p):
            print(f"{out_name:22s}  缺失：{p}")
            same_all = False
            continue
        a = open(p, "rb").read()
        b = z.read(zip_name)
        ha, hb = sha(a), sha(b)
        want = listed.get(zip_name, "").lower()
        same = a == b
        same_all = same_all and same
        mark = "相同" if same else "不同"
        ok = "OK" if ha == want else "MISMATCH"
        print(f"{out_name:22s}{len(a):>10,}{len(b):>10,}  {mark:6s}  {ha}  {ok}")
        if not same:
            n = min(len(a), len(b))
            d = next((i for i in range(n) if a[i] != b[i]), n)
            print(f"    首个差异 @0x{d:X}：产物=0x{a[d]:02X} 资源=0x{b[d]:02X}")
        if ha != want:
            print(f"    清单里记的是：{want}")

    print()
    hekate_path = os.path.join(args.output, "hekate.bin")
    if not os.path.isfile(hekate_path):
        print(f"找不到编译产物：{hekate_path}", file=sys.stderr)
        print("先跑一次编译：build.cmd arm", file=sys.stderr)
        return 2
    payload = open(hekate_path, "rb").read()
    print("定制 payload 的内部签名（build.py 会校验这两项）：")
    print(f"  偏移 280 处 4 字节 : {payload[280:284]!r}  期望 b'ICTC'")
    print(f"  末尾 6 字节        : {payload[-6:]!r}  期望 b'ICTC49'")

    if args.original_payload:
        op = open(args.original_payload, "rb").read()
        print()
        print("ready.flag 应该长什么样（假设卡上原 payload.bin = 上面这个文件）：")
        print(f"  payload_size = {len(op)}")
        print(f"  payload_hash = {sha(op)}")
        print()
        print("注意：ready.flag 记的是【原】payload 的哈希，不是定制 payload 的。")
        print(f"  定制 payload SHA-256 : {sha(payload)}")
        print(f"  原 payload   SHA-256 : {sha(op)}")
        print("  两者不同是设计如此 —— 收尾时要靠它确认备份没被改动，再把原文件换回去。")
        print("  同理 payload_size 也会与部署后的 payload.bin 大小不一致，这是正常现象。")

    return 0 if same_all else 1


if __name__ == "__main__":
    sys.exit(main())
