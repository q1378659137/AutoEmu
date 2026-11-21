#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""获取 Nyx 资源包 res.pak 与 TSEC keygen thk.bin —— 只用 GitHub，不碰原始 zip。

两个文件的真实来源（都实测过）
------------------------------
thk.bin
    就是 Atmosphère 仓库里的 fusee/program/tsec_keygen/tsec_keygen.bin，
    **逐字节相同**（sha256 4c04434899d04a364fe9cb98aa98c0a3，7,936 字节）。
    hekate 的 README 自己也写着「Atmosphère Tsec Hovi 密钥生成器」。

res.pak
    Nyx 的 GUI 资源包，**不能从源码重建**：
      * hekate 仓库根 res/ 只有 bootlogo + 两个 ini 模板；
      * 没有任何 Makefile / 脚本生成它（nyx.c 只是把它原样读到 NYX_RES_ADDR）；
      * 它的内容是 7 段字体位图 + 2 段 logo，偏移硬编码在源码里：
            0x00000 ubuntu_mono          (bdk/libs/lvgl/lv_fonts/ubuntu_mono.c)
            0x03A00 interui_20           (interui_20.c)
            0x07900 interui_30           (interui_30.c)
            0x0FC00 hekate_symbol_20     (hekate_symbol_20.c)
            0x14200 hekate_symbol_30     (hekate_symbol_30.c)
            0x1D900 logo 1               (nyx_gui/gfx/logos-gui.h)
            0x2BF00 logo 2               (logos-gui.h)
            0x36E00 hekate_symbol_120    (hekate_symbol_120.c)
        而字体位图是 TTF 经 lvgl 转换工具生成的，**仓库里没有任何 ttf/otf**
        （find -iname '*.ttf' 为空），所以无法复现、只能取已发布的那一份。

结论：thk.bin 走源码仓库即可；res.pak 只能取 Release 附件。
两者都在 GitHub 上，因此本工程不再需要 NsToolbox.AutoEmu.zip 提供任何素材。

用法
----
    python tools/fetch_res.py                 # 自动：thk 先取 Atmosphere，再与 release 交叉校验
    python tools/fetch_res.py --check         # 只比对，不写
    python tools/fetch_res.py --thk-source ams      # 只认 Atmosphere 源码仓库
    python tools/fetch_res.py --thk-source release  # 只认 hekate release
    python tools/fetch_res.py --repo ctcaer --ref 6.5.5
"""
import argparse
import hashlib
import io
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RES = ROOT / "baseline" / "firmware" / "resources"
VERSIONS = ROOT / "baseline" / "firmware" / "hekate" / "Versions.inc"
SRC_FILE = HERE / "_upstream"

REPOS = {"easyworld": "easyworld/hekate", "ctcaer": "CTCaer/hekate"}
AMS_THK_URL = ("https://raw.githubusercontent.com/Atmosphere-NX/Atmosphere/master/"
               "fusee/program/tsec_keygen/tsec_keygen.bin")


def log(msg=""):
    print(msg, flush=True)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read_version(p: Path):
    """Versions.inc 是 `BLVERSION_MAJOR := 6` 的 make 变量格式，解析复用 sync.py。"""
    sys.path.insert(0, str(HERE))
    import sync  # noqa: E402
    return sync.read_version(p)


def asset_url(repo_key, ver, nyx):
    if repo_key == "easyworld":
        name = f"hekate_ctcaer_{ver}_Nyx_{nyx}_sc.zip"
    else:
        name = f"hekate_ctcaer_{ver}_Nyx_{nyx}.zip"
    return (f"https://github.com/{REPOS[repo_key]}/releases/download/"
            f"v{ver}/{name}"), name


def make_opener(proxy):
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        if not proxy and os.environ.get(var):
            proxy = os.environ[var]
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers), proxy or ""


def get(op, url, timeout=180):
    with op.open(url, timeout=timeout) as r:
        return r.read()


def default_source():
    try:
        s = SRC_FILE.read_text(encoding="utf-8").strip().lower()
        if s in REPOS:
            return s
    except OSError:
        pass
    return "easyworld"


def main(argv):
    ap = argparse.ArgumentParser(description="从 GitHub 获取 res.pak / thk.bin")
    ap.add_argument("--repo", choices=sorted(REPOS), default=None,
                    help="release 来源（默认读 tools/_upstream，缺省 easyworld）")
    ap.add_argument("--ref", default=None, help="版本号，如 6.5.5；默认当前基线版本")
    ap.add_argument("--proxy", default="", help="代理，如 http://127.0.0.1:10808")
    ap.add_argument("--thk-source", choices=("auto", "ams", "release"), default="auto",
                    help="thk.bin 来源：ams=Atmosphere 源码仓库；release=hekate 附件；"
                         "auto=先 ams 再与 release 交叉校验（默认）")
    ap.add_argument("--check", action="store_true", help="只下载比对，不写文件")
    args = ap.parse_args(argv)

    if not VERSIONS.is_file():
        log(f"[失败] 找不到 {VERSIONS}")
        return 1
    cur_ver, cur_nyx = read_version(VERSIONS)
    ver = (args.ref or cur_ver).lstrip("vV")
    nyx = cur_nyx
    if not ver or "?" in ver:
        log("[失败] 读不到当前基线版本，请用 --ref 指定")
        return 1

    repo_key = args.repo or default_source()
    url, asset = asset_url(repo_key, ver, nyx)
    op, proxy = make_opener(args.proxy)

    log(f"当前基线：hekate {cur_ver} / Nyx {cur_nyx}")
    log(f"release 源：{REPOS[repo_key]}  ->  {asset}")
    if proxy:
        log(f"代理：{proxy}")
    log()

    # ---- release 包：res.pak 只能从这里取；同时留作 thk.bin 的对照 ----
    rel_zip = None
    log(f"下载 {url}")
    try:
        data = get(op, url)
        log(f"  已下载 {len(data):,} 字节")
        rel_zip = zipfile.ZipFile(io.BytesIO(data))
    except Exception as e:
        log(f"  [失败] {type(e).__name__}: {e}")
        log("         需要联网；本机通常要设代理：")
        log("         set HTTPS_PROXY=http://127.0.0.1:10808")

    def from_release(name):
        if rel_zip is None:
            return None
        try:
            return rel_zip.read(f"bootloader/sys/{name}")
        except KeyError:
            return None

    # ---- Atmosphere 源码仓库里的 thk.bin ----
    ams_thk = None
    if args.thk_source in ("auto", "ams"):
        log(f"下载 {AMS_THK_URL}")
        try:
            ams_thk = get(op, AMS_THK_URL, timeout=90)
            log(f"  已下载 {len(ams_thk):,} 字节  {sha(ams_thk)[:16]}")
        except Exception as e:
            log(f"  [失败] {type(e).__name__}: {e}")

    rel_thk = from_release("thk.bin")

    # ---- 决定 thk.bin 用哪一份 ----
    thk_new, thk_from = None, None
    if args.thk_source == "ams":
        thk_new, thk_from = ams_thk, "Atmosphere 源码仓库"
    elif args.thk_source == "release":
        thk_new, thk_from = rel_thk, "hekate release"
    else:  # auto
        if ams_thk and rel_thk and ams_thk != rel_thk:
            log()
            log("  [注意] Atmosphere 的 tsec_keygen.bin 与 hekate release 里的 thk.bin 不同：")
            log(f"         ams {len(ams_thk):,} {sha(ams_thk)[:16]}")
            log(f"         rel {len(rel_thk):,} {sha(rel_thk)[:16]}")
            log("         自动模式取 release 那份（与当前 hekate 配套）；")
            log("         若确认要用新版，跑 --thk-source ams。")
            thk_new, thk_from = rel_thk, "hekate release（ams 不一致，取配套版）"
        elif ams_thk:
            thk_new, thk_from = ams_thk, "Atmosphere 源码仓库（与 release 一致）"
        elif rel_thk:
            thk_new, thk_from = rel_thk, "hekate release（ams 取不到）"

    targets = {
        "res.pak": (from_release("res.pak"), "hekate release"),
        "thk.bin": (thk_new, thk_from),
    }

    log()
    log(f"{'文件':10s}{'来源':28s}{'新':>10s}{'本地':>10s}   结论")
    log("-" * 78)
    results = {}
    for name in ("res.pak", "thk.bin"):
        new, src = targets[name]
        dst = RES / name
        old = dst.read_bytes() if dst.is_file() else b""
        if new is None:
            log(f"{name:10s}{'（取不到）':28s}{'-':>10s}{len(old):>10,}   保持不变")
            results[name] = None
            continue
        same = old == new
        log(f"{name:10s}{src:28s}{len(new):>10,}{len(old):>10,}   "
            + ("相同" if same else "**不同**"))
        log(f"{'':10s}{sha(new)[:32]}  {sha(old)[:32] if old else '(本地缺失)'}")
        results[name] = (new, same, src)

    changed = [n for n, v in results.items() if v and not v[1]]
    log()
    if not changed:
        log("结论：本地 res.pak / thk.bin 已是最新，无需改动。")
        return 0
    if args.check:
        log(f"[check] 可更新：{'、'.join(changed)}（未写入）")
        return 0

    for name in changed:
        new, _, src = results[name]
        dst = RES / name
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        tmp.write_bytes(new)
        tmp.replace(dst)
        if dst.read_bytes() != new:
            log(f"[失败] {name} 回读不一致")
            return 1
        log(f"  已写入 {name}（{len(new):,} 字节，来源 {src}，回读一致）")

    log()
    log("下一步：这两个是打包素材，必须重跑一次打包才会进 auto-emu.zip")
    log("  build.cmd  ->  2（强制重新编译 + 打包）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
