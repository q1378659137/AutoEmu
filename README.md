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
