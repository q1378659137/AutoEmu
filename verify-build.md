# 复现构建记录

**目的**：证明 `baseline/` 里的源码 + 本机工具链能编出与 `NsToolbox.AutoEmu.zip` **完全一致**的
二进制。这是"将来系统升版能自己重做"的前提 —— 如果连当前版本都复现不了，改出来的东西就没法信。

**执行时间**：2026-11-20 22:39–22:42
**结论**：**ARM 产物 4/4 逐字节相同；整包 8/9 相同，唯一差异是 zip 的 `create_system` 标记。**

---

## 1. 环境

| 项 | 值 | 位置 |
|---|---|---|
| 交叉编译器 | **devkitARM 16.1.0**（gcc 16.1.0） | `D:\biancheng\Atmosphere\msys64\opt\devkitpro\devkitARM` |
| GNU Make | 4.4.1 | `D:\biancheng\Atmosphere\msys64\usr\bin\make.exe` |
| 主机编译器 | mingw-w64 gcc（编主机测试用） | `msys64\mingw64\bin\gcc.exe` |
| Python | 3.13.12 | managed venv |

---

## 2. 怎么跑

**必须在 MSYS2 的 bash 里**，不能从 Git Bash 或 cmd 直接调：

```bash
D:/biancheng/Atmosphere/msys64/usr/bin/bash.exe -lc '
  export DEVKITARM=/opt/devkitpro/devkitARM
  export DEVKITPRO=/opt/devkitpro
  export PATH=/mingw64/bin:/usr/bin:$PATH
  export PYTHONUTF8=1
  cd /f/daima/yijianhuanbao/src/native/AutoEmu/baseline/firmware
  mkdir -p ../assets ../release
  /c/Users/nianruoanzhi/.workbuddy/binaries/python/envs/default/Scripts/python.exe build.py'
```

三个坑，踩过：

| 现象 | 原因 | 处理 |
|---|---|---|
| `Cannot create temporary file in C:\WINDOWS\: Permission denied`（编 main.o 时） | 在 Git Bash 里 export 的 `TEMP` 传不到 msys 的 make 拉起的 `arm-none-eabi-gcc`，它退回 `GetTempPath()` = `C:\WINDOWS` | 改在 MSYS2 bash 里跑（`TEMP=/tmp` 天然可写） |
| `UnicodeDecodeError: 'gbk' codec can't decode byte 0x9f` | `upstream_test.py` 用 `read_text()` 无 encoding，Windows 中文 locale 默认 GBK | `export PYTHONUTF8=1` |
| `No such file or directory: .../baseline/assets/auto-emu.zip` | `build.py` 的 `PROJECT = ROOT.parent`，会写 `baseline/assets/`，而解出的源码里没有这个目录 | 先 `mkdir -p assets release` |

只编 ARM 部分、不打 zip 的话，直接：

```bash
bash.exe -lc 'export DEVKITARM=/opt/devkitpro/devkitARM; cd /f/.../firmware/hekate && make -j8'
```

`make` 用时约 **2 分 28 秒**（首次干净构建，-j8）。

---

## 3. 结果一：ARM 产物逐字节比对

```
产物                            大小      资源大小  逐字节  SHA-256
hekate.bin               107,160   107,160  相同      35ea3d14b81484a8799dc1a27673023e469720b7cdfe1c641d0a4e7baf4b0863
nyx.bin                1,410,321 1,410,321  相同      1a1ddc57964f323f15878eb414208c4fa40210f89ae0293fd464f9e5e9c81721
libsys_minerva.bso       147,380   147,380  相同      18e43c399914362afcf3666ef9c2524ba647c2fcd400edaffee9b082eb5467f4
libsys_lp0.bso            33,372    33,372  相同      8b0d547438083b63986687d487454a591e7b558cf3f9147cea015412c8eccaad
```

- 四个 SHA-256 与 zip 内 `sha256.json` 记录的值**完全一致**
- `hekate.bin` 内部签名有效：偏移 280 处 `ICTC`、末尾 `ICTC49`（这也是 `build.py` 的硬门槛）
- 压缩统计：`Uncompr 131,113 / Payload 107,154`，加 6 字节尾标 → 107,160

**说明**：这份构建是确定性的。同一份源码 + 同一套 devkitARM，两次独立构建（一次干净、
一次增量）产出的 `hekate.bin` 哈希相同。

---

## 4. 结果二：整包比对

| 条目 | 原件 | 重编 | 结论 |
|---|---|---|---|
| `payload.bin` | 107,160 | 107,160 | **相同** |
| `nyx.bin` | 1,410,321 | 1,410,321 | **相同** |
| `libsys_minerva.bso` | 147,380 | 147,380 | **相同** |
| `libsys_lp0.bso` | 33,372 | 33,372 | **相同** |
| `res.pak` | 405,504 | 405,504 | 相同（未重编，直接取自 `resources/`） |
| `thk.bin` | 7,936 | 7,936 | 相同（同上） |
| `LICENSE.txt` | 18,092 | 18,092 | 相同 |
| `sha256.json` | 496 | 496 | 相同（内容由上面几个算出） |
| `source.zip` | 2,123,657 | 2,123,657 | **大小相同，字节不同** |

整包体积：原件 2,819,877 → 重编 2,819,876，**差 1 字节**。

### source.zip 差在哪

不是源码变了。解到条目级逐条比对：

```
条目数 455 / 455，条目顺序相同，内容不同的条目：0
唯一差异：ZipInfo.create_system —— 原件 3（Unix），重编 0（MS-DOS/FAT）
```

也就是说，455 个源文件**逐字节相同**，只是 zip 头里记录的"打包平台"不同（原件在 Linux 上打，
重编在 Windows 上打）。这 1 个字节的差异只影响 zip 元数据，不影响 GPL 要求的源码完整性。

---

## 5. `ready.flag` 与 `payload.bin` 是什么关系

这是最容易搞混的地方：**`ready.flag` 里存的哈希不是指向那个定制 payload。**

一次完整的部署，卡上会有三个 payload 文件：

| 卡上的文件 | 内容 | SHA-256 |
|---|---|---|
| `payload.bin`（部署后） | **定制**临时 hekate（107,160） | `35ea3d14…` |
| `bootloader/ns-toolbox/payload.bin` | 同一份定制 hekate | `35ea3d14…` |
| `payload.bin.backup` | **原来的** payload.bin（用户的 hekate） | 取决于用户 |

而 `ready.flag` 里记的是：

```
payload_size = 原 payload 的字节数      ← 不是 107,160
payload_hash = SHA-256(原 payload)      ← 不是 35ea3d14…
```

以官方 hekate 6.5.4（110,144 字节）当作"用户的原 payload"举例：

```
定制 payload SHA-256 : 35ea3d14b81484a8799dc1a27673023e469720b7cdfe1c641d0a4e7baf4b0863
原 payload   SHA-256 : 95f6e933e32e028f3ae90f0b0857ff47800e834bdace38a0ab019d8ed35a8c24
ready.flag 记的      : 95f6e933…  + size 110,144
```

**所以：**

- 编译产物 vs 资源里的 `payload.bin` → **相同**（已证，见 §3）
- 编译产物 vs 卡上部署后的 `payload.bin` → **相同**（部署时拷的就是它）
- 编译产物 vs `ready.flag` 里的 `payload_hash` → **必然不同**
- `ready.flag` 的 `payload_size` vs 部署后 `payload.bin` 的大小 → **必然不同**

后两条是设计如此：创建完成后要把原 payload 换回去，所以清单里必须记"原件"的哈希，
用来确认 `payload.bin.backup` 没被改动。看到两者不一致就怀疑卡坏了，会误判。

---

## 6. 复跑

```bash
python src/native/AutoEmu/verify/compare.py \
    src/native/AutoEmu/baseline/firmware/hekate/output \
    --original-payload <你假设的卡上原 payload.bin>
```

退出码 0 = 四个 ARM 产物全部与资源逐字节相同。

---

## 7. 遗留

- `baseline/firmware/hekate/build/` 是中间 `.o`，已删；`output/` 保留作为证据
- `baseline/assets/auto-emu.zip`、`baseline/release/*.zip`、`firmware/build-info.json` 是
  本次构建产物，保留供比对；它们不参与 `source_hash` 计算（`build.py` 的 `sources()` 已排除）
- **没有在真实 Switch 上跑过**。构建可复现 ≠ 逻辑正确，仍按 `UPGRADE.md` §2 ⑧ 的清单实机验收

---

## 8. 一键脚本（`build.cmd`）

上面这些步骤全部封进了 `build.cmd`，入口在 AutoEmu 根目录。

### 实测

| 命令 | 结果 |
|---|---|
| `build.cmd full`（空 baseline 冷启动） | **4 分 54 秒，rc=0**，`compare.py` 报 PASS |
| `build.cmd arm` | 3 分 45 秒，四个产物哈希与发布件一致 |
| `build.cmd verify` | 走完 build.py 三个主机测试 + 打包 + 比对，rc=0 |
| `build.cmd clean` | `baseline/` 只剩 `firmware/`，`hekate/` 无 `output`、`build` |
| `build.cmd reset` | 删掉 `tools/_env.cmd`，下次运行重新探测 |
| 路径探测（清缓存后） | 提示输入 → 接受 → 缓存重建 |

### 又踩到一个坑：环境变量路径转换被关掉

第一次 `build.cmd full` 失败在 build.py 的这句：

```
自动创建组件源码已改变，请安装 devkitARM 后重编译 firmware/build.py。
```

真实原因是 `build.py` 用 `Path(os.environ["DEVKITARM"])/"base_rules"` 判断工具链，
而它跑在 **Windows 版 Python** 上，不认 MSYS2 的 `/opt/devkitpro/devkitARM`。

正常情况下 MSYS 运行时会把这个值自动转成 `D:/.../devkitARM`（实测 `bash -lc` 里
`DEVKITARM=/opt/...`，Python 读到的是 `D:/...`）。但外层若设了
`MSYS_NO_PATHCONV=1` 或 `MSYS2_ENV_CONV_EXCL`，转换会被整体关闭，
Python 就把 `/opt/...` 当成当前盘根下的相对路径，自然找不到。

**修法**：`rebuild.sh` 里自己用 `cygpath -m` 转一次，不依赖 MSYS 的自动转换：

```bash
[ -d "${DEVKITARM:-}" ] && DEVKITARM="$(cygpath -m "$DEVKITARM")" && export DEVKITARM
[ -d "${DEVKITPRO:-}" ] && DEVKITPRO="$(cygpath -m "$DEVKITPRO")" && export DEVKITPRO
```

改完重跑，冷启动一次通过（4 分 54 秒）。

### 为什么 `.cmd` 里全用英文

`cmd.exe` 按当前控制台代码页（中文系统是 936/GBK）逐行解析 `.bat` 文件。
UTF-8 保存的中文在里面会变成乱码字节，其中部分字节被当成命令分隔符，
导致后续行错位、乱码被当作命令执行（实测：`'devkitARM' 不是内部或外部命令`）。

所以 `build.cmd` 只写 ASCII，中文输出全部放在 `tools/rebuild.sh` 里，
由 `chcp 65001` 包裹那一段调用来保证显示正常，调用完再切回原代码页。

### 默认模式：产物已是最新就只收拢

`build.cmd` 不带参数时是 `auto`，判定逻辑在 `rebuild.sh` 里：

1. `firmware/build-info.json` 存在、`assets/auto-emu.zip` 存在、`output/hekate.bin` 存在；
2. 用 `build.py` 自己的 `source_hash()` 重算当前源码摘要，与 `build-info.json` 里的 `sourceHash` 比对。

一致 → 只把产物复制到 `out\` 并写 `MANIFEST.txt`（秒级）；
不一致或产物缺失 → 转 `full` 完整构建。

判据不依赖文件时间戳，改完源码保存就直接跑，不会误用旧产物。

实测（产物已最新）：

```
== 源码未变化，产物已是最新 —— 只做收拢 ==
```

把 `build-info.json` 的 `sourceHash` 改成全零模拟源码变化：

```
== 源码有变化（或产物不齐），转完整构建 ==
```

之后 `build.py` 会把 `sourceHash` 重写回正确值 `4a0205a1…`。

### 输出编码：中文必须统一在 65001 下

`rebuild.sh`（bash）输出 UTF-8，`compare.py` 是 Python，默认跟随控制台代码页。
两者混着打就会出现"一半正常一半乱码"。两处修正：

- `build.cmd` 在调用 bash **之前** `chcp 65001`，直到 `:done` 才恢复原代码页，
  中间不再切换，`compare.py` 也在这个窗口里跑；
- `compare.py` 开头把 `sys.stdout/stderr` 强制 `reconfigure(encoding="utf-8")`。

修完后日志里 `资源包` / `相同` / `产物` 等中文各出现预期次数，唯一含非法字节的行是
`pause` 的「请按任意键继续」，那是 cmd 恢复 936 后用自己的字符串资源打的 —— 属正常。

### 改成菜单入口（2026-11-21）

双击 `build.cmd` 不再直接跑默认模式，而是先打印菜单、读一个数字：

```
1 auto   2 full   3 arm   4 verify   5 collect
6 sync   7 sync --apply   8 clean   9 reset   h help   0 quit
```

实现上有两个约束：

- **`.cmd` 里仍然只能是 ASCII**（见上一节），所以中文菜单放在 `tools/menu.txt`，
  由 `chcp 65001` 之后 `type` 出来。字节不在 `.bat` 里，就不会被当成命令分隔符；
- 读入的选择要能容忍空格、空行、越界值：空行 = 1，非法值打一行提示再回菜单。

命令行的老用法（`build.cmd full` 等）保留，菜单项与它们是同一套 MODE。

### 坑：MSYS2 登录 shell 不继承环境变量

`build.cmd` 把 `DEVKITARM` / `PY` 设在环境里，再 `bash.exe -l tools\rebuild.sh`。
实测在脚本里这两个变量**是空的**：

```
$ export PY="C:\...\python.exe"
$ msys64/usr/bin/bash.exe -lc 'echo "[${PY:-none}]"'
[none]
```

后果不是编译失败（`rebuild.sh` 里有 `/opt/devkitpro/devkitARM` 兜底、`python3` 兜底），
而是**静默降级**：用的是哪套工具链取决于兜底命不命中。更糟的是 `compare_summary`
拿不到 `PY`，退回 `/mingw64/bin/python3`，在 chcp 65001 的管道里静默失败，
`MANIFEST.txt` 的结论行变成空行 —— 看着像"没比对"，实际是比对失败。

修法：`build.cmd` 解析完同时写两份缓存

| 文件 | 给谁读 |
|---|---|
| `tools\_env.cmd` | 本脚本（`call`） |
| `tools\_env.sh` | `rebuild.sh`（`source`），路径用正斜杠 |

`rebuild.sh` 开头 `source` 它；`reset` 两个一起删；两份都进了 `.gitignore`。
`compare_summary` 也改成逐个候选（`$PY` → `python3` → `python`）先跑
`-c "import sys"` 验证可用，并且不再把 stderr 丢掉 —— 实在没有 Python 就写
"未比对（找不到可用的 Python）"，而不是输出空行。

### 坑：`MANIFEST.txt` 里那句"与发布件逐字节相同"是写死的

第一次在隔离副本里升到 6.5.5 后，`hekate.bin` 已经是 107,236 字节、
`nyx.bin` 1,410,409 字节，`MANIFEST.txt` 结尾却仍然印着

```
hekate.bin / nyx.bin / libsys_*.bso 与发布件逐字节相同；
```

因为它当时是两行 `echo` 常量。已改为调用 `verify/summary.py` 实际比对后输出一行结论：

```
四个 ARM 产物与发布件逐字节相同（sha256 前 8 位 35ea3d14）
```

或

```
与发布件不同：hekate.bin 本地 107,236 / 发布件 107,160 字节  ← 改了源码或换了上游属正常
```

或（找不到发布件/Python 时）

```
未比对（找不到发布件 NsToolbox.AutoEmu.zip）
```

判定依据是内容，不是文件大小 —— 大小相同也可能内容不同，所以逐字节比。

### 坑：`build.py` 的上游指纹把新版本判成"被篡改"（菜单 2 因此失败）

升级到 6.5.5 后点菜单 `2` 会直接失败：

```
AssertionError: Upstream code changed: bdk/storage/emmc.c
Command ... tests/upstream_test.py returned non-zero exit status 1
[失败] build.py 失败（详见上面的输出）
```

原因：`build.py` 第一步跑 `tests/upstream_test.py`，它比对
`tests/easyworld-baseline.json` 里 8 项**钉死在 6.5.4** 的指纹。升级后上游改了文件，
指纹必然不匹配 —— 这不是"源码被改坏"，而是"钉的文件没跟着更新"。

菜单 `3`（只编 ARM，不走 build.py）不受影响，所以会出现"能编出二进制、但打不了整包"
的怪现象。

三处修改：

1. `tests/upstream_test.py` 重写：指纹计算抽成函数，加 `--update [--commit <sha>]`；
   失败时打印**哪几个文件变了** + 重钉命令。读文件全部显式 `encoding="utf-8"`。
2. `sync.py --apply` 收尾自动 `--update` 重钉 + 立刻再校验一次，不 PASS 就报错退出。
3. `rebuild.sh clean` 顺手删 `loader/payload_0*.h`（bin2c 产物）。

### 坑：Windows 上 `git checkout` 把 LF 写成 CRLF

第一次同步出来的树 411 个文件全是 CRLF。C 编译器不在乎，但：

- 整棵树字节与上游不同 → 差异统计、逐字节比对全部失真；
- 指纹校验把每个文件都判成"被篡改"（第一个报的就是 `emmc.c`）。

`sync.py` 现在所有 git 调用带 `-c core.autocrlf=false -c core.eol=lf`，`copytree`
后再 `to_lf()` 兜底，工作树每次重建不复用。判据：

```bash
grep -rlU $'\r' baseline/firmware/hekate --include=*.c | wc -l   # 期望 0
```

（`loader/payload_00.h`、`payload_01.h` 例外 —— 那是 bin2c 生成的构建产物。）

### ready.flag 能不能"编译出来"：不能，只能按卡生成

`payload.bin` 是编译产物（`out/hekate.bin` 改名，107,236 字节 / `a9aacc51…`，
与 `auto-emu.zip` 内的 `payload.bin` 逐字节相同）。

`ready.flag` 不是。它是 128 字节清单，字段绑死一张卡：

```
magic "NSTASK01" + version 1 + CRC32(前 124 字节)
disk_sectors     整卡扇区数
signature        MBR 偏移 440 的磁盘签名（写分区表时随机生成）
main_start/count 0x8000 / 主分区扇区数
raw_start/count  emuMMC 分区起止
payload_size/hash 卡上【原来】那个 payload.bin
```

Switch 侧 `ns_layout_valid()` 会拿它和卡上的 MBR 逐项比。所以正确顺序是
「先分区写 MBR，再为这张卡生成清单」。

`tools/prepare.py`（菜单 `p`）做这件事，实测一次（构造参数：62,333,952 扇区、
签名 0xA1B2C3D4、12 GiB 档、原 payload 用官方 hekate 6.5.4 的 110,144 字节）：

```
nstask dump（C 侧同一套判据）
  disk_sectors : 62333952 (29.72 GiB)
  signature    : 0xA1B2C3D4
  main         : start=32768 count=37060608
  raw (emuMMC) : start=37093376 count=25229312
  CRC32        : 通过
  与 MBR 一致性：OK
  退出码 0
```

再用**独立**校验器（`verify/check_layout.c`，直接 include Switch 源码里的
`ns_task.h`，不经过 Python 也不经过 nstask.exe）：

```
gcc -I <repo>/hekate/nyx/nyx_gui/frontend -o check.exe verify/check_layout.c
./check.exe out/prepare/ready.flag out/prepare/sector0.bin 62333952
ns_manifest_valid = 1
ns_layout_valid   = 1
negate(signature) = 0  (expect 0)
negate(sectors)   = 0  (expect 0)
```

两处独立实现都判通过，且反例（改一字节签名 / 扇区数减 1）都正确变 0 ——
说明校验是真敏感，不是"恒真"。

**没有在真卡上跑过**：本机当前未插卡，`--disk` 路径（需要管理员）未实测。
