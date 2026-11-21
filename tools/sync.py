#!/usr/bin/env python3
"""把上游 hekate 同步进 baseline，并重放本项目的 13 文件改动。

    python tools/sync.py                      # 检查最新 tag，只报告（不落盘）
    python tools/sync.py --ref v6.5.5         # 指定 tag / commit
    python tools/sync.py --ref v6.5.5 --apply # 真正替换 baseline

默认 dry-run。落盘前会：
  1. 备份当前 baseline/firmware/hekate 为 baseline/.backup/hekate-<旧版本>-<时间>.zip
  2. 用上游树替换，再 git apply patches/autotask.patch
  3. 从 CTCaer 对应 release 取 res.pak / thk.bin（内容相同就跳过）
  4. 更新 firmware/UPSTREAM.md 的版本记录，删除 build-info.json（强制重编）

补丁冲突时拒绝应用，让你用 patches/overlay 人工合并 —— 不猜、不覆盖。
"""
import argparse
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "baseline"
FW = BASE / "firmware"
HK = FW / "hekate"
RES = FW / "resources"
PATCH = ROOT / "patches" / "autotask.patch"
WORK = ROOT / ".sync"          # 上游工作树，可随时整个删掉
UPSTREAM_MD = FW / "UPSTREAM.md"

REPOS = {
    "easyworld": "https://github.com/easyworld/hekate.git",
    "ctcaer": "https://github.com/CTCaer/hekate.git",
}
SKIP_DIRS = {"build", "output", "__pycache__", ".git", ".sync", ".backup"}
# bin2c 生成的 C 头、以及构建时编出来的主机工具
SKIP_FILES = {"payload_00.h", "payload_01.h"}
SKIP_SUFFIX = {".o", ".d", ".elf", ".exe"}
# 本项目独有、上游一定没有的文件（不要算进"上游删除"）
OUR_FILES = {"nyx/nyx_gui/frontend/ns_task.c", "nyx/nyx_gui/frontend/ns_task.h"}


def log(msg=""):
    print(msg, flush=True)


def die(msg, code=1):
    print(f"\n[失败] {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def git(args, cwd, proxy=None, check=True):
    # core.autocrlf=false / core.eol=lf：Windows 上默认会把 checkout 出来的
    # LF 转成 CRLF，那样整棵树 411 个文件的字节都变了（上游没改也判"变了"，
    # 上游指纹校验、逐字节比对全部失效）。基线必须与上游字节一致。
    cmd = ["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf"]
    if proxy:
        cmd += ["-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}"]
    cmd += args
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：\n{(r.stderr or r.stdout).strip()[:500]}")
    return r


TEXT_SUFFIX = {".c", ".h", ".hpp", ".cpp", ".inl", ".inc", ".ld", ".s", ".S", ".mk",
               ".py", ".md", ".txt", ".json", ".yml", ".yaml", ".cfg", ".ini", ".def"}
TEXT_NAMES = {"Makefile", "LICENSE", "README", "README.md", "gitignore", ".gitignore"}


CUSTOM_FILES = [
    "bdk/mem/minerva.c", "bootloader/main.c", "nyx/Makefile", "nyx/nyx_gui/config.c",
    "nyx/nyx_gui/frontend/fe_emummc_tools.c", "nyx/nyx_gui/frontend/fe_emummc_tools.h",
    "nyx/nyx_gui/frontend/gui.c",
    "nyx/nyx_gui/frontend/gui_emummc_tools.c", "nyx/nyx_gui/frontend/gui_emummc_tools.h",
    "nyx/nyx_gui/hos/hos.c", "nyx/nyx_gui/nyx.c",
    "nyx/nyx_gui/frontend/ns_task.c", "nyx/nyx_gui/frontend/ns_task.h",
]


def refresh_overlay():
    """把"改完之后"的定制文件刷新到 patches/overlay/。

    补丁打不上时要靠 overlay 人工合并；升级后 overlay 若还是旧上游的版本，
    照着它合会把新版修正丢掉。所以每次 --apply 都跟着刷新。
    """
    ov = ROOT / "patches" / "overlay"
    n = 0
    for rel in CUSTOM_FILES:
        src = HK / rel
        if not src.is_file():
            continue
        dst = ov / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        n += 1
    log(f"  已刷新 patches/overlay（{n} 个定制文件，跟随新上游）")


def rm_tree(p: Path):
    """删目录；沙箱里 rmtree 偶尔被 trash 包装拦住，失败就挪开，别留残缺树。"""
    if not p.exists():
        return
    for _ in range(3):
        shutil.rmtree(p, ignore_errors=True)
        if not p.exists():
            return
        time.sleep(0.5)
    aside = WORK / f"old-{int(time.time())}"
    try:
        p.rename(aside)
        log(f"  [warn] 直接删除失败，已挪到 {aside}")
    except OSError:
        die(f"无法替换 {p}（目录被占用？关掉编辑器/资源管理器再试）")


def repin_upstream(commit):
    """升级后重钉上游指纹。

    build.py 会先跑 tests/upstream_test.py，它比对的 tests/easyworld-baseline.json
    记的是"上游该版本"的哈希。升版后不重钉，build.py 会以
    `AssertionError: Upstream code changed` 直接退出 —— 也就是菜单 2 失败。
    """
    script = FW / "tests" / "upstream_test.py"
    if not script.is_file():
        log("  [跳过] 没有 tests/upstream_test.py")
        return
    env = dict(os.environ, PYTHONUTF8="1")
    log("  重钉上游指纹 tests/easyworld-baseline.json ...")
    r = subprocess.run([sys.executable, str(script), "--update", "--commit", commit],
                       cwd=str(FW), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    for line in (r.stdout or "").strip().splitlines():
        log("    " + line)
    if r.returncode != 0:
        die("重钉上游指纹失败（build.py 会因此拒绝打包）：\n"
            + (r.stderr or r.stdout).strip()[:800])
    v = subprocess.run([sys.executable, str(script)], cwd=str(FW), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    for line in (v.stdout or "").strip().splitlines():
        log("    " + line)
    if v.returncode != 0:
        die("重钉后校验仍失败：\n" + (v.stderr or v.stdout).strip()[:800])


def to_lf(root: Path):
    """把文本文件统一成 LF。沙箱/Windows 上 copy+patch 可能留下混合行尾。"""
    fixed = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in TEXT_SUFFIX and p.name not in TEXT_NAMES:
            continue
        try:
            d = p.read_bytes()
        except OSError:
            continue
        if b"\r\n" in d:
            p.write_bytes(d.replace(b"\r\n", b"\n"))
            fixed += 1
    return fixed


def read_version(inc: Path):
    vals = {}
    if not inc.exists():
        return ("?", "?")
    for line in inc.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\s*(BL|NYX)VERSION_(MAJOR|MINOR|HOTFX|REL)\s*:=\s*(\d+)", line)
        if m:
            vals[(m.group(1), m.group(2))] = int(m.group(3))
    try:
        bl = f"{vals[('BL','MAJOR')]}.{vals[('BL','MINOR')]}.{vals[('BL','HOTFX')]}"
        nyx = f"{vals[('NYX','MAJOR')]}.{vals[('NYX','MINOR')]}.{vals[('NYX','HOTFX')]}"
        return bl, nyx
    except KeyError:
        return ("?", "?")


def vkey(s):
    return [int(x) for x in re.findall(r"\d+", s)] or [0]


def latest_tag(repo_url, cwd, proxy):
    r = git(["ls-remote", "--tags", "--refs", repo_url], cwd, proxy)
    tags = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            name = parts[1].rsplit("/", 1)[-1]
            if re.fullmatch(r"v\d+(\.\d+)*", name):
                tags.append((name, parts[0]))
    if not tags:
        die("上游没有任何 v* 标签，无法自动判断最新版本")
    tags.sort(key=lambda t: vkey(t[0]))
    return tags[-1]


def snapshot(root: Path):
    out = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if set(rel.parts) & SKIP_DIRS or p.name in SKIP_FILES or p.suffix in SKIP_SUFFIX:
            continue
        try:
            out[rel.as_posix()] = hashlib.sha256(
                p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        except OSError:
            continue
    return out


def diff_report(old: dict, new: dict):
    add = sorted(set(new) - set(old))
    rem = sorted(set(old) - set(new))
    mod = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    return add, rem, mod


def backup_zip(ver: str):
    d = BASE / ".backup"
    d.mkdir(parents=True, exist_ok=True)
    dst = d / f"hekate-{ver}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    n = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in HK.rglob("*"):
            if not p.is_file() or set(p.relative_to(HK).parts) & SKIP_DIRS:
                continue
            z.write(p, p.relative_to(BASE).as_posix())
            n += 1
    return dst, n


def fetch_resources(ver, nyx, proxy):
    url = (f"https://github.com/CTCaer/hekate/releases/download/v{ver}/"
           f"hekate_ctcaer_{ver}_Nyx_{nyx}.zip")
    log(f"  取官方配套资源：{url}")
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(url, timeout=120) as r:
            data = r.read()
    except Exception as e:
        log(f"  [跳过] 下载失败（{type(e).__name__}: {e}）")
        log("         资源将保持原样；若上游换过 res.pak/thk.bin，需手动更新。")
        return
    z = zipfile.ZipFile(io.BytesIO(data))
    changed = []
    for name in ("res.pak", "thk.bin"):
        try:
            new = z.read(f"bootloader/sys/{name}")
        except KeyError:
            log(f"  [跳过] release 里没有 bootloader/sys/{name}")
            continue
        dst = RES / name
        old = dst.read_bytes() if dst.exists() else b""
        if old == new:
            log(f"  {name:8s} 无变化（{len(new):,} 字节）")
        else:
            dst.write_bytes(new)
            changed.append(name)
            log(f"  {name:8s} 已更新 {len(old):,} -> {len(new):,} 字节")
    if not changed:
        log("  资源无需改动")


def update_upstream_md(ver, nyx, commit):
    if not UPSTREAM_MD.exists():
        return
    t = UPSTREAM_MD.read_text(encoding="utf-8")
    t2 = re.sub(r"简体中文\s*v\d+(?:\.\d+)*", f"简体中文 v{ver}", t)
    t2 = re.sub(r"Nyx\s*\d+(?:\.\d+)*", f"Nyx {nyx}", t2)
    t2 = re.sub(r"tree/[0-9a-f]{7,40}", f"tree/{commit}", t2)
    t2 = re.sub(r"v\d+\.\d+\.\d+ 标签", f"v{ver} 标签", t2)
    if t2 != t:
        UPSTREAM_MD.write_text(t2, encoding="utf-8")
        log(f"  已更新 {UPSTREAM_MD.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="latest", help="tag 或 commit，默认 latest")
    ap.add_argument("--repo", default="easyworld", choices=sorted(REPOS))
    ap.add_argument("--apply", action="store_true", help="真正替换 baseline（默认只检查）")
    ap.add_argument("--proxy", default=os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "")
    ap.add_argument("--quick", action="store_true",
                    help="只查最新 tag 并与本地比较，不下载源码树（几秒，适合放进一键构建）")
    ap.add_argument("--force", action="store_true",
                    help="即使上游版本与本地相同也强制重新拉取并替换 baseline")
    args = ap.parse_args()

    if not HK.is_dir() or not (HK / "Makefile").is_file():
        die(f"baseline 不完整：{HK}/Makefile 不存在")
    if not PATCH.is_file():
        die(f"缺补丁：{PATCH}")

    old_ver, old_nyx = read_version(HK / "Versions.inc")
    log(f"当前基线：hekate {old_ver} / Nyx {old_nyx}")

    crlf = [p for p in HK.rglob("*")
            if p.is_file() and p.suffix in TEXT_SUFFIX
            and p.name not in SKIP_FILES            # loader/payload_0*.h 是编译产物
            and b"\r\n" in p.read_bytes()]
    if crlf:
        log(f"  [warn] 当前基线有 {len(crlf)} 个文件是 CRLF 行尾（旧版同步留下的）。")
        log("         上游是 LF，CRLF 会让 411 个文件的字节都与上游不同；")
        log("         重新跑一次 --apply 会把行尾归一化回 LF。")

    repo_url = REPOS[args.repo]
    WORK.mkdir(parents=True, exist_ok=True)

    # ---- 拉上游 ----
    ref = args.ref
    if ref.lower() == "latest":
        log(f"\n查询 {args.repo} 最新 tag ...")
        tag, sha = latest_tag(repo_url, WORK, args.proxy)
        ref, commit = tag, sha
        log(f"  最新：{tag}  {sha[:12]}")
    else:
        commit = None

    # --quick：只回答"有没有新版"，不下载源码树。一键构建用它做只读提示。
    if args.quick:
        new_ver = ref.lstrip("vV")
        if new_ver == old_ver:
            log(f"  => 已是最新（本地 {old_ver}）")
        else:
            log(f"  => 上游 {new_ver} > 本地 {old_ver}：可用菜单 u 同步并构建")
        return 0

    # 版本相同就别折腾。baseline 里有我们自己的 11 处改动（main.c / nyx.c /
    # emummc_tools 等）和 2 个新增文件，差异统计必然报"内容不同 11"，
    # 那不是"上游有新东西"。只看 tag 才可靠。
    if (not args.force and args.ref.lower() == "latest"
            and ref.lstrip("vV") == old_ver):
        log(f"  => 与本地基线相同（hekate {old_ver}），无需同步。")
        log("     确实要重新拉一次（例如上游 force-push）：加 --force")
        return 0

    # 工作树每次重建：旧版脚本用 default autocrlf 拉过 CRLF 内容，
    # 复用会让补丁在 CRLF 树上打不干净。空间换确定性，17MB 一次很快。
    safe = re.sub(r"[^0-9A-Za-z._-]", "_", f"{args.repo}-{ref}")
    WT = WORK / safe
    if WT.is_dir():
        rm_tree(WT)
    WT.mkdir(parents=True, exist_ok=True)
    log(f"\n拉取 {args.repo} @ {ref} ...")
    if not (WT / ".git").is_dir():
        git(["init", "-q", "."], WT)
    git(["remote", "remove", "origin"], WT, check=False)
    git(["remote", "add", "origin", repo_url], WT)
    spec = ref if re.fullmatch(r"[0-9a-f]{7,40}", ref) else f"refs/tags/{ref}"
    try:
        git(["fetch", "--depth", "1", "origin", spec], WT, args.proxy)
    except RuntimeError as e:
        die(f"拉取失败（网络？代理？）\n{e}")
    git(["checkout", "-q", "-f", "FETCH_HEAD"], WT)
    # 清掉上一次同步残留的未跟踪文件，避免混进本次树
    git(["clean", "-xdfq"], WT, check=False)
    commit = commit or git(["rev-parse", "HEAD"], WT).stdout.strip()
    new_ver, new_nyx = read_version(WT / "Versions.inc")

    # ---- 补丁检查 ----
    log(f"\n上游版本：hekate {new_ver} / Nyx {new_nyx}  ({commit[:12]})")
    r = git(["apply", "--check", "-p1", str(PATCH)], WT, check=False)
    patch_ok = r.returncode == 0
    if patch_ok:
        log("  补丁检查：可以干净应用")
    else:
        log("  补丁检查：**有冲突**")
        for line in (r.stderr or r.stdout).strip().splitlines()[:12]:
            log("    " + line)

    # ---- 差异统计 ----
    old_snap = snapshot(HK)
    new_snap = snapshot(WT)
    add, rem, mod = diff_report(old_snap, new_snap)
    ours = [k for k in rem if k in OUR_FILES]
    rem_real = [k for k in rem if k not in OUR_FILES]
    log(f"\n与当前基线的差异（排除 build/ output/ 与生成物）："
        f"上游新增 {len(add)} / 上游删除 {len(rem_real)} / 内容不同 {len(mod)}")
    if ours:
        log(f"  另有本项目独有文件 {len(ours)} 个（上游没有，属预期）："
            + "、".join(Path(k).name for k in ours))
    for k in add[:12]:
        log("  + " + k)
    if len(add) > 12:
        log(f"  ... 另有 {len(add)-12} 个新增")
    for k in rem_real[:8]:
        log("  - " + k)
    if len(rem_real) > 8:
        log(f"  ... 另有 {len(rem_real)-8} 个删除")
    for k in mod[:40]:
        log("  M " + k)
    if len(mod) > 40:
        log(f"  ... 另有 {len(mod)-40} 个修改")

    # 我们的定制文件清单（用于提醒这些文件上游也改过）
    custom = ["bdk/mem/minerva.c", "bootloader/main.c", "nyx/Makefile", "nyx/nyx_gui/config.c",
              "nyx/nyx_gui/frontend/fe_emummc_tools.c", "nyx/nyx_gui/frontend/fe_emummc_tools.h",
              "nyx/nyx_gui/frontend/gui.c",
              "nyx/nyx_gui/frontend/gui_emummc_tools.c", "nyx/nyx_gui/frontend/gui_emummc_tools.h",
              "nyx/nyx_gui/hos/hos.c", "nyx/nyx_gui/nyx.c"]
    touched = [c for c in custom if c in mod]
    if touched:
        log("\n注意：以下文件既是我们的定制点，上游这一版也改过 ——")
        for c in touched:
            log("  ! " + c)
        log("  补丁若能干净应用就没问题；否则按 UPGRADE.md 用 overlay 人工合并。")

    if new_ver == old_ver and new_nyx == old_nyx and not add and not rem and not mod:
        log("\n与当前基线内容一致，无需同步。")
        return 0

    if not args.apply:
        log("\n[dry-run] 没有改动任何文件。")
        log("确认无误后加 --apply 才会替换 baseline：")
        log(f"  build.cmd sync --ref {ref} --apply")
        return 0

    if not patch_ok:
        die("补丁有冲突，拒绝自动替换。请先按 UPGRADE.md §3 手工合并，"
            "或改用 patches/overlay 逐文件覆盖后再跑 build.cmd。")

    # ---- 落盘 ----
    log("\n开始同步 ...")
    bk, n = backup_zip(old_ver)
    log(f"  备份当前基线：{bk}（{n} 文件）")

    rm_tree(HK)
    shutil.copytree(WT, HK, ignore=shutil.ignore_patterns(".git", "build", "output"))
    log(f"  已替换 {HK}")
    fixed = to_lf(HK)
    if fixed:
        log(f"  行尾归一化为 LF：{fixed} 个文件（Windows 的 autocrlf 会写 CRLF，"
            f"那样 411 个文件的字节都会变）")

    r = git(["apply", "-p1", str(PATCH)], HK, check=False)
    if r.returncode != 0:
        die(f"复制后应用补丁失败（已备份在 {bk}）：\n{(r.stderr or r.stdout).strip()[:600]}")
    log("  已应用 patches/autotask.patch")

    # 自检：定制文件必须在
    checks = [
        (HK / "nyx/nyx_gui/frontend/ns_task.c", None),
        (HK / "nyx/nyx_gui/frontend/ns_task.h", None),
        (HK / "nyx/Makefile", "ns_task"),
        (HK / "bootloader/main.c", "ns-toolbox"),
    ]
    bad = []
    for p, needle in checks:
        if not p.exists():
            bad.append(f"缺 {p.relative_to(HK)}")
        elif needle and needle not in p.read_text(encoding="utf-8", errors="replace"):
            bad.append(f"{p.relative_to(HK)} 里没有 {needle}")
    if bad:
        die("同步后自检失败：" + "；".join(bad) + f"（可从 {bk} 还原）")
    log("  自检通过：ns_task.c/h 就位，ns-toolbox 路径已改写")

    repin_upstream(commit)
    refresh_overlay()

    fetch_resources(new_ver, new_nyx, args.proxy)
    update_upstream_md(new_ver, new_nyx, commit)

    bi = FW / "build-info.json"
    if bi.exists():
        bi.unlink()
        log("  已删除 build-info.json（强制下次重编）")

    log("\n完成。下一步：")
    log("  1) build.cmd            重新编译并收拢到 out\\")
    log("  2) build.cmd verify     与发布件比对（换了上游版本，这里必然不同，属正常）")
    log("  3) 按 UPGRADE.md §2 ⑧ 上真机验收后再替换 src\\NsToolbox.App\\NsToolbox.AutoEmu.zip")
    log(f"  4) 要回滚：解压 {bk.name} 到 baseline\\ 覆盖 firmware\\hekate\\")
    return 0


if __name__ == "__main__":
    sys.exit(main())
