#!/usr/bin/env python3
"""把 AutoEmu 源码工程打成一份 zip（不含任何编译产物）。

    python tools/package.py                 # 输出到 ../../../../dist/AutoEmu-源码-YYYYMMDD.zip
    python tools/package.py --out D:/x.zip  # 指定输出路径

排除：out/、baseline/assets/、baseline/release/、hekate/{build,output}/、
build-info.json、tools/_env.{cmd,sh}、tools/nstask/bin/、.sync/、__pycache__。

保留 baseline/firmware/resources/{res.pak,thk.bin} —— 它们是构建**输入素材**，
不是本工程编出来的产物（判据是"能否由本仓库源码生成"，不是"是不是二进制"）。
"""
import argparse
import hashlib
import os
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCL_PREFIX = (
    "out/",
    "baseline/assets/",
    "baseline/release/",
    "baseline/firmware/hekate/output/",
    "baseline/firmware/hekate/build/",
    "baseline/.backup/",
    "tools/nstask/bin/",
    ".sync/",
)
EXCL_NAME = {"_env.cmd", "_env.sh", "build-info.json"}
EXCL_DIR_NAME = {"__pycache__", ".git", "build", "output"}

PACKAGE_INFO = """AutoEmu —— 自动创建 emuMMC 组件的源码工程（纯源码包）
=====================================================
打包时间 : {stamp}
上游基线 : easyworld/hekate {ver} / Nyx {nyx} @ {commit}
许可     : GPL-2.0（见 baseline/firmware/hekate/LICENSE）

本包只有源码，不含任何编译产物
------------------------------
已排除：out\\、baseline\\assets\\、baseline\\release\\、
        hekate\\output\\、hekate\\build\\、build-info.json、tools\\_env.*
保留：  baseline\\firmware\\resources\\ 下的 res.pak / thk.bin —— 构建输入素材，
        缺了编不出可用的 payload。

怎么用
------
双击 build.cmd，出现菜单后输入数字：
  1 完整构建（源码没变只收拢）   2 强制重编+打包+比对   3 只编译 ARM
  4 严格校验   5 只收拢产物   6 检查上游更新   7 同步上游并应用
  8 清理构建产物   9 清除路径缓存
需要 MSYS2（usr\\bin\\bash.exe、usr\\bin\\make.exe）、devkitPro 的 devkitARM、Python 3。
找不到会提示输入路径并缓存到 tools\\_env.cmd / _env.sh。

内容
----
build.cmd       菜单入口          tools/rebuild.sh   编译逻辑（MSYS2 内执行）
tools/sync.py   同步上游          tools/package.py   打这个包
verify/compare.py  逐字节比对     verify/summary.py  一行结论
baseline/       完整源码 455 文件（hekate + 本项目改动 + build.py + 主机测试）
patches/        相对上游的 13 文件改动（unified diff + overlay）
README.md / UPGRADE.md / SYNC.md / verify-build.md
"""


def read_ver():
    inc = ROOT / "baseline/firmware/hekate/Versions.inc"
    vals = {}
    if inc.is_file():
        for line in inc.read_text(encoding="utf-8", errors="replace").splitlines():
            for key in ("BL", "NYX"):
                for part, idx in (("MAJOR", 0), ("MINOR", 1), ("HOTFX", 2)):
                    if line.strip().startswith(f"{key}VERSION_{part}"):
                        try:
                            vals.setdefault(key, ["0", "0", "0"])[idx] = line.split(":=")[1].strip()
                        except (IndexError, ValueError):
                            pass
    bl = ".".join(vals.get("BL", ["?", "?", "?"]))
    nyx = ".".join(vals.get("NYX", ["?", "?", "?"]))
    commit = "?"
    md = ROOT / "baseline/firmware/UPSTREAM.md"
    if md.is_file():
        import re
        m = re.search(r"tree/([0-9a-f]{7,40})", md.read_text(encoding="utf-8", errors="replace"))
        if m:
            commit = m.group(1)
    return bl, nyx, commit


def skip(rel: str) -> bool:
    r = rel.replace(os.sep, "/")
    if any(r.startswith(p) for p in EXCL_PREFIX):
        return True
    if os.path.basename(r) in EXCL_NAME:
        return True
    return bool(set(r.split("/")) & EXCL_DIR_NAME)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    stamp_day = time.strftime("%Y%m%d")
    out = Path(args.out) if args.out else ROOT.parents[2] / "dist" / f"AutoEmu-源码-{stamp_day}.zip"

    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCL_DIR_NAME]
        for f in filenames:
            p = Path(dirpath) / f
            rel = p.relative_to(ROOT).as_posix()
            if skip(rel):
                continue
            files.append((p, rel))
    files.sort(key=lambda t: t[1].lower())
    total = sum(p.stat().st_size for p, _ in files)
    print(f"待打包 {len(files)} 文件 / {total / 1048576:.1f} MB")

    bl, nyx, commit = read_ver()
    info = PACKAGE_INFO.format(stamp=time.strftime("%Y-%m-%d %H:%M:%S"), ver=bl, nyx=nyx, commit=commit)

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr(zipfile.ZipInfo("AutoEmu/PACKAGE-INFO.txt", time.localtime()[:6]),
                   info.encode("utf-8"))
        for p, rel in files:
            z.write(p, "AutoEmu/" + rel, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    size = out.stat().st_size
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"已生成 {out}")
    print(f"  {size:,} 字节 ({size / 1048576:.1f} MB)  压缩率 {size / max(total, 1) * 100:.0f}%")
    print(f"  sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
