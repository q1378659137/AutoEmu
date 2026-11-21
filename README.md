# AutoEmu —— 自动创建 emuMMC 组件的源码工程

`NsToolbox.AutoEmu.zip`（主程序里那个 2,819,877 字节的嵌入资源）的**完整源码与改动集**。
把这个目录单独拎出来的目的只有一个：**Switch 系统升版、hekate 跟不上时，能自己改、自己编**。

原来的 `../hekate-automation/` 只有说明文字；这里是可编译、可 diff、可校验的工程。

---

## 目录

```
AutoEmu/
├─ build.cmd               ★ 菜单式入口（双击 → 输入数字；自动找环境，找不到会问路径）
├─ README.md / UPGRADE.md / SYNC.md / verify-build.md
├─ baseline/               完整源码（455 文件，从 EXE 内嵌 source.zip 原样解出）
│  └─ firmware/
│     ├─ UPSTREAM.md       上游版本、提交、定制点自述
│     ├─ build.py          官方构建脚本（产出 assets/auto-emu.zip）
│     ├─ hekate/           easyworld/hekate 6.5.5 全量源码 + 本项目改动
│     ├─ resources/        res.pak / thk.bin（CTCaer 官方配套，6.5.4→6.5.5 未变）
│     └─ tests/            handoff_test.c / task_test.c 等主机侧测试
├─ patches/
│  ├─ autotask.patch       相对上游提交 9bf0f7d0 的 unified diff（13 个文件）
│  └─ overlay/             同样 13 个文件的"改完之后"版本，按上游路径摆放
├─ tools/
│  ├─ menu.txt             菜单文案（UTF-8，由 build.cmd 在 65001 下 type 出来）
│  ├─ rebuild.sh           真正的编译逻辑（由 build.cmd 在 MSYS2 里调用）
│  ├─ sync.py              同步上游 hekate（拉取 → 检查补丁 → 可选替换）
│  ├─ prepare.py           按一张卡生成 ready.flag / task.bin，并备好 payload.bin
│  ├─ package.py           把本工程打成纯源码 zip
│  └─ nstask/              PC 侧协议工具（纯 C，无第三方依赖）
└─ verify/
   ├─ compare.py           编译产物 vs 发布件逐字节比对（详细表）
   └─ summary.py           同一件事的"一行结论"，供 MANIFEST.txt 使用
```

`patches/` 两个形态是冗余的，但用途不同：

- **patch** 用于"上游没怎么变"的情况，`git apply` 一步到位，能用 `--check` 验；
- **overlay** 用于"上游大改、patch 打不上"的情况，直接覆盖再人工合并，比逐块调冲突快。

---

## 快速开始

### 1. 一键编译（推荐）

**双击 `build.cmd`，出现菜单，输入数字回车。**

```
  ================================================================
    NS Toolbox  AutoEmu  ——  编译 / 同步 / 校验
  ================================================================

    1   完整构建          源码没变就只收拢，变了自动重编
    2   强制重新编译      重编 + 打包 + 与发布件比对
    3   只编译 ARM        不打包，最快
    4   严格校验          要求与发布件逐字节相同
    5   只收拢产物        不编译，刷新 out\ 与 MANIFEST.txt
    6   检查上游更新      只报告差异，不改任何文件
    7   同步上游并应用    替换 baseline（自动先备份）
    8   清理构建产物      删 build\ output\ assets\ release\ out\
    9   清除路径缓存      下次重新查找 MSYS2 / devkitARM / Python
    p   生成任务文件      按一张具体的卡生成 ready.flag + payload.bin
    s   切换更新源        在 easyworld 与 CTCaer 之间选
    h   帮助
    0   退出

  输入编号回车即可。直接回车 = 1。
  更新源：easyworld/hekate（简体中文界面，版本可能慢一点）
  >> current baseline: hekate 6.5.5

  Select [1-9 / h / 0 = quit]:
```

菜单里最常用的是 `1`（日常）和 `2`（改过源码后强制全编）。窗口跑完会停住等你按键，
方便看结果；自动化调用可以设 `set AUTOEMU_NO_PAUSE=1` 跳过。

需要脚本化时也能直接带参数（等价于菜单项）：

| 命令 | 等价菜单 | 作用 | 耗时 |
|---|---|---|---|
| `build.cmd` | — | 弹菜单 | — |
| `build.cmd auto` / `1` | 1 | 源码没变就只把产物收拢到 `out\`；变了自动走 full | 秒级 / 约 4 分钟 |
| `build.cmd full` / `2` | 2 | 强制重编 ARM + 打整包 + 与发布件比对 | 约 4 分钟 |
| `build.cmd arm` / `3` | 3 | 只编 ARM 组件，不打包 | 约 4 分钟 |
| `build.cmd verify` / `4` | 4 | 同 full，且要求与发布件**逐字节相同** | 约 4 分钟 |
| `build.cmd collect` / `5` | 5 | 不编译，把已有产物收拢到 `out\` 并写 MANIFEST | 秒级 |
| `build.cmd sync` / `6` | 6 | 检查上游 hekate 新版（**默认 dry-run**） | 秒级 |
| `build.cmd sync --apply` | 7 | 同上但真正替换 `baseline\`（会先备份） | 约 1 分钟 |
| `build.cmd clean` / `8` | 8 | 删 `build/ output/ assets/ release/ build-info.json out/` | — |
| `build.cmd reset` / `9` | 9 | 清掉路径缓存 | — |
| `build.cmd prepare` / `p` | p | 按一张具体的卡生成 `ready.flag` + `payload.bin` | 秒级 |

## payload.bin 与 ready.flag 从哪来

| 文件 | 能不能"编译出来" | 说明 |
|---|---|---|
| **`payload.bin`** | **能**，就是编译产物 | `out\hekate.bin` 改名即可，两者逐字节相同（107,236 字节 / `a9aacc51…`）。`auto-emu.zip` 里的 `payload.bin` 也是同一份。 |
| **`ready.flag`** | **不能预生成**，只能"按卡生成" | 128 字节清单，里面是这张卡的 `disk_sectors`、MBR 偏移 440 的随机磁盘签名、主/emuMMC 分区的起止扇区，外加**卡上原来那个 payload** 的大小与 SHA-256。Switch 侧 `ns_layout_valid()` 会把清单与卡上的 MBR 逐项比对，任何一项不符就报「SD卡与准备任务不一致」。 |

所以流程只能是：**先把卡按工具布局分好区（写 MBR），再为这张卡生成 `ready.flag`**。

菜单里按 `p`（或 `build.cmd prepare`）就是干这件事，**产物直接写进那张卡，不落 `out\`**：

```bat
:: 卡插着，交互输入盘符（读 MBR 需要管理员）
build.cmd prepare

:: 指定盘符 + 物理盘号（读 MBR 与容量）
build.cmd prepare --deploy H: --disk 4

:: 只有 MBR dump 和容量
build.cmd prepare --deploy H: --mbr mbr512.bin --sectors 62333952

:: 全手填（按 SdLayout 的规则自己算分区）
build.cmd prepare --deploy H: --sectors 62333952 --sig 0xA1B2C3D4 --emu-gib 12
```

**读物理盘会自动申请管理员权限。** `prepare.py` 先用 `IsUserAnAdmin()` 判断，
不是管理员就 `ShellExecuteW(..., "runas", ...)` 弹 UAC、并把已问到的参数原样带给
新开的管理员窗口（`--elevated` 标记）。原窗口会提示
`[ELEVATED] continued in a new administrator window` 然后退出。

- 点了"否"：原窗口报 `没有拿到管理员权限（ShellExecute 返回 5）`，退出码 1；
- 已经是管理员（右键 build.cmd → 以管理员身份运行）：直接读，不弹窗；
- 不想提权也能用：`--mbr` + `--sectors` 或手填参数都**不需要**管理员权限。

**盘符不用猜**（`Path("H:")` 在 Python 里是"盘符相对路径"，会拼成 `H:payload.bin`
而不是 `H:\payload.bin`，所以脚本现在会先补成 `H:\`；`H`、`h:`、全角 `H：` 都认）：

```bat
build.cmd prepare --deploy auto --disk 4     :: 自动在磁盘 4 上找含 payload.bin 的卷
build.cmd prepare --deploy H: --disk 4
```

`--deploy auto` 会枚举该物理盘的所有卷（`IOCTL_STORAGE_GET_DEVICE_NUMBER` 匹配盘号，
这一步不需要管理员），挑根目录里有 `payload.bin` 或 `atmosphere` 的那个。

根目录里找不到 `payload.bin` 时，脚本会把该根目录的内容、以及该磁盘所有卷的列表
打出来，并标出哪个卷里有 `payload.bin` —— 不用自己猜哪个盘符是主数据分区。

写进卡里的东西（与主程序 Deploy 的布局一致）：
```
H:\payload.bin                       定制 hekate（= out\hekate.bin）
H:\payload.bin.backup                卡上【原来】那个 payload.bin 改名而来
H:\ready.flag                        128 字节任务清单（在根目录，不是 ns-toolbox）
H:\bootloader\ns-toolbox\task.bin    与 ready.flag 逐字节相同
H:\bootloader\ns-toolbox\payload.bin + nyx.bin + libsys_minerva.bso
                        + libsys_lp0.bso + res.pak + thk.bin
```

**原 payload 从卡上现有的 `payload.bin` 自动取**，不用另外找文件；生成完它就成了
`payload.bin.backup`。如果卡上原本没有 `payload.bin`，可以用 `--payload <文件>` 指定。

只想生成文件、不写卡时（例如先检查参数）：

```bat
build.cmd prepare --deploy H: --out out\prepare   :: 两边都留一份
build.cmd prepare --sectors 62333952 --out out\prepare
```

`--out` 只写目录、不碰卡；`--deploy` 只写卡、不落 `out\`。

写卡前后各有一道校验：

1. 写之前 `prepare.py` 复刻 `ns_manifest_valid()` + `ns_layout_valid()`，布局不符直接拒绝；
2. 写之后逐文件**读回比对**（ready.flag / task.bin / payload.bin / 5 个组件 / backup），
   任一不一致就报错，不会留下"看着写完了其实坏了"的卡。

1. `prepare.py` 内部复刻 `ns_manifest_valid()` + `ns_layout_valid()`；
2. 再调 `tools\nstask\bin\nstask.exe dump` 用 C 侧同一套判据复核（打印 `CRC32 通过`、
   `与 MBR 一致性：OK`、退出码 0）。

想自己复核，用 Switch 源码里那份头文件直接编一个检查器最硬（不经过任何我写的 Python）：

```bash
gcc -I <repo>/hekate/nyx/nyx_gui/frontend -o check verify/check_layout.c
./check "H:\ready.flag" mbr512.bin 62333952
# ns_manifest_valid = 1 / ns_layout_valid = 1（再改一个签名字节应变 0）
```

`mbr512.bin` 是这张卡的 MBR 扇区（512 字节）。拿不到就先用
`build.cmd prepare --deploy H: --out out\prepare` 跑一次，`out\prepare\sector0.bin`
就是本次用的那份。

默认模式怎么判断"源码没变"：把 `firmware/build-info.json` 里记的 `sourceHash`
与当前源码重新算一遍的值比对。一致且四个产物都在 → 只收拢；否则完整构建。
`sourceHash` 由 `build.py` 在每次成功构建后写入，不依赖文件时间戳。

环境要求：MSYS2（含 `usr\bin\bash.exe`、`usr\bin\make.exe`）、
devkitPro 的 `devkitARM`（含 `base_rules`）、Python 3。

产物落在：

```
out\                                ★ 直接取用这里：4 个 ARM 组件 + auto-emu.zip + MANIFEST.txt
baseline\firmware\hekate\output\    编译原始位置（out\ 是它的副本）
baseline\assets\auto-emu.zip        整包（要放回 src\NsToolbox.App\ 的那个）
```

`out\MANIFEST.txt` 记录了生成时间、工具链版本、每个文件的字节数与 SHA-256，
以及"与发布件是否逐字节相同"的结论 —— 不用相信我，自己核这一行就行。

脚本**不写死任何绝对路径**。探测顺序：`tools\_env.cmd` → 环境变量（`MSYS2_ROOT` /
`DEVKITARM` / `PY`）→ `PATH` → 常见安装位置 → 交互输入。

### 2. 只想确认这套源码是完整的

```bash
git clone https://github.com/easyworld/hekate.git /tmp/up
cd /tmp/up && git checkout 9bf0f7d0eebc08acfb5b1845ba56aef82e430693
git apply --check -p1 /path/to/patches/autotask.patch
```

`--check` 返回 0 就说明 `/tmp/up` 打上补丁后与 `baseline/firmware/hekate` **内容等价**（只差换行）。

### 3. 想绕过 build.cmd 手工编

必须在 **MSYS2 的 bash** 里执行，细节和坑见 `verify-build.md` §2。

```bash
msys64/usr/bin/bash.exe -l <AutoEmu>/tools/rebuild.sh arm
```

### 3. 想诊断一张卡上的任务标记

```bash
cd tools/nstask
./build.cmd            # 或 make
./bin/nstask.exe selftest
./bin/nstask.exe dump "H:/ready.flag" --mbr "H:/sector0.bin" --sectors 62333952
```

`dump` 会打印磁盘签名、主/raw 分区起止、payload 哈希，并把 `ready.flag` 与那张卡的
MBR 逐字段比对 —— 就是 Switch 侧报「SD卡与准备任务不一致」时，到底哪一项不符。

---

## 三份源码必须同步

自动创建任务用的是同一个 128 字节协议，三处实现任何一处改动都必须同步另外两处：

| 位置 | 语言 | 作用 |
|---|---|---|
| `baseline/firmware/hekate/nyx/nyx_gui/frontend/ns_task.h` | C（Switch） | 定义结构体 + `ns_manifest_valid` / `ns_layout_valid` |
| `src/NsToolbox.Core/NsToolbox.Core/EmuTask.cs` | C#（PC 生产实现） | `Encode` / `Decode` / `ValidateLayout` |
| `tools/nstask/nstask.c` | C（PC 参考实现） | 与上面两者逐字节一致，带自检 |

**已验证**：同一组字段分别用 `nstask.exe encode` 与 `EmuTask.Encode()` 编码，
128 字节逐字节相同（判据见 `UPGRADE.md` §4）。

---

## 上游标识

| 项 | 值 |
|---|---|
| 仓库 | `https://github.com/easyworld/hekate` |
| 版本 | 简体中文 v6.5.5 / Nyx 1.9.5（2026-11-21 从 v6.5.4 同步） |
| 提交 | `9bf0f7d0eebc08acfb5b1845ba56aef82e430693` |
| 许可 | GPL-2.0（`baseline/firmware/hekate/LICENSE`） |
| 改动面 | 新增 2 文件 + 修改 11 文件，见 `patches/autotask.patch` |

升级流程、每处改动的语义、以及新版合并时的注意事项，全在 **`UPGRADE.md`**。

---

## 本目录做过的验证

| 项 | 方法 | 结果 |
|---|---|---|
| 源码完整性 | 与 `NsToolbox.AutoEmu.zip` 内 `source.zip` 清单逐项比对 | 455 文件，一致 |
| 改动面确定 | 归一化换行后与上游 `9bf0f7d0` 逐文件哈希比对 | **新增 2 / 修改 11 / 删除 0** |
| 补丁可应用 | `git apply --check -p1 autotask.patch`（干净上游） | 退出码 0 |
| 补丁等价 | 上游+补丁 vs `baseline/firmware/hekate` 全量比对 | **445/445 一致**（归一化换行） |
| 协议一致 | `nstask.exe encode` vs 生产实现 `EmuTask.Encode()` | **128/128 逐字节一致** |
| 工具自检 | `nstask.exe selftest` | 7 项全通过 |
| 重编译 | devkitARM 16.1.0 + MSYS2 make，`make -j8` | **成功，产物与发布逐字节相同** |
| 整包重建 | `firmware/build.py` 端到端 | 8/9 条目相同；`source.zip` 仅 zip 元数据差异 |
| 一键脚本 | `build.cmd full`（冷启动，空 baseline） | 4 分 54 秒，rc=0，`compare.py` 报 **PASS** |
| 一键脚本 | `build.cmd arm` / `verify` / `clean` / `reset` | 均按预期，`clean` 后目录回空 |
| 路径探测 | 清缓存后跑 `clean` | 提示输入 → 接受 → 缓存重建（全反斜杠规范化） |
| 实机 | 需要真机 | **未做** |

重编译的完整记录（环境、命令、踩过的三个坑、`ready.flag` 哈希语义）见 **`verify-build.md`**。
