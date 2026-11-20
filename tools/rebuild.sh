#!/usr/bin/env bash
# 在 MSYS2 环境内编译 AutoEmu 组件。由 build.cmd 调用，不要从 Git Bash 直接跑
# （arm-none-eabi-gcc 拿不到 TEMP，会去写 C:\WINDOWS 导致 Permission denied）。
#
# 用法：rebuild.sh [auto|arm|full|verify|collect|clean]
#   auto    （默认）源码没变就只收拢已有产物，变了走 full
#   full    端到端：主机测试 + make + 打包 auto-emu.zip
#   verify  同 full，但要求产物与发布件逐字节相同（由 build.cmd 判定）
#   collect 不编译，把已有产物收拢到 out/ 并写 MANIFEST.txt
#   clean   删除 build/ output/ assets/ release/ build-info.json 与 out/
set -uo pipefail

MODE="${1:-full}"
SELF="${BASH_SOURCE[0]}"
# 从 cmd 直接调用时这里是 Windows 风格路径，先转成 POSIX
case "$SELF" in
    [A-Za-z]:*) SELF="$(cygpath -u "$SELF")" ;;
    *\\*)       SELF="$(cygpath -u "$SELF")" ;;
esac
ROOT="$(cd "$(dirname "$SELF")/.." && pwd)"
BASE="$ROOT/baseline"
FW="$BASE/firmware"
HK="$FW/hekate"
OUT="$ROOT/out"

# MSYS2 的登录 shell 不继承调用方的环境变量（实测：从 cmd 传进去的 DEVKITARM /
# PY 在脚本里是空的），所以 build.cmd 会把解析结果同时写一份 tools/_env.sh，
# 由这里读回来，避免依赖继承。
if [ -f "$ROOT/tools/_env.sh" ]; then
    . "$ROOT/tools/_env.sh"
fi

# devkitPro 用 MSYS2 内部路径；用户若给了 Windows 路径则尝试转换
export DEVKITARM="${DEVKITARM:-/opt/devkitpro/devkitARM}"
export DEVKITPRO="${DEVKITPRO:-/opt/devkitpro}"
if [ ! -f "$DEVKITARM/base_rules" ] && [ -f "/opt/devkitpro/devkitARM/base_rules" ]; then
    export DEVKITARM=/opt/devkitpro/devkitARM
    export DEVKITPRO=/opt/devkitpro
fi
export PATH="/mingw64/bin:/usr/bin:$PATH"
export PYTHONUTF8=1
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"

# MSYS 会在启动原生子进程时自动把 /opt/... 转成 D:/...，但若外层设了
# MSYS_NO_PATHCONV / MSYS2_ENV_CONV_EXCL，转换就被关掉，Windows 版 build.py
# 会把 /opt/... 当成当前盘根下的相对路径而找不到 devkitARM。这里自己转一次。
[ -d "${DEVKITARM:-}" ] && DEVKITARM="$(cygpath -m "$DEVKITARM")" && export DEVKITARM
[ -d "${DEVKITPRO:-}" ] && DEVKITPRO="$(cygpath -m "$DEVKITPRO")" && export DEVKITPRO

log() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
die() { printf '\n[失败] %s\n' "$*" >&2; exit 1; }

say_artifacts() {
    log "产物"
    printf '  %-22s %12s  %s\n' 文件 字节 SHA-256
    for f in hekate.bin nyx.bin libsys_minerva.bso libsys_lp0.bso; do
        p="$HK/output/$f"
        if [ -f "$p" ]; then
            printf '  %-22s %12s  %s\n' "$f" "$(stat -c%s "$p")" "$(sha256sum "$p" | cut -d' ' -f1)"
        else
            printf '  %-22s %12s\n' "$f" "缺失"
        fi
    done
}

[ -f "$HK/Makefile" ] || die "找不到 $HK/Makefile —— 目录结构不对，AutoEmu 应在 src/native/ 下"

# x.y.z，取自 Versions.inc（BL / NYX 各三个字段）
ver3() {
    local k="$1" f="$HK/Versions.inc" out
    [ -f "$f" ] || { echo "?"; return; }
    out="$(awk -F':=' -v k="$k" '
        $1 ~ ("^" k "VERSION_") && $1 !~ /REL/ { v=$2; gsub(/[ \t]+/, "", v); printf "%s.", v }
    ' "$f" | sed 's/\.$//')"
    echo "${out:-?}"
}

# MANIFEST 头部用的上游标识：hekate 6.5.4 / Nyx 1.9.4 @ 9bf0f7d0
upstream_label() {
    local label="hekate $(ver3 BL) / Nyx $(ver3 NYX)" cm
    if [ -f "$FW/UPSTREAM.md" ]; then
        cm="$(grep -o 'tree/[0-9a-f]\{7,40\}' "$FW/UPSTREAM.md" | head -1 | cut -d/ -f2)"
        [ -n "${cm:-}" ] && label="$label @ ${cm:0:8}"
    fi
    echo "$label"
}

# 与发布件比对的结论（一行）；找不到发布件或 Python 时明确说明，不假装相同
compare_summary() {
    local zip="$ROOT/../../NsToolbox.App/NsToolbox.AutoEmu.zip"
    local cand pysrc="" err
    [ -f "$zip" ] || { echo "未比对（找不到发布件 NsToolbox.AutoEmu.zip）"; return 0; }
    [ -f "$ROOT/verify/summary.py" ] || { echo "未比对（缺 verify/summary.py）"; return 0; }

    # 候选：环境里的 PY、PATH 上的 python3 / python；每个都先跑一次确认能用
    for cand in "${PY:-}" "$(cygpath -u "${PY:-}" 2>/dev/null)" \
                "$(command -v python3 || true)" "$(command -v python || true)"; do
        [ -n "$cand" ] || continue
        [ -x "$cand" ] || continue
        if "$cand" -c "import sys" >/dev/null 2>&1; then
            pysrc="$cand"
            break
        fi
    done
    if [ -z "$pysrc" ]; then
        echo "未比对（找不到可用的 Python）"
        return 0
    fi

    err="$("$pysrc" "$(cygpath -m "$ROOT/verify/summary.py")" "$(cygpath -m "$HK/output")" \
            --zip "$(cygpath -m "$zip")" 2>&1)" || true
    if [ -n "$err" ]; then
        printf '%s\n' "$err" | tail -1
    else
        echo "未比对（summary.py 无输出）"
    fi
}

# 把产物收拢到一个固定目录，并写清单，方便直接取用
collect() {
    mkdir -p "$OUT" || die "无法创建 $OUT"
    rm -f "$OUT"/* 2>/dev/null || true
    local n=0 f
    for f in hekate.bin nyx.bin libsys_minerva.bso libsys_lp0.bso; do
        if [ -f "$HK/output/$f" ]; then
            cp "$HK/output/$f" "$OUT/" && n=$((n + 1))
        fi
    done
    if [ -f "$BASE/assets/auto-emu.zip" ]; then
        cp "$BASE/assets/auto-emu.zip" "$OUT/" && n=$((n + 1))
    fi
    [ "$n" -gt 0 ] || { echo "没有可收拢的产物，先跑一次编译" >&2; return 1; }

    local rows
    rows="$(for f in "$OUT"/*; do
        [ -f "$f" ] || continue
        printf '%-22s %12s  %s\n' "$(basename "$f")" "$(stat -c%s "$f")" "$(sha256sum "$f" | cut -d' ' -f1)"
    done)"

    {
        echo "AutoEmu 编译产物"
        echo "生成时间 : $(date '+%Y-%m-%d %H:%M:%S')"
        echo "工具链   : $("$DEVKITARM/bin/arm-none-eabi-gcc" --version 2>/dev/null | head -1)"
        echo "上游     : $(upstream_label)"
        echo "对照     : src/NsToolbox.App/NsToolbox.AutoEmu.zip"
        echo
        printf '%-22s %12s  %s\n' FILE BYTES SHA-256
        printf '%-22s %12s  %s\n' ---------------------- ------------ ----------------------------------------
        printf '%s\n' "$rows"
        echo
        echo "$(compare_summary)"
    } > "$OUT/MANIFEST.txt"

    echo
    echo "已收拢到 $OUT"
    sed 's/^/  /' "$OUT/MANIFEST.txt"
}

case "$MODE" in
collect)
    collect
    exit $?
    ;;
clean)
    log "清理构建产物"
    rm -rf "$HK/build" "$HK/output" "$BASE/assets" "$BASE/release" "$FW/build-info.json" "$OUT"
    # bin2c 在 loader/ 里生成的载荷头，也是编译产物
    rm -f "$HK/loader/payload_00.h" "$HK/loader/payload_01.h"
    echo "已删除 build/ output/ assets/ release/ build-info.json out/ 与 loader/payload_0*.h"
    exit 0
    ;;
arm|full|verify|auto) ;;
*)
    die "未知模式：$MODE（可用 auto / arm / full / verify / collect / clean）"
    ;;
esac

[ -f "$DEVKITARM/base_rules" ] || die "devkitARM 不完整：$DEVKITARM/base_rules 不存在
  期望位置：<MSYS2>/opt/devkitpro/devkitARM"

# auto（默认）：源码没变且产物齐全时只收拢，不重编；否则走 full
if [ "$MODE" = "auto" ]; then
    if [ -f "$FW/build-info.json" ] && [ -f "$BASE/assets/auto-emu.zip" ] && [ -f "$HK/output/hekate.bin" ]; then
        PYTMP="${PY:-}"
        if [ -n "$PYTMP" ]; then
            PYTMP="$(cygpath -u "$PYTMP" 2>/dev/null || echo "$PYTMP")"
        else
            PYTMP="$(command -v python3 || command -v python || true)"
        fi
        if [ -n "$PYTMP" ]; then
            FWWIN="$(cygpath -m "$FW")"
            now="$("$PYTMP" -c "import importlib.util,sys; s=importlib.util.spec_from_file_location('b',sys.argv[1]+'/build.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.source_hash())" "$FWWIN" 2>/dev/null)"
            have="$("$PYTMP" -c "import json,sys; print(json.load(open(sys.argv[1],encoding='utf-8')).get('sourceHash',''))" "$FWWIN/build-info.json" 2>/dev/null)"
            if [ -n "$now" ] && [ "$now" = "$have" ]; then
                log "源码未变化，产物已是最新 —— 只做收拢"
                say_artifacts
                collect
                exit 0
            fi
            log "源码有变化（或产物不齐），转完整构建"
        fi
    else
        log "没有可用产物，转完整构建"
    fi
    MODE=full
fi

log "环境"
printf '  DEVKITARM : %s\n' "$DEVKITARM"
printf '  Make      : %s\n' "$(make --version 2>/dev/null | head -1)"
printf '  gcc       : %s\n' "$("$DEVKITARM/bin/arm-none-eabi-gcc" --version 2>/dev/null | head -1)"
printf '  并行      : -j%s\n' "$JOBS"

if [ "$MODE" = "arm" ]; then
    log "编译 ARM 组件（不打包）"
    ( cd "$HK" && make -j"$JOBS" ) || die "make 失败"
    say_artifacts
    collect || true
    printf '\n下一步：build.cmd verify 可与发布件比对。\n'
    exit 0
fi

# full / verify
PYW="${PY:-}"
if [ -n "$PYW" ]; then
    PY="$(cygpath -u "$PYW" 2>/dev/null || echo "$PYW")"
else
    PY="$(command -v python3 || command -v python || true)"
fi
[ -n "${PY:-}" ] || die "找不到 Python。用 set PY=<python.exe 路径> 指定"

log "端到端构建（主机测试 → make → 打包）"
printf '  Python    : %s\n' "$PY"
mkdir -p "$BASE/assets" "$BASE/release" || die "无法创建 assets/ release/"
( cd "$FW" && "$PY" build.py ) || die "build.py 失败（详见上面的输出）"

say_artifacts
log "整包"
BUNDLE="$BASE/assets/auto-emu.zip"
[ -f "$BUNDLE" ] || die "没有生成 $BUNDLE"
printf '  %s\n  %s 字节  %s\n' "$BUNDLE" "$(stat -c%s "$BUNDLE")" "$(sha256sum "$BUNDLE" | cut -d' ' -f1)"
collect || true
printf '\n下一步：把 auto-emu.zip 替换到 src/NsToolbox.App/NsToolbox.AutoEmu.zip，然后重编主程序。\n'
