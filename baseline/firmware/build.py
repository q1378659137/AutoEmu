#!/usr/bin/env python3
"""Rebuild or verify the pinned one-shot hekate component; never fetch a moving release."""
import hashlib
import io
import time
import tempfile
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
UPSTREAM = "9bf0f7d0eebc08acfb5b1845ba56aef82e430693"
UPSTREAM_REPOSITORY = "https://github.com/easyworld/hekate"
NAMES = {"payload.bin":"hekate.bin", "nyx.bin":"nyx.bin", "libsys_minerva.bso":"libsys_minerva.bso", "libsys_lp0.bso":"libsys_lp0.bso"}

def sources():
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if not path.is_file() or any(p in {"build", "output", "__pycache__"} for p in relative.parts):
            continue
        if path.name in {"payload_00.h", "payload_01.h", "build-info.json", ".DS_Store", "lz77", "bin2c"} or path.suffix in {".o", ".d", ".elf", ".exe"}:
            continue
        yield path

def source_hash():
    h = hashlib.sha256()
    for path in sources():
        h.update(path.relative_to(ROOT).as_posix().encode()); h.update(b"\0"); h.update(path.read_bytes())
    return h.hexdigest()

def zip_bytes(target, files):
    # 用真实时间戳：ZipInfo 的 date_time 默认是 1980-01-01（不是当前时间），
    # 必须显式传当前本地时间。这样每次真正打包出来的 zip 条目时间都反映本次
    # 构建；内容一致性仍靠 sha256.json 逐文件核对，不依赖 zip 容器元数据。
    stamp = time.localtime()[:6]
    with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data in sorted(files.items()):
            entry=zipfile.ZipInfo(name,stamp); entry.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(entry,data)

def build():
    subprocess.run([sys.executable,str(ROOT/"tests/upstream_test.py")],check=True)
    compiler=shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not compiler:
        raise RuntimeError("未找到主机 C 编译器，无法验证 Switch 任务契约。")
    with tempfile.TemporaryDirectory(prefix="ns-emu-contract-") as temp:
        test=Path(temp)/("task-test.exe" if sys.platform=="win32" else "task-test")
        subprocess.run([compiler,"-std=c11","-Wall","-Wextra","-Werror",str(ROOT/"tests/task_test.c"),"-o",str(test)],check=True)
        subprocess.run([str(test)],check=True)
        handoff=Path(temp)/("handoff-test.exe" if sys.platform=="win32" else "handoff-test")
        subprocess.run([compiler,"-std=c11","-Wall","-Wextra","-Wno-unused-parameter","-I"+str(ROOT/"tests/stubs"),str(ROOT/"tests/handoff_test.c"),"-o",str(handoff)],check=True)
        subprocess.run([str(handoff)],check=True)
    digest=source_hash()
    bundle=PROJECT/"assets/auto-emu.zip"
    info_path=ROOT/"build-info.json"
    valid=False
    if info_path.exists() and bundle.exists():
        info=json.loads(info_path.read_text())
        valid=info.get("sourceHash")==digest and info.get("bundleHash")==hashlib.sha256(bundle.read_bytes()).hexdigest()
    # NS_FORCE_REPACK=1：源码没变也重新走一遍 make + 打包，让 zip 里的时间戳
    # 反映这次构建。rebuild.sh 的 full 分支会设置它（arm 分支不设置）。
    force_repack=os.environ.get("NS_FORCE_REPACK")=="1"
    if not valid or force_repack:
        devkit=os.environ.get("DEVKITARM", "/opt/devkitpro/devkitARM")
        if not (Path(devkit)/"base_rules").exists():
            raise RuntimeError("自动创建组件源码已改变，请安装 devkitARM 后重编译 firmware/build.py。")
        env=dict(os.environ,DEVKITARM=devkit)
        subprocess.run(["make","-j4"],cwd=ROOT/"hekate",env=env,check=True)
        files={name:(ROOT/"hekate/output"/source).read_bytes() for name,source in NAMES.items()}
        files.update({name:(ROOT/"resources"/name).read_bytes() for name in ("res.pak","thk.bin")})
        if len(files["payload.bin"])>126296 or (ROOT/"hekate/output/hekate_unc.bin").stat().st_size>140288:
            raise RuntimeError("临时 hekate 超过引导区安全大小限制。")
        if int.from_bytes(files["payload.bin"][280:284],"little")!=0x43544349 or files["payload.bin"][-6:]!=b"ICTC49":
            raise RuntimeError("临时启动文件签名无效。")
        hashes={name:hashlib.sha256(data).hexdigest().upper() for name,data in files.items()}
        files["sha256.json"]=json.dumps(hashes,sort_keys=True).encode()
        files["LICENSE.txt"]=(ROOT/"hekate/LICENSE").read_bytes()
        source_buffer=io.BytesIO()
        zip_bytes(source_buffer,{"firmware/"+p.relative_to(ROOT).as_posix():p.read_bytes() for p in sources()})
        files["source.zip"]=source_buffer.getvalue()
        zip_bytes(bundle,files)
        info_path.write_text(json.dumps(dict(upstreamRepository=UPSTREAM_REPOSITORY,upstream=UPSTREAM,sourceHash=digest,bundleHash=hashlib.sha256(bundle.read_bytes()).hexdigest(),assets=hashes),indent=2)+"\n")
    with zipfile.ZipFile(bundle) as archive:
        if archive.testzip(): raise RuntimeError("内置组件 ZIP 校验失败。")
    source=PROJECT/"release/NS一键换包 2.3-自动创建组件源码.zip"
    source.parent.mkdir(exist_ok=True)
    zip_bytes(source,{"firmware/"+p.relative_to(ROOT).as_posix():p.read_bytes() for p in sources()})
    print("自动创建组件源码、ARM 产物和完整对应源码包已校验。",flush=True)

if __name__=="__main__":
    try: build()
    except (RuntimeError,OSError,subprocess.CalledProcessError,zipfile.BadZipFile) as error:
        print(str(error),file=sys.stderr); sys.exit(1)
