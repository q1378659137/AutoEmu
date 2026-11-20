"""Guard the requested upstream Chinese UI, partition detection and creation implementation.

Two modes:

    python tests/upstream_test.py                 # verify (used by build.py)
    python tests/upstream_test.py --update         # re-pin after syncing a new upstream
    python tests/upstream_test.py --update --commit <sha>

The pinned file is tests/easyworld-baseline.json. It stores, for the pristine upstream
tree, the hashes of the files we care about plus two slices of gui_emummc_tools.c that
must keep their original behaviour. "Pristine upstream" means: our own patch reverted,
so the same file can be hashed before and after we modify it.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "tests/easyworld-baseline.json"

GUI = "hekate/nyx/nyx_gui/frontend/gui_emummc_tools.c"
FE = "hekate/nyx/nyx_gui/frontend/fe_emummc_tools.c"

# Files whose pristine-upstream hash is pinned.
HASHED_FILES = [
    "bdk/storage/emmc.c",
    "bdk/storage/nx_emmc_bis.c",
    "bdk/storage/nx_emmc_bis.h",
    "bdk/libs/lvgl/lv_fonts/harmony_os_sans_20.c",
    "bdk/libs/lvgl/lv_fonts/harmony_os_sans_30.c",
    "nyx/nyx_gui/frontend/fe_emummc_tools.c",
]

CREATION_UI_START = "static void _create_window_emummc()"
CREATION_UI_END = "\n\tif (!mbr_ctx.part_idx)\n\t\tdump_emummc_file"
PARTITION_START = "\tmemset(&mbr_ctx, 0, sizeof(mbr_ctxt_t));"
PARTITION_END = "\n\t// Equivalent to selecting Part 1"


def _slice(text, start, end, what):
    try:
        i = text.index(start)
    except ValueError:
        raise SystemExit(
            f"[FAIL] cannot find the start marker of {what} in {GUI}\n"
            f"       marker: {start!r}\n"
            f"       upstream changed this function; update the markers in tests/upstream_test.py"
        )
    try:
        j = text.index(end, i)
    except ValueError:
        raise SystemExit(
            f"[FAIL] cannot find the end marker of {what} in {GUI}\n"
            f"       marker: {end!r}\n"
            f"       upstream changed this function; update the markers in tests/upstream_test.py"
        )
    return text[i:j]


def creation_ui(text):
    return _slice(text, CREATION_UI_START, CREATION_UI_END, "creation-ui")


def partition_detection(text):
    return _slice(text, PARTITION_START, PARTITION_END, "partition-detection")


def pristine_bytes(name):
    """Bytes of `name` with this project's patch reverted (= how upstream ships it)."""
    data = (ROOT / "hekate" / name).read_bytes()
    if not name.endswith("/fe_emummc_tools.c"):
        return data
    # Revert: void -> int signature, and the F0 hidden-type guard back to the plain E0 write.
    text = data.decode("utf-8").replace("int dump_emummc_raw(", "void dump_emummc_raw(")
    text = text.replace(
        "\t\t// Keep the PC-prepared partition hidden from Windows.\n"
        "\t\tif (mbr.partitions[part_idx].type != 0xF0)\n"
        "\t\t\tmbr.partitions[part_idx].type = 0xE0;",
        "\t\tmbr.partitions[part_idx].type = 0xE0;",
    )
    tail = "\tsd_unmount();\n\treturn res;\n}\n"
    if not text.endswith(tail):
        raise SystemExit(
            f"[FAIL] {FE} does not end with the expected restore tail\n"
            f"       expected tail: {tail!r}\n"
            f"       upstream changed this function; adjust tests/upstream_test.py"
        )
    return (text[: -len("\treturn res;\n}\n")] + "}\n").encode()


def compute():
    gui = (ROOT / GUI).read_text(encoding="utf-8")
    hashes = {}
    for name in HASHED_FILES:
        hashes[name] = hashlib.sha256(pristine_bytes(name)).hexdigest()
    hashes["creation-ui"] = hashlib.sha256(creation_ui(gui).encode()).hexdigest()
    hashes["partition-detection"] = hashlib.sha256(partition_detection(gui).encode()).hexdigest()
    return hashes


def main(argv):
    update = "--update" in argv
    commit = None
    if "--commit" in argv:
        try:
            commit = argv[argv.index("--commit") + 1]
        except IndexError:
            raise SystemExit("--commit needs a value")

    current = compute()

    if update:
        pinned = {}
        if PINNED.is_file():
            try:
                pinned = json.loads(PINNED.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pinned = {}
        old = pinned.get("hashes", {})
        changed = [k for k in current if old.get(k) not in (None, current[k])]
        payload = {
            "commit": commit or pinned.get("commit", "unknown"),
            "hashes": current,
        }
        PINNED.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n",
                          encoding="utf-8")
        print(f"[OK] re-pinned {len(current)} entries to tests/easyworld-baseline.json")
        if commit:
            print(f"     commit: {commit}")
        if changed:
            print("     changed hashes: " + ", ".join(changed))
        else:
            print("     hashes unchanged")
        return 0

    if not PINNED.is_file():
        raise SystemExit(f"[FAIL] missing pin file: {PINNED}")

    expected = json.loads(PINNED.read_text(encoding="utf-8"))
    bad = []
    for name, digest in expected["hashes"].items():
        got = current.get(name)
        if got != digest:
            bad.append(name)
    if bad:
        print("[FAIL] upstream fingerprint mismatch: " + ", ".join(bad), file=sys.stderr)
        print(
            "       If you just synced a new upstream version, re-pin it:\n"
            "         python tests/upstream_test.py --update --commit <sha>\n"
            "       (build.cmd sync --apply does this automatically)\n"
            "       If you did NOT sync, one of those files was edited by hand.",
            file=sys.stderr,
        )
        return 1

    print(
        "PASS pinned easyworld Chinese UI, Part 1 capacity detection, GPT parser, "
        f"raw creation, BIS driver and fonts (hekate commit {expected.get('commit', '?')[:12]})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
