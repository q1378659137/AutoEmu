# 升级指引：Switch 系统更新后怎么重做这个组件

这份文档解决一个具体问题：**任天堂发布新固件 → hekate 必须跟进 → 本项目的自动创建组件也要跟着换版本**。
不换的后果不是"界面难看"，而是自动创建静默失败、或建出来的 emuMMC 起不来。

---

## 1. 什么时候需要动

三个信号，任意一个出现就要评估：

| 信号 | 怎么确认 |
|---|---|
| 新固件发布，hekate 跟不上 | 新系统版本下注入 hekate 报 `Unknown pkg1 version` / 卡在 `Package1` 阶段 |
| 上游 easyworld/hekate 发了新版 | `https://github.com/easyworld/hekate/releases` 有新 tag |
| CTCaer 官方 hekate 发了新版 | 上游会先说"support FW x.y.z"，这是最可靠的信号 |

判断"新固件到底动了什么"，看上游这几个文件的提交：

```
bootloader/hos/pkg2.c            pkg1/pkg2 解包与版本识别
bootloader/hos/secmon_exo.c      Exosphère 补丁偏移
bootloader/hos/pkg2_patches.inl  各固件版本的内核补丁表
bdk/sec/se_t210.c                key derivation（新 key 世代）
```

**只改 UI 的版本不用跟。** 只有当上面这些文件有实质变化，才需要重编本组件。

---

## 2. 升级步骤

**优先用脚本**，它把下面 ①② 做了，并且是 dry-run 优先：

```bat
build.cmd sync                             :: 只报告，不动文件
build.cmd sync --ref v6.5.5 --apply        :: 确认后落盘
```

`sync --apply` 会自动备份、替换、重放补丁、自检、取配套资源、更新 UPSTREAM.md，
并在补丁冲突时**拒绝落盘**。详细说明与"两个上游源怎么选"见 **`SYNC.md`**。

下面是手工流程，脚本不适用时照做：

```
① 拉新版上游 ──► ② 打补丁 ──► ③ 合并冲突 ──► ④ 编译
                                      │
⑤ 换 res.pak/thk.bin ──► ⑥ 更新 sha256.json ──► ⑦ 重打 EXE ──► ⑧ 实机验收
```

### ① 拉新版

```bash
git clone https://github.com/easyworld/hekate.git up
cd up && git log --oneline -5
```

选 commit：优先选**与你机器固件对应**的那个 tag（如 `v7.0.0`）。不要用 master 的随机提交。

### ② 打补丁

```bash
# 先干跑
git apply --check -p1 /path/to/AutoEmu/patches/autotask.patch
# 无冲突就直接上
git apply -p1 /path/to/AutoEmu/patches/autotask.patch
```

### ③ 合并冲突（大概率会有）

`patch` 打不上时，用 `patches/overlay/` 里的 13 个文件人工对照。**不要整文件覆盖**——
新版在这些文件里可能加了别的东西，覆盖等于把它们丢了。

按 §3 的清单逐项确认每一处改动在新版里还成立。

### ④ 编译

**最省事：在 AutoEmu 根目录双击 `build.cmd`，菜单里选 `2`（强制重编 + 打包 + 比对）。**
它会自己找 MSYS2 / devkitARM / Python，找不到就问你要路径并缓存。

**手工升版（不用 `sync --apply`）必须先重钉上游指纹**，否则 `build.py` 第一步就失败：

```bash
python3 tests/upstream_test.py --update --commit <上游 commit>
python3 tests/upstream_test.py            # 应打印 PASS
```

`sync --apply` 会自动做这一步；手工 git apply 的路径不会。

还有一条隐含前提：**基线必须是 LF 行尾**。上游是 LF，Windows 上 `git checkout`
默认写 CRLF，那样 411 个文件的字节都与上游不同，指纹校验会把每个文件都判成"被篡改"。
用 `git -c core.autocrlf=false -c core.eol=lf checkout` 拉取，或跑
`sync.py` 自带的 `to_lf()`。

手工跑时，**必须在 MSYS2 的 bash 里执行**，从 Git Bash 调会失败（`arm-none-eabi-gcc`
拿不到 `TEMP`，报 `Cannot create temporary file in C:\WINDOWS\`）。Python 必须开 UTF-8 模式，
否则 `upstream_test.py` 按 GBK 读源码直接抛 `UnicodeDecodeError`。

```bash
msys64/usr/bin/bash.exe -lc '
  export DEVKITARM=/opt/devkitpro/devkitARM
  export DEVKITPRO=/opt/devkitpro
  export PATH=/mingw64/bin:/usr/bin:$PATH
  export PYTHONUTF8=1
  cd <repo>/firmware
  mkdir -p ../assets ../release      # build.py 不会自己建，缺了会报 No such file
  python3 build.py'
```

只编 ARM、不打 zip 时：

```bash
bash.exe -lc 'export DEVKITARM=/opt/devkitpro/devkitARM; cd <repo>/firmware/hekate && make -j8'
```

产出 `assets/auto-emu.zip`。先在主机侧跑测试：

```bash
python3 tests/upstream_test.py    # 对照上游提交的摘要
```

`tests/handoff_test.c` 需要在构建环境里编，验证状态机（不碰真实设备）。

> 实测参考（6.5.4 基线）：`make -j8` 首次干净构建约 **2 分 28 秒**，
> 产物与发布件**逐字节相同**，详见 `verify-build.md`。

### ⑤ 换资源

`res.pak` / `thk.bin` 必须换成本次上游对应的官方配套版本：

```bash
curl -LO https://github.com/CTCaer/hekate/releases/download/v<新版>/hekate_ctcaer_<新版>_Nyx_<Nyx版>.zip
```

解出来放进 `firmware/resources/`。**版本不配套会白屏或图标错乱**，这不是可选项。

### ⑥ 更新清单

`assets/auto-emu.zip` 里的 `sha256.json` 记录 6 个二进制的摘要，由 `build.py` 生成。
确认它和实际文件对得上：

```bash
python3 - <<'PY'
import zipfile, hashlib, json
z = zipfile.ZipFile("assets/auto-emu.zip")
idx = json.loads(z.read("sha256.json"))
for n, want in idx.items():
    got = hashlib.sha256(z.read(n)).hexdigest().upper()
    print(("OK  " if got == want.upper() else "FAIL") + n)
PY
```

### ⑦ 重打 EXE

`NsToolbox.AutoEmu.zip` 的结构是 `{payload.bin, nyx.bin, libsys_*.bso, res.pak, thk.bin,
sha256.json, source.zip, LICENSE.txt}`，注意：

- 顶层是这 8 个**平铺文件**，不是目录
- `source.zip` 必须与本次编译源码一致（GPL 义务），`build.py` 会生成
- 替换后主程序 `NsToolbox.App.csproj` 里 `<EmbeddedResource Include="NsToolbox.AutoEmu.zip"
  LogicalName="NsToolbox.AutoEmu.zip" />` 不用改，路径没变
- **改完必须重编主程序**，否则 dll 里还是旧的

### ⑧ 实机验收

主机测试不代替真机。至少覆盖：

- [ ] 全新卡：格式化 → 重建 → 开机自动创建 → 建完自动引导回原 payload
- [ ] 已建好的卡：换包不被"未完成任务"拦住
- [ ] 中途断电：再开机停在原版分区选择界面（可手动重试）
- [ ] 失败路径：故意占用卡 → 报错且保留 `payload.bin.backup`
- [ ] Erista / Mariko / OLED 各一台（至少两种）

---

## 3. 十三处改动逐条说明

一共 13 个文件：**新增 2 个 + 修改 11 个**，完整 diff 见 `patches/autotask.patch`。

### 3.1 路径重定向（6 处，最容易机械照搬）

把上游读 `bootloader/sys/*` 的地方指向 `bootloader/ns-toolbox/*`，让临时组件不覆盖用户的正式文件。

| 文件 | 行附近 | 原路径 → 新路径 |
|---|---|---|
| `bdk/mem/minerva.c` | 3 处 `ianos_static_module(...)` | `libsys_minerva.bso` |
| `bootloader/main.c` | `_nyx_load_run()` | `nyx.bin` |
| `bootloader/main.c` | 保存 LP0 参数处 | `libsys_lp0.bso` |
| `nyx/nyx_gui/config.c` | `f_open(...)` | `nyx.ini` |
| `nyx/nyx_gui/frontend/gui.c` | "Nyx still exists" 检查 | `nyx.bin` |
| `nyx/nyx_gui/hos/hos.c` | TSEC keygen | `thk.bin` |

**合并新版时注意**：上游若把 `bootloader/sys` 换成别的目录（历史上有过 `bootloader/payloads`
的重排），这 6 处要跟着新目录改，不能只把 `sys` 替换成 `ns-toolbox` 就完事。

### 3.2 跳过启动流程（`bootloader/main.c`）

```c
// 原版
_check_for_updated_bootloader();
_auto_launch();
// 本项目：注释掉（临时引导不该检查更新，也不该自动进 HOS）
```

**为什么**：这个 payload 只在"要建 emuMMC"的时候被塞进去用一次，如果它去检查
`bootloader/update.bin` 或按 `hekate_ipl.ini` 自动启动，用户开机就直接进系统了，
自动创建永远不会发生。

**合并注意**：新版可能把自动启动逻辑挪到别的函数（比如统一成 `h_cfg.autoboot` 判断）。
这时要找到**新的入口**去关，而不是照抄这两行的位置。

### 3.3 保留 0xF0 隐藏分区类型（`fe_emummc_tools.c`）

```c
// 原版：无条件改成 0xE0
mbr.partitions[part_idx].type = 0xE0;
// 本项目：PC 已设 0xF0 就不动，否则才改
if (mbr.partitions[part_idx].type != 0xF0)
    mbr.partitions[part_idx].type = 0xE0;
```

**为什么**：PC 端把 emuMMC 分区写成 `0xF0`（见 `SdLayout.HiddenEmuPartitionType`），
Windows 才会当作未知分区不弹"需要格式化"。改回 `0xE0` 会让资源管理器一直提示格式化。

**合并注意**：新版若把这段抽成 `emummc_set_partition_type()` 之类的函数，改函数体即可。
如果新版同时支持多种隐藏类型，判断条件要放宽成"属于隐藏集合就不动"。

### 3.4 让创建结果能回传（`fe_emummc_tools.c` / `.h`）

```c
- void dump_emummc_raw(...)
+ int  dump_emummc_raw(...)     // 返回 0 成功
```

**为什么**：`ns_task_complete()` 需要知道创建到底成没成。原版是 void，只能靠全局状态猜，
接不住"失败/取消"的区分。

**合并注意**：这是**签名变更**，新版所有调用点都要跟着改返回类型。如果新版已经改成
返回 `int` 或 `FRESULT`，这处可以撤销，把 `ns_task` 那边对接新返回值即可。

### 3.5 自动选第 1 分区（`gui_emummc_tools.c`）

新增 `create_emummc_raw_auto(int select_first)`，配一个静态 `auto_select_first`：

- `select_first = 1`：跳过分区选择，直接选第 1 个可用分区
- 进入创建前调 `ns_task_begin(part, sector, gui)`，完成后调 `ns_task_complete(gui, result)`
- 分区不可用时**保留原版弹窗**，不擅自换分区

**合并注意**：这段依赖上游 `create_emummc_raw` 的入口与分区遍历顺序。新版若重构了
创建流程（例如改成流式、或换了 BIS 处理方式），**要按新流程重写这段，不要照抄**。
判断依据：看新版 `gui_emummc_tools.c` 里 `create_emummc_raw` 附近是否还叫这个名字、
参数是否还是 `(gui, part_idx, sector_start, resized_count)`。

### 3.6 开机自动进入（`gui.c`）

```c
if (ns_task_pending()) {
    /* 直接打开原版 emuMMC 管理与创建窗口，跳过主菜单 */
}
```

**合并注意**：新版如果改了窗口构造顺序（`lv_tabview`、`_show_hide_save_button` 附近），
这处插入位置要重新找 —— 原则是"在主菜单控件建好之后、第一次刷新之前"。

### 3.7 内存链式引导（`nyx.c`）

```c
void ns_task_chainload(void *buffer, uint32_t size)
{
    sd_end();
    memcpy((void *)RCM_PAYLOAD_ADDR, buffer, size);
    _reloc_append(PATCHED_RELOC_ENTRY, EXT_PAYLOAD_ADDR, ALIGN(size, 0x10));
    hw_deinit(false);
    void (*entry)() = (void *)EXT_PAYLOAD_ADDR;
    (*entry)();
    while (true) bpmp_halt();
}
```

**为什么**：恢复原 payload 后要"立刻引导它"，而不是重启让用户再注入一次。
官方 hekate 有 payload 引导逻辑，但路径不同（走 SD 文件），这里要的是**从内存直接跳**。

**合并注意**：`_reloc_append` / `RCM_PAYLOAD_ADDR` / `EXT_PAYLOAD_ADDR` 是内部符号，
新版若改了内存布局，这三个常量和 `_reloc_append` 的签名要一起核对。这是最容易编不过的地方。

### 3.8 核心状态机（`ns_task.c` / `ns_task.h`，新增）

`ns_task.c` 182 行、`ns_task.h` 48 行，五个入口：

| 函数 | 时机 | 作用 |
|---|---|---|
| `ns_task_pending()` | 开机 | 有没有 `ready.flag` / `ready.flag.restore` |
| `ns_task_start()` | 开机 | 校验任务 + MBR + payload，决定"创建"或"恢复" |
| `ns_task_begin()` | 进创建前 | 记录中断检查点（state=1） |
| `ns_task_complete()` | 创建成功 | 校验 `emuMMC/RAW1/raw_based` 与 `emummc.ini`，写 state=2，恢复 |
| `finish_restore()` | 收尾 | 换回原 payload、删私有文件、链式引导 |

状态文件 `state.bin`（32 字节）：`NSSTATE1` + task id(16) + state(4) + CRC32(4)。
`state=1` 可重试，`state=2` 只允许恢复、禁止再次创建 —— 这是防止"续做时把已建好的系统再建一遍"的闸门。

**合并注意**：
- `ns_task.c` 里的 `message()` 用的是 lvgl 旧 API（`lv_mbox_create`、`lv_obj_set_style`）。
  Nyx 若升到更高 lvgl 版本，这几个调用会失效，要按新版 API 重写
- `create_emummc_raw_auto()` 的声明在 `gui_emummc_tools.h`，新版若改了头文件名要跟着改
- `asset_names[]` 列了 9 个要清理的文件（6 个组件 + `nyx.ini` / `payload.old` / `state.bin`），
  新增组件时要同步这张表，否则收尾会留垃圾

### 3.9 编译挂接（`nyx/Makefile`）

```make
OBJS = ... fe_emummc_tools fe_emmc_tools ns_task
```

**合并注意**：只有一个词，但漏了就是"链接时找不到 `ns_task_pending`"。

---

## 4. 协议三处必须同步

改 `ns_task.h` 的结构体或字段语义时，这三处**必须一起改**，否则 PC 写的标记 Switch 不认：

| 文件 | 作用 |
|---|---|
| `baseline/firmware/hekate/nyx/nyx_gui/frontend/ns_task.h` | Switch 侧结构 + 校验 |
| `src/NsToolbox.Core/NsToolbox.Core/EmuTask.cs` | PC 生产实现（真正的写入方） |
| `src/native/AutoEmu/tools/nstask/nstask.c` | PC 参考实现（诊断工具） |

### 校验一致性（改完必做）

```bash
# 1. 参考实现自检
cd src/native/AutoEmu/tools/nstask && ./bin/nstask.exe selftest

# 2. 生成一个固定参数的标记
./bin/nstask.exe encode --sectors 268435456 --sig 0xA1B2C3D4 \
    --main-count 240000000 --raw-count 25166720 --full 0 \
    --payload <任意 payload.bin> \
    --id 00112233445566778899aabbccddeeff --out /tmp/mine.bin

# 3. 用生产实现（EmuTask.Encode）编码同一组字段，逐字节比对
#    最小对拍程序（net10.0，引用 NsToolbox.Core.dll）：
#      uint U(int i) => BitConverter.ToUInt32(raw, i);
#      var t = new NsToolbox.Core.EmuTask(U(12), U(16), U(20), U(24), U(28), U(32),
#              (NsToolbox.Core.SdFullEmuSize)U(36), U(40), raw[44..76], raw[76..92]);
#      File.WriteAllBytes(args[1], t.Encode());
#    然后  fc /b  /tmp/mine.bin  /tmp/prod.bin
```

预期：`fc` 报「找不到差异」，即 **128/128 逐字节一致**（本仓库在 6.5.4 基线上实测通过）。

### 硬编码常量

`EmuTask.ValidateFields` 与 `ns_manifest_valid` 都写死了这些，改 `SdLayout` 时要一起改：

```
main_start   == 0x8000        （16 MiB 对齐）
main_count   >  0x400000      （主分区至少 2 GiB）
raw_start    == main_start + main_count
raw_count    >= 0x80F000      （emuMMC 至少约 4 GiB）
payload_size 0x120 .. 0x30000
full_size    <= 2
```

---

## 5. 故障对照

| 现象 | 真实原因 | 查哪里 |
|---|---|---|
| `自动创建标记无效, 请连接电脑工具恢复启动.` | `ready.flag` 的 magic/CRC/字段范围不过 | `nstask dump <file>` |
| `SD卡与准备任务不一致, 请连接电脑工具.` | MBR 签名、扇区数、分区项与任务不符 | `nstask dump --mbr --sectors` |
| `原启动文件或任务记录无效` | `payload.bin.backup` 的 SHA-256 对不上 | 比 `payload_hash` |
| `无法开始第1部分` | 分区序号或起始扇区不是 `raw_start + 0x8000` | 看 `ns_layout_valid` 与 `emmc_tool_gui` 的分区推导 |
| 开机直接进系统，没自动创建 | `main.c` 的 `_auto_launch()` 没跳过，或 `ready.flag` 没写成功 | 见 §3.2 |
| 建完卡在 Nyx 不引导 | `ns_task_chainload` 的地址/`_reloc_append` 不匹配新版布局 | 见 §3.7 |
| 资源管理器提示格式化 emuMMC 分区 | `0xF0` 被改回 `0xE0` | 见 §3.3 |

---

## 6. 当前基线

| 项 | 值 |
|---|---|
| 上游提交 | `9bf0f7d0eebc08acfb5b1845ba56aef82e430693` |
| hekate / Nyx | 6.5.4 / 1.9.4（easyworld 简体中文） |
| 改动面 | +2 文件（`ns_task.c/h`），~11 文件 |
| 源码规模 | 455 文件 |
| 本机是否重编过 | **是**（devkitARM 16.1.0 / MSYS2 make 4.4.1）：`payload.bin` 107,160 字节、sha256 `35ea3d14…`，与发布件**逐字节相同**；整包 8/9 条目一致，仅 `source.zip` 的 zip 元数据差 1 字节。记录见 `verify-build.md` |
| 实机验证 | **没有** |

构建可复现只说明「同一份源码能编出同一个二进制」，不说明逻辑正确。
改完之后仍要按 §2 ⑧ 上真机。
