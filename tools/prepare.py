#!/usr/bin/env python3
r"""为一张具体的 TF 卡生成并【直接写入】自动创建任务所需的文件。

写进卡里的东西（和主程序 Deploy 的布局一致）：

    卡根\payload.bin                      定制 hekate（= out/hekate.bin）
    卡根\payload.bin.backup               卡上【原来】那个 payload.bin 改名而来
    卡根\ready.flag                       128 字节任务清单（注意：在根目录，不在 ns-toolbox）
    卡根\bootloader\ns-toolbox\task.bin   与 ready.flag 逐字节相同
    卡根\bootloader\ns-toolbox\payload.bin / nyx.bin / libsys_minerva.bso /
                                libsys_lp0.bso / res.pak / thk.bin

为什么 ready.flag 不能"预生成"：它的字段是这张卡的
  disk_sectors / MBR 偏移 440 的磁盘签名 / 主分区与 emuMMC 分区的起止，
  外加卡上【原 payload】的 size+sha256。Switch 侧 ns_layout_valid() 会拿它和
  卡上的 MBR 逐项比对，任何一项不符就报「SD卡与准备任务不一致」。

用法：
  python tools/prepare.py                                  # 交互，默认写卡
  python tools/prepare.py --deploy H: --disk 4             # 读物理盘参数，写 H: 卡
  python tools/prepare.py --deploy H: --mbr mbr512.bin --sectors 62333952
  python tools/prepare.py --deploy H: --sectors N --sig 0xA1B2C3D4 --emu-gib 12
  python tools/prepare.py --out out/prepare                # 只生成不写卡（老行为）

`--disk` 需要管理员权限（直接读 \\\\.\\PhysicalDriveN）。
"""
import argparse
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "out" / "hekate.bin"
BUNDLE = ROOT / "out" / "auto-emu.zip"
BUNDLE_ALT = ROOT.parents[1] / "NsToolbox.App" / "NsToolbox.AutoEmu.zip"
NSTASK = ROOT / "tools" / "nstask" / "bin" / "nstask.exe"
NS_DIR = "bootloader/ns-toolbox"
ASSETS = ["payload.bin", "nyx.bin", "libsys_minerva.bso", "libsys_lp0.bso", "res.pak", "thk.bin"]

MAGIC = b"NSTASK01"
VERSION = 1
MAIN_START = 0x8000
MIN_MAIN_COUNT = 0x400000
MIN_RAW_COUNT = 0x80F000


# ---------------------------------------------------------------- 读卡参数

def read_disk(index: int):
    """返回 (mbr512, total_sectors)。需要管理员权限。"""
    import ctypes
    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 1
    FILE_SHARE_WRITE = 2
    OPEN_EXISTING = 3
    IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    path = f"\\\\.\\PhysicalDrive{index}"
    h = k32.CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                        None, OPEN_EXISTING, 0, None)
    if h == wintypes.HANDLE(-1).value or h is None:
        err = ctypes.get_last_error()
        raise OSError(err, f"打不开 {path}（错误 {err}）—— 需要以管理员身份运行")
    try:
        buf = ctypes.create_string_buffer(512)
        got = wintypes.DWORD(0)
        if not k32.ReadFile(h, buf, 512, ctypes.byref(got), None) or got.value != 512:
            raise OSError(ctypes.get_last_error(), "读 MBR 失败")
        mbr = bytes(buf.raw[:512])

        length = ctypes.c_ulonglong(0)
        ret = wintypes.DWORD(0)
        k32.DeviceIoControl(h, IOCTL_DISK_GET_LENGTH_INFO, None, 0,
                            ctypes.byref(length), 8, ctypes.byref(ret), None)
        if not length.value:
            raise OSError(0, "取不到磁盘容量（IOCTL_DISK_GET_LENGTH_INFO 失败）")
        return mbr, length.value // 512
    finally:
        k32.CloseHandle(h)


def parse_mbr(mbr: bytes):
    if len(mbr) < 512:
        raise SystemExit("[失败] MBR 不足 512 字节")
    if mbr[510] != 0x55 or mbr[511] != 0xAA:
        raise SystemExit("[失败] MBR 结尾不是 55 AA —— 这不是有效的分区表扇区")
    parts = []
    for i in range(4):
        off = 446 + i * 16
        start, count = struct.unpack_from("<II", mbr, off + 8)
        parts.append({"n": i + 1, "type": mbr[off + 4], "start": start, "count": count})
    return struct.unpack_from("<I", mbr, 440)[0], parts


def check_layout(sig, parts, sectors):
    bad = []
    if not sectors:
        bad.append("扇区数为 0")
    if not sig:
        bad.append("磁盘签名（MBR 偏移 440）为 0")
    p1, p2 = parts[0], parts[1]
    if p1["type"] not in (0x0C, 0x07):
        bad.append(f"第 1 分区类型是 0x{p1['type']:02X}，应为 0x0C(FAT32) 或 0x07(exFAT)")
    if p1["start"] != MAIN_START:
        bad.append(f"第 1 分区起点是 {p1['start']}，应为 {MAIN_START}（16 MiB 对齐）")
    if p2["type"] != 0xF0:
        bad.append(f"第 2 分区类型是 0x{p2['type']:02X}，应为 0xF0（emuMMC 隐藏分区）")
    if p2["start"] and p2["start"] != p1["start"] + p1["count"]:
        bad.append(f"第 2 分区起点 {p2['start']} 与第 1 分区末尾 "
                   f"{p1['start'] + p1['count']} 不连续")
    for p in parts[2:]:
        if p["type"] and p["count"]:
            bad.append(f"第 {p['n']} 分区非空，工具布局只允许两个分区")
    if p1["count"] <= MIN_MAIN_COUNT:
        bad.append(f"主分区只有 {p1['count']} 扇区，需大于 {MIN_MAIN_COUNT}（4 GiB）")
    if p2["count"] < MIN_RAW_COUNT:
        bad.append(f"emuMMC 分区只有 {p2['count']} 扇区，需不少于 {MIN_RAW_COUNT}")
    if p2["start"] + p2["count"] > sectors:
        bad.append("分区超出卡容量")
    return bad


# ---------------------------------------------------------------- 清单

def build_manifest(sectors, sig, main_count, raw_count, full, payload_size,
                   payload_hash, task_id):
    raw_start = MAIN_START + main_count
    body = struct.pack(
        "<8sIIIIIIIII",
        MAGIC, VERSION, sectors, sig, MAIN_START, main_count, raw_start,
        raw_count, full, payload_size,
    ) + payload_hash + task_id + b"\x00" * 32
    assert len(body) == 124, len(body)
    return body + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)


def self_check(manifest: bytes, mbr: bytes, sectors: int):
    """等价于 C 侧的 ns_manifest_valid() + ns_layout_valid()。"""
    (magic, ver, s_sectors, sig, m_start, m_count, r_start, r_count,
     full, psize) = struct.unpack("<8sIIIIIIIII", manifest[:44])
    crc, = struct.unpack("<I", manifest[124:128])
    p = []
    if magic != MAGIC: p.append("magic 不对")
    if ver != VERSION: p.append("version 不对")
    if not s_sectors or not sig: p.append("sectors/signature 为 0")
    if m_start != MAIN_START: p.append("main_start != 0x8000")
    if m_count <= MIN_MAIN_COUNT: p.append("main_count 太小")
    if m_start + m_count != r_start: p.append("分区不连续")
    if r_count < MIN_RAW_COUNT: p.append("raw_count 太小")
    if r_start + r_count > s_sectors: p.append("分区超出卡容量")
    if full > 2: p.append("full_size 越界")
    if not (0x120 <= psize <= 0x30000): p.append("payload_size 越界")
    if manifest[92:124] != b"\x00" * 32: p.append("reserved 非零")
    if (zlib.crc32(manifest[:124]) & 0xFFFFFFFF) != crc: p.append("CRC 不对")
    if mbr:
        if sectors != s_sectors: p.append("清单扇区数与卡不符")
        msig, parts = parse_mbr(mbr)
        if msig != sig: p.append("清单签名与 MBR 不符")
        if parts[0]["start"] != m_start or parts[0]["count"] != m_count:
            p.append("主分区项与清单不符")
        if parts[1]["start"] != r_start or parts[1]["count"] != r_count:
            p.append("raw 分区项与清单不符")
        if mbr[478:510] != b"\x00" * 32: p.append("MBR 478..509 非零")
    return p


def load_assets():
    """从 auto-emu.zip 取 6 个自动创建组件。"""
    for z in (BUNDLE, BUNDLE_ALT):
        if not z.is_file():
            continue
        import zipfile
        try:
            with zipfile.ZipFile(z) as zf:
                names = set(zf.namelist())
                if set(ASSETS) <= names:
                    return {n: zf.read(n) for n in ASSETS}, z
        except (zipfile.BadZipFile, OSError):
            continue
    return None, None


def write_verified(path: Path, data: bytes):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    back = tmp.read_bytes()
    if back != data:
        raise SystemExit(f"[失败] 写入后读回不一致：{path}")
    tmp.replace(path)


def sha(b: bytes):
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- 写卡

def deploy_to_card(root: Path, manifest: bytes, assets: dict, orig_payload: bytes | None,
                   force: bool, mbr: bytes, sectors: int):
    """把 8 个文件按主程序的布局写进卡里，并逐项回读校验。"""
    if not root.is_dir():
        raise SystemExit(f"[失败] 目标不存在：{root}")
    drive = os.path.splitdrive(str(root.resolve()))[0]
    if not drive:
        raise SystemExit("[失败] 需要盘符根目录，例如 H:\\")
    sysdrive = os.environ.get("SystemDrive", "C:").upper()
    if drive.upper() == sysdrive:
        raise SystemExit(f"[失败] 拒绝写入系统盘 {sysdrive}")

    nsdir = root / "bootloader" / "ns-toolbox"
    root_flag = root / "ready.flag"
    if root_flag.exists() or (root / "payload.bin.backup").exists():
        print("  [注意] 卡上已有上一次的任务文件，将按新参数覆盖（payload.bin.backup 保留原样）")

    nsdir.mkdir(parents=True, exist_ok=True)

    # 早前版本把 ready.flag 误放进了 ns-toolbox，Switch 只认根目录那份；顺手清掉
    stray = nsdir / "ready.flag"
    if stray.exists():
        stray.unlink()
        print("  已删除错位的 bootloader/ns-toolbox/ready.flag（Switch 只读根目录的）")

    # 1) 清单（先放，失败也不影响引导）
    write_verified(nsdir / "task.bin", manifest)

    # 2) 五个配套组件（不含 payload.bin，最后单独处理）
    for n in ASSETS:
        if n == "payload.bin":
            continue
        write_verified(nsdir / n, assets[n])

    # 3) 卡根 payload.bin ↔ payload.bin.backup
    card_payload = root / "payload.bin"
    backup = root / "payload.bin.backup"
    custom = assets["payload.bin"]
    if backup.exists():
        # 已经备份过：backup 才是原始文件，保留它；卡上 payload 可能是上一次写进去的定制版
        if card_payload.exists():
            old = card_payload.read_bytes()
            if old not in (backup.read_bytes(), custom) and not force:
                raise SystemExit(
                    "[失败] 卡上 payload.bin 既不是备份内容、也不是本次要写的定制 payload；"
                    "确认要覆盖就加 --force")
        print("  卡上已有 payload.bin.backup，保留不动（收尾靠它换回去）")
    elif card_payload.exists():
        old = card_payload.read_bytes()
        card_payload.replace(backup)
        print(f"  卡上原 payload.bin → payload.bin.backup（{len(old):,} 字节，{sha(old)[:16]}…）")
    elif orig_payload is not None:
        write_verified(backup, orig_payload)
        print(f"  卡上原本没有 payload.bin，按 --payload 写入 backup（{len(orig_payload):,} 字节）")

    # 4) 定制 payload：卡根 + ns-toolbox
    write_verified(card_payload, custom)
    write_verified(nsdir / "payload.bin", custom)

    # 5) ready.flag 最后放到【卡根】（ns_task.h 里 NS_READY 就是 "ready.flag"，
    #    Switch 侧 f_stat(NS_READY) 读的是根目录，不是 ns-toolbox）
    tmp_flag = root / "ready.flag.tmp"
    write_verified(tmp_flag, manifest)
    tmp_flag.replace(root_flag)

    # 6) 回读校验
    problems = []
    if root_flag.read_bytes() != manifest:
        problems.append("ready.flag 回读不一致")
    if (nsdir / "ready.flag").exists():
        problems.append("ns-toolbox 里残留了 ready.flag")
    if (nsdir / "task.bin").read_bytes() != manifest:
        problems.append("task.bin 回读不一致")
    if sha(card_payload.read_bytes()) != sha(custom):
        problems.append("卡根 payload.bin 回读不一致")
    if sha((nsdir / "payload.bin").read_bytes()) != sha(custom):
        problems.append("ns-toolbox/payload.bin 回读不一致")
    for n in ASSETS:
        if n == "payload.bin":
            continue
        if sha((nsdir / n).read_bytes()) != sha(assets[n]):
            problems.append(f"{n} 回读不一致")
    if backup.exists() and orig_payload is not None:
        if sha(backup.read_bytes()) != sha(orig_payload):
            problems.append("payload.bin.backup 内容不是原 payload")
    if problems:
        raise SystemExit("[失败] 写入后校验不过：" + "；".join(problems))
    return nsdir


def dump_check(manifest: bytes, mbr: bytes, sectors: int):
    """用 nstask.exe（C 侧同一套判据）复核一遍；临时文件不留在卡上。"""
    if not NSTASK.is_file():
        return None
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "ready.flag"
        m = Path(td) / "sector0.bin"
        f.write_bytes(manifest)
        m.write_bytes(mbr)
        try:
            r = subprocess.run([str(NSTASK), "dump", str(f), "--mbr", str(m),
                                "--sectors", str(sectors)], capture_output=True)
            out = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
            return r.returncode, out
        except OSError as e:
            return None, str(e)


# ---------------------------------------------------------------- 主流程

def ask(prompt, default=None):
    d = f"（默认 {default}）" if default else ""
    v = input(f"{prompt}{d}: ").strip()
    return v or (default or "")


def norm_root(p):
    """把用户输入的盘符规范成根目录。

    Path("H:") 是"盘符相对路径"，Path("H:")/"payload.bin" 会拼成 "H:payload.bin"，
    即 H 盘当前的 working directory —— 不是 H:\\ 。必须补上反斜杠。
    """
    if not p:
        return None
    s = str(p).strip().strip('"').replace("：", ":").replace("/", "\\")
    if re.fullmatch(r"[A-Za-z]", s):            # "H" -> "H:\"
        s += ":\\"
    if re.fullmatch(r"[A-Za-z]:", s):
        s += "\\"
    elif re.fullmatch(r"[A-Za-z]:[^\\].*", s):
        s = s[:2] + "\\" + s[2:]
    return Path(os.path.abspath(s))


def volumes_of_disk(disk_index):
    """枚举属于某物理盘的卷，返回 [(根目录, 分区号)]。需要管理员。"""
    import ctypes
    import string
    from ctypes import wintypes

    IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x2D1080

    class SDN(ctypes.Structure):
        _fields_ = [("DeviceType", wintypes.DWORD),
                    ("DeviceNumber", wintypes.DWORD),
                    ("PartitionNumber", wintypes.DWORD)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    mask = k32.GetLogicalDrives()
    out = []
    for i, ch in enumerate(string.ascii_uppercase):
        if not ((mask >> i) & 1):
            continue
        h = k32.CreateFileW(f"\\\\.\\{ch}:", 0, 3, None, 3, 0, None)
        if h == wintypes.HANDLE(-1).value or h is None:
            continue
        try:
            sdn = SDN()
            ret = wintypes.DWORD(0)
            ok = k32.DeviceIoControl(h, IOCTL_STORAGE_GET_DEVICE_NUMBER, None, 0,
                                     ctypes.byref(sdn), ctypes.sizeof(sdn),
                                     ctypes.byref(ret), None)
            if ok and sdn.DeviceNumber == disk_index:
                out.append((f"{ch}:\\", int(sdn.PartitionNumber)))
        finally:
            k32.CloseHandle(h)
    return out


def describe_card_root(root: Path):
    """根目录里有什么，用来判断盘符是不是选错了。"""
    try:
        items = sorted(os.listdir(root))
    except OSError as e:
        return f"  读不到 {root}：{e}"
    if not items:
        return f"  {root} 是空的。"
    shown = items[:24]
    more = "" if len(items) <= 24 else f" …（共 {len(items)} 项）"
    return f"  {root} 里有：" + "、".join(shown) + more


def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def replay_args(a):
    """把已经问出来的参数序列化，供提权重开时原样带上。"""
    out = ["--elevated"]
    if a.deploy:
        out += ["--deploy", a.deploy]
    if a.disk is not None:
        out += ["--disk", str(a.disk)]
    if a.mbr:
        out += ["--mbr", a.mbr]
    if a.sectors:
        out += ["--sectors", str(a.sectors)]
    if a.sig:
        out += ["--sig", a.sig]
    if a.main_count:
        out += ["--main-count", str(a.main_count)]
    if a.raw_count:
        out += ["--raw-count", str(a.raw_count)]
    out += ["--emu-gib", str(a.emu_gib), "--full", str(a.full)]
    if a.payload:
        out += ["--payload", a.payload]
    if a.payload_hash:
        out += ["--payload-hash", a.payload_hash]
    if a.payload_size:
        out += ["--payload-size", str(a.payload_size)]
    if a.id:
        out += ["--id", a.id]
    if a.force:
        out += ["--force"]
    if a.out:
        out += ["--out", a.out]
    return out


def relaunch_as_admin(pargs):
    """用 UAC 重新启动自己；成功返回 True（由调用方 exit 42 交棒）。"""
    import ctypes
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):      # pythonw 没有控制台，新窗口会看不到输出
        exe = exe[: -len("pythonw.exe")] + "python.exe"
    script = os.path.abspath(__file__)
    params = subprocess.list2cmdline([script] + pargs)
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, os.getcwd(), 1)
    except Exception as e:
        print(f"[失败] 提权失败：{e}", file=sys.stderr)
        return False
    if rc <= 32:      # 5 = 用户点了"否"，其它见 ShellExecute 返回值
        print(f"[失败] 没有拿到管理员权限（ShellExecute 返回 {rc}）。", file=sys.stderr)
        print("       读物理盘必须要管理员：右键 build.cmd → 以管理员身份运行，", file=sys.stderr)
        print("       或者改用 --mbr / --sectors 手动给参数（不需要管理员）。", file=sys.stderr)
        return False
    return True


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--deploy", help="目标卡根，例如 H:  （默认就写卡，不落 out）")
    ap.add_argument("--disk", type=int, help="物理盘号，如 4（读 MBR 与容量，需管理员）")
    ap.add_argument("--mbr", help="MBR 扇区 dump（512 字节）")
    ap.add_argument("--sectors", type=int, default=0)
    ap.add_argument("--sig", default="", help="磁盘签名，如 0xA1B2C3D4")
    ap.add_argument("--main-count", type=int, default=0)
    ap.add_argument("--raw-count", type=int, default=0)
    ap.add_argument("--emu-gib", type=int, default=12)
    ap.add_argument("--full", type=int, default=0, choices=[0, 1, 2])
    ap.add_argument("--payload", help="卡上【原来】的 payload.bin；不给就用卡上现有的那个")
    ap.add_argument("--payload-hash", help="直接给原 payload 的 sha256（64 hex）")
    ap.add_argument("--payload-size", type=int, default=0)
    ap.add_argument("--id", help="32 hex 的任务 ID，默认随机")
    ap.add_argument("--force", action="store_true", help="允许覆盖已存在的 payload.bin.backup")
    ap.add_argument("--out", help="只生成到一个目录，不写卡（老行为）")
    ap.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-pause", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--print-elevate", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    interactive = not any([args.deploy, args.out, args.disk is not None,
                           args.mbr, args.sectors])
    if interactive:
        print("== 生成并写入 TF 卡：payload.bin / payload.bin.backup / ready.flag ==")
        print("ready.flag 绑定这张卡的 MBR（签名、分区起止）与总扇区数，不能预生成。")
        print()
        args.deploy = ask("目标卡盘符（例如 H:，或输入 auto 自动找）", "")
        if not args.deploy:
            print("[失败] 没给盘符，退出。只想生成文件不写卡就用 --out <目录>", file=sys.stderr)
            return 1
        print()
        print("读参数的方式：")
        print("  1) 直接读这张卡（需要管理员）")
        print("  2) 读一个 MBR dump 文件（512 字节）")
        print("  3) 手动输入参数")
        mode = ask("选择 [1/2/3]", "1")
        if mode == "1":
            args.disk = int(ask("物理盘号（磁盘管理里看，如 4）", ""))
        elif mode == "2":
            args.mbr = ask("MBR 文件路径", "")
            args.sectors = int(ask("整卡扇区数", ""))
        else:
            args.sectors = int(ask("整卡扇区数", ""))
            args.sig = ask("磁盘签名（如 0xA1B2C3D4，留空自动生成）", "")
            args.emu_gib = int(ask("emuMMC 容量 GiB", "12"))

    # ---- 读物理盘需要管理员：不够就自己弹 UAC 重开 ----
    if args.disk is not None and not is_admin():
        print("\n[权限] 读物理盘（\\\\.\\PhysicalDrive%d）需要管理员权限。" % args.disk)
        print("       正在向 Windows 申请（UAC）—— 允许后会新开一个管理员窗口继续。")
        if args.print_elevate:
            print("       将执行：" + subprocess.list2cmdline(
                [sys.executable, os.path.abspath(__file__)] + replay_args(args)))
            return 42
        if relaunch_as_admin(replay_args(args)):
            return 42          # build.cmd 收到 42 会提示"已在新窗口继续"
        return 1

    assets, bundle = load_assets()
    if not assets:
        print("[失败] 找不到含 6 个组件的 auto-emu.zip（先在菜单里选 2 编一次）", file=sys.stderr)
        return 1

    mbr = None
    sectors = args.sectors
    sig = int(args.sig, 0) if args.sig else 0

    if args.disk is not None:
        try:
            mbr, sectors = read_disk(args.disk)
        except OSError as e:
            print(f"[失败] {e}", file=sys.stderr)
            return 1
        print(f"读到 PhysicalDrive{args.disk}：{sectors:,} 扇区")
        sig, parts = parse_mbr(mbr)
    elif args.mbr:
        mbr = Path(args.mbr).read_bytes()[:512]
        sig, parts = parse_mbr(mbr)
        if not sectors:
            sectors = int(ask("整卡扇区数", ""))
    else:
        if not sectors:
            print("[失败] 需要 --sectors（或 --disk / --mbr 让它自己读）", file=sys.stderr)
            return 1
        if not sig:
            sig = zlib.crc32(os.urandom(16)) | 1
            print(f"未给 --sig，自动生成 0x{sig:08X}")
        aligned = sectors // 32768 * 32768
        emu = (29856 if args.full == 1 else 59680 if args.full == 2
               else args.emu_gib * 1024 + 32) * 2048
        raw_start = aligned - emu
        args.main_count, args.raw_count = raw_start - MAIN_START, emu - 2048
        parts = [{"n": 1, "type": 0x0C, "start": MAIN_START, "count": args.main_count},
                 {"n": 2, "type": 0xF0, "start": raw_start, "count": args.raw_count},
                 {"n": 3, "type": 0, "start": 0, "count": 0},
                 {"n": 4, "type": 0, "start": 0, "count": 0}]

    if args.main_count:
        parts[0]["count"] = args.main_count
    if args.raw_count:
        parts[1]["count"] = args.raw_count

    bad = check_layout(sig, parts, sectors)
    if bad:
        print("\n[失败] 这张卡不符合工具的布局，写进去也没用（Switch 会拒绝）：",
              file=sys.stderr)
        for b in bad:
            print("  - " + b, file=sys.stderr)
        print("\n  想让它能用，先走「格式化并重建 emuMMC」。", file=sys.stderr)
        return 1

    # ---- 原 payload：优先用卡上现有的那个（backup 就是它） ----
    orig = None
    card_root = norm_root(args.deploy) if args.deploy else None

    # --deploy auto：从 --disk 指向的物理盘里，自动找含 payload.bin 的那个卷
    if card_root is not None and str(args.deploy).strip().lower() == "auto":
        if args.disk is None:
            print("[失败] --deploy auto 需要同时给 --disk N", file=sys.stderr)
            return 1
        vols = volumes_of_disk(args.disk)
        if not vols:
            print(f"[失败] PhysicalDrive{args.disk} 上没有已分配盘符的卷", file=sys.stderr)
            return 1
        picked = None
        for root, part in vols:
            if (Path(root) / "payload.bin").is_file() or (Path(root) / "atmosphere").is_dir():
                picked = Path(root)
                break
        if picked is None:
            picked = Path(min(vols, key=lambda v: v[1])[0])
        print(f"  自动选中 {picked}（PhysicalDrive{args.disk} 上的卷）")
        card_root = picked

    if card_root is not None and not card_root.is_dir():
        print(f"[失败] 目标卡根不存在：{card_root}", file=sys.stderr)
        if args.disk is not None:
            for root, part in volumes_of_disk(args.disk):
                print(f"  PhysicalDrive{args.disk} 的分区 {part} → {root}", file=sys.stderr)
        return 1

    if args.payload:
        orig = Path(args.payload).read_bytes()
    elif card_root and (card_root / "payload.bin.backup").is_file():
        # 卡上已经有备份：它才是原始启动文件（卡根 payload.bin 可能已被换成定制版）
        orig = (card_root / "payload.bin.backup").read_bytes()
        print(f"用卡上已有的 payload.bin.backup 作为原启动文件（{len(orig):,} 字节）")
    elif card_root and (card_root / "payload.bin").is_file():
        orig = (card_root / "payload.bin").read_bytes()
        print(f"用卡上现有的 payload.bin 作为原启动文件（{len(orig):,} 字节）")
    elif args.payload_hash:
        p_hash = bytes.fromhex(args.payload_hash.lower().strip())
        if len(p_hash) != 32:
            print("[失败] --payload-hash 需要 64 个 hex 字符", file=sys.stderr)
            return 1
        orig = None
    if orig is not None:
        p_size, p_hash = len(orig), hashlib.sha256(orig).digest()
    elif args.payload_hash:
        p_size = args.payload_size
    else:
        print(f"[失败] 在 {card_root} 里没找到 payload.bin（也没给 --payload / --payload-hash）",
              file=sys.stderr)
        print(describe_card_root(card_root), file=sys.stderr)
        if (card_root / "atmosphere").is_dir() or (card_root / "Nintendo").is_dir():
            print("  这个根目录里有 atmosphere/Nintendo，盘符应该是对的，缺的只是 payload.bin。",
                  file=sys.stderr)
            print("  用 --payload <你的 payload.bin> 指定，或先跑一次「一键换包」把它放上去。",
                  file=sys.stderr)
        if args.disk is not None:
            vols = volumes_of_disk(args.disk)
            if vols:
                print(f"  PhysicalDrive{args.disk} 上的卷：", file=sys.stderr)
                for root, part in vols:
                    has = (Path(root) / "payload.bin").is_file()
                    print(f"    分区 {part} → {root}{'  ← 这里有 payload.bin' if has else ''}",
                          file=sys.stderr)
            print("\n  用 --deploy auto（配合 --disk）会自动选中正确的卷。", file=sys.stderr)
        return 1
    if not (0x120 <= p_size <= 0x30000):
        print(f"[失败] 原 payload 大小 {p_size} 越界（要求 288..196608 字节）", file=sys.stderr)
        return 1

    task_id = bytes.fromhex(args.id) if args.id else os.urandom(16)
    if len(task_id) != 16:
        print("[失败] --id 需要 32 个 hex 字符", file=sys.stderr)
        return 1

    manifest = build_manifest(sectors, sig, parts[0]["count"], parts[1]["count"],
                              args.full, p_size, p_hash, task_id)

    if mbr is None:
        mb = bytearray(512)
        struct.pack_into("<I", mb, 440, sig)
        for i, p in enumerate(parts[:2]):
            off = 446 + i * 16
            mb[off + 4] = p["type"]
            struct.pack_into("<II", mb, off + 8, p["start"], p["count"])
        mb[510], mb[511] = 0x55, 0xAA
        mbr = bytes(mb)

    problems = self_check(manifest, mbr, sectors)
    if problems:
        print("[失败] 自检不过：" + "；".join(problems), file=sys.stderr)
        return 1

    # ---- 落盘：默认写卡；给了 --out 才落目录 ----
    print("\n== 布局 ==")
    print(f"  整卡扇区数   {sectors:,}")
    print(f"  磁盘签名     0x{sig:08X}")
    print(f"  主分区       起点 {MAIN_START}，{parts[0]['count']:,} 扇区"
          f"（{parts[0]['count'] * 512 / 2**30:.1f} GiB）")
    print(f"  emuMMC 分区  起点 {parts[1]['start']:,}，{parts[1]['count']:,} 扇区"
          f"（{parts[1]['count'] * 512 / 2**30:.1f} GiB）")
    print(f"  原 payload   {p_size:,} 字节  {p_hash.hex()[:16]}…")
    print(f"  ready.flag   {len(manifest)} 字节  sha256 {sha(manifest)[:16]}…")

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "ready.flag").write_bytes(manifest)
        (out / "task.bin").write_bytes(manifest)
        (out / "payload.bin").write_bytes(assets["payload.bin"])
        if orig is not None:
            (out / "payload.bin.backup").write_bytes(orig)
        (out / "sector0.bin").write_bytes(mbr)
        print(f"\n== 只生成，不写卡：{out}")
    elif card_root is not None:
        print(f"\n== 写入卡 {card_root.resolve()} ==")
        try:
            nsdir = deploy_to_card(card_root, manifest, assets, orig, args.force, mbr, sectors)
        except SystemExit:
            raise
        except OSError as e:
            print(f"[失败] 写卡出错：{e}\n  卡可能被占用（资源管理器/杀软），或写保护开着。",
                  file=sys.stderr)
            return 1
        print("\n== 卡上现状 ==")
        for rel in ("ready.flag", "payload.bin", "payload.bin.backup",
                    f"{NS_DIR}/task.bin", f"{NS_DIR}/payload.bin",
                    f"{NS_DIR}/nyx.bin", f"{NS_DIR}/res.pak", f"{NS_DIR}/thk.bin"):
            f = card_root / rel
            if f.exists():
                print(f"  {rel:32s} {f.stat().st_size:>8,} 字节  {sha(f.read_bytes())[:16]}…")
            else:
                print(f"  {rel:32s} 缺失")
    else:
        print("[失败] 既没 --deploy 也没 --out", file=sys.stderr)
        return 1

    dump = dump_check(manifest, mbr, sectors)
    if dump:
        rc, text = dump
        print("\n== 交叉验证（nstask dump，和 Switch 侧同一套判据）==")
        for line in text.splitlines()[-8:]:
            print("  " + line)
        print(f"  退出码 {rc}（0 = 清单与这张卡完全匹配）")

    if card_root is not None and not args.out:
        print("\n== 下一步 ==")
        print("  安全弹出这张卡，插回 Switch 开机 —— 它会自动建 emuMMC，")
        print("  完成后自己删掉 ready.flag/task.bin/ns-toolbox 并把 payload.bin 换回 backup。")
    return 0


if __name__ == "__main__":
    rc = main(sys.argv[1:])
    # 提权重开的新窗口是独立控制台，跑完没人接，得自己停住
    if "--elevated" in sys.argv and "--no-pause" not in sys.argv and rc != 42:
        try:
            input("\n按回车关闭此窗口…")
        except (EOFError, KeyboardInterrupt):
            pass
    raise SystemExit(rc)
