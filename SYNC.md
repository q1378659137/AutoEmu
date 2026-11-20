# 同步上游更新

这份文档回答两件事：**hekate 更新了怎么跟**、**Atmosphère 更新了要不要跟**。

先说结论：

| 上游 | 要不要跟 | 原因 |
|---|---|---|
| **hekate**（easyworld 或 CTCaer） | **必须跟** | 本组件就是它的定制构建，源码级绑定 |
| **Atmosphère** | **不用跟** | 本组件不引用它的任何源码，见 §5 |

---

## 1. 先判断"该不该升"

别看到新版本就升。判据是**你的机器固件版本**：

1. 打开 hekate 的 release 说明，找 `Latest HOS supported:`（例如 v6.5.5 写的是 `23.5.0`）；
2. 对照你 Switch 里的系统版本：
   - 固件 ≤ 该值 → 现在这版就够，不必升；
   - 固件 > 该值 → 必须升，否则 hekate 起不来（`Unknown pkg1 version`）。

另外看上游这几个文件的提交，它们才是固件适配的核心：

```
bootloader/hos/pkg1.c            pkg1 版本识别
bootloader/hos/pkg2_patches.inl  内核补丁表
bootloader/hos/secmon_exo.c      Exosphère 偏移
bdk/sec/se_t210.c                key derivation
```

只改 UI 的版本不用跟。

---

## 2. 两个上游源，选哪个

| 源 | 名称 | 特点 | 代价 |
|---|---|---|---|
| **easyworld/hekate**（默认） | `easyworld` | 简体中文界面，Nyx 中文翻译 + HarmonyOS 字体 | 版本可能比官方慢一点 |
| **CTCaer/hekate**（官方） | `ctcaer` | 上游权威，更新最快 | **会丢中文界面** —— 界面变英文 |

**在菜单里按 `s` 切换**，选完会记在 `tools\_upstream`（本机偏好，不进版本库），
菜单顶部会显示当前源。之后 `6` / `7` 都用这个源。

命令行等价写法：`build.cmd sync --repo ctcaer`（一次性的，不改偏好）。

实测差异（同为 v6.5.5）：从 `ctcaer` 同步会让这些文件消失或被覆盖 ——

```
- bdk/libs/lvgl/lv_fonts/harmony_os_sans_20.c   ← 中文字体
- bdk/libs/lvgl/lv_fonts/harmony_os_sans_30.c   ← 中文字体
- tools/find_chinese.py
- README_EN.md  .github/workflows/main.yml
内容不同：easyworld 16 个文件 / ctcaer 27 个文件
```

所以：**想要中文界面就用 easyworld，只要功能就用 ctcaer。** 这是选择，不是缺陷。

---

## 3. 怎么同步（菜单 / 命令两种）

**双击 `build.cmd`，菜单里选 `6`（只检查）或 `7`（检查并应用），源用 `s` 切换。**

```
    s   切换更新源        在 easyworld 与 CTCaer 之间选
    6   检查上游更新      只报告差异，不改任何文件
    7   同步上游并应用    替换 baseline（自动先备份）
```

选 `6` 会打印版本对比、补丁能否干净应用、逐文件差异，然后什么都不改；
看完觉得可以，重新运行选 `7` 才真正落盘。

要换源或指定版本就用命令行（等价于脚本参数）：

```bat
build.cmd sync                              :: 查 easyworld 最新版，只报告（= 菜单 6）
build.cmd sync --repo ctcaer                :: 查官方最新版
build.cmd sync --ref v6.5.5                 :: 指定 tag 或 commit
build.cmd sync --ref v6.5.5 --apply         :: 真正替换 baseline（= 菜单 7 的进阶用法）
```

**默认是 dry-run，不会动任何文件。** 网络需要代理时先设：

```bat
set HTTPS_PROXY=http://127.0.0.1:10808
```

（`sync.py` 由 cmd 直接调用，不经过 MSYS2 登录 shell，所以这个变量能正常传进去。）

### dry-run 会告诉你什么

```
当前基线：hekate 6.5.4 / Nyx 1.9.4
  最新：v6.5.5  ff0693843bf1
上游版本：hekate 6.5.5 / Nyx 1.9.5
  补丁检查：可以干净应用
与当前基线的差异：上游新增 0 / 上游删除 0 / 内容不同 16
  另有本项目独有文件 2 个（上游没有，属预期）：ns_task.c、ns_task.h
  M Versions.inc
  M bootloader/hos/pkg1.c          ← 固件适配
  ...
注意：以下文件既是我们的定制点，上游这一版也改过 ——
  ! bootloader/main.c
  ...
```

最后那段是关键：**上游也动了我们的定制点**。补丁能干净应用就没问题；不能就按 §4 处理。

### `--apply` 做什么

1. 备份 `baseline/firmware/hekate` → `baseline/.backup/hekate-<旧版本>-<时间>.zip`
2. 用上游树替换（保留 `output/` 以外的源码）
3. `git apply patches/autotask.patch`（13 文件改动）
4. **自检**：`ns_task.c/h` 在、`nyx/Makefile` 有 `ns_task`、`main.c` 有 `ns-toolbox` —— 任一不满足就报错并提示备份位置
5. 从 CTCaer 对应 release 取 `res.pak` / `thk.bin`（内容相同则跳过）
6. 更新 `firmware/UPSTREAM.md` 的版本与提交，删除 `build-info.json`（强制重编）
7. 打印下一步

**补丁有冲突时它拒绝落盘**，不会给你一个半成品。这时走 §4。

### 工作目录

上游树拉到 `AutoEmu/.sync/<repo>-<ref>/`，同一版本复用。这个目录可以随时整个删掉，
不影响任何东西。

---

## 4. 补丁打不上怎么办

```bash
# 1) 看冲突在哪
cd .sync/easyworld-v6.5.5
git apply -p1 --check /path/to/patches/autotask.patch   # 报错会指明文件与行

# 2) 按 UPGRADE.md §3 的 13 条逐项对照
#    新版可能改了函数名、挪了代码位置、换了目录
```

再用 `patches/overlay/` 里的"改完版"文件对照人工合并 —— **不要整文件覆盖**，
新版在这些文件里可能加了别的东西，覆盖等于把它们丢了。

合并完：

```bash
# 3) 重新生成补丁（可选，让下次能自动应用）
cd .sync/easyworld-v6.5.5 && git diff > /tmp/new.patch
```

如果改动语义变了（不只是位置挪动），同步更新 `UPGRADE.md` §3 的说明 —— 那份文档是给
下次升级的人看的。

---

## 5. Atmosphère 为什么不用跟

**本组件不引用 Atmosphère 的任何源码。** 证据：

```bash
grep -ri "atmosphere" baseline/firmware/hekate --include=*.c --include=*.h | wc -l
# 只出现在注释与整合包路径里，没有 #include、没有链接
```

三个看似"来自 Atmosphère"的组件，实际来源是：

| 组件 | 真实来源 | 怎么更新 |
|---|---|---|
| `libsys_minerva.bso` | hekate 的 `modules/hekate_libsys_minerva`，上游是 `CTCaer/minerva_tc`（README 里写着 `(c) 2018 CTCaer`） | 跟着 hekate 源码一起编 |
| `libsys_lp0.bso` | hekate 的 `modules/hekate_libsys_lp0` | 同上 |
| `res.pak` / `thk.bin` | **CTCaer hekate release** 的 `bootloader/sys/` 里，预制资源，不从源码编 | `sync --apply` 自动取 |

所以 **Atmosphère 发新版本时，这个组件不需要做任何事**。

真正需要跟 Atmosphère 的是**整合包里的 `atmosphere/` 目录**（AMS 本体、sysmodules、
`package3`、`fusee.bin`）—— 那是主程序「一键换包」的职责：它从
`download.nswiki.cn` 拉整合包，Atmosphère 更新后上游改整合包，用户重跑换包即可。

一个必须同时满足的条件：**新固件要 hekate 和 Atmosphère 同时支持**。
只升其中一个，要么起不来（hekate 不认 pkg1），要么进系统后黑屏/报错（AMS 不支持新固件）。
本组件只管 hekate 这一半。

---

## 6. 同步之后必须做的三件事

```bat
build.cmd              :: 1. 重编 + 收拢到 out\
build.cmd verify       :: 2. 与发布件比对 —— 换了版本这里必然"不同"，属正常
                       ::    但要看产物是否合理：大小在 100~130 KB、末尾是 ICTC49
```

3. **上真机**（`UPGRADE.md` §2 ⑧）：全新卡建 emuMMC、已建卡换包、断电续做、失败路径。
   构建通过 ≠ 逻辑正确，尤其是 pkg1/pkg2 patch 这类固件适配改动。

确认可用后再替换 `src/NsToolbox.App/NsToolbox.AutoEmu.zip` 并重编主程序。

---

## 7. 回滚

```bash
# 备份是 zip，直接解到 baseline/ 覆盖
cd baseline && unzip -o .backup/hekate-6.5.4-20261120-234500.zip
# 然后删掉 build-info.json，重新 build.cmd
```

`--apply` 失败时也会打印备份路径，照做即可。

---

## 8. 2026-11-20 实测记录

| 项 | 结果 |
|---|---|
| easyworld v6.5.5（`ff069384`）补丁 | **可以干净应用** |
| CTCaer v6.5.5（`9593272c`）补丁 | **可以干净应用** |
| easyworld 差异 | 上游新增 0 / 删除 0 / 内容不同 **16**（含 `pkg1.c`、`pkg2_patches.inl`） |
| ctcaer 差异 | 上游删除 5（中文字体等）/ 内容不同 **27** |
| `res.pak` / `thk.bin` | 两版之间**未变化**（`3570aa7a…` / `4c044348…`） |
| 是否已替换 baseline | 当时**没有**（后来 2026-11-21 已真正升级，见 §10） |

---

## 10. 2026-11-21 真实升级到 6.5.5（当前状态）

`baseline/` 现在是 **hekate 6.5.5 / Nyx 1.9.5 @ ff069384**，来自 easyworld。
备份留了两份：`hekate-6.5.4-20261121-004420.zip`（升级前）和
`hekate-6.5.5-20261121-005534.zip`（重同步前那一版）。

这次暴露了两个必须修的问题，都已经改在脚本里：

### 10.1 行尾：Windows 上 git 会把 LF 写成 CRLF

第一次 `--apply` 出来的树 **411 个文件全是 CRLF**，而上游是 LF。后果不是编译失败
（C 编译器不在乎），而是：

- 整棵树的字节都与上游不同 → 差异统计、逐字节比对全部失真；
- `build.py` 里的指纹校验把每个文件都判成"上游被改过"。

`sync.py` 现在所有 git 调用都带 `-c core.autocrlf=false -c core.eol=lf`，并在
`copytree` 之后再做一次 `to_lf()` 兜底（实测会修掉 2 个文件），工作树每次重建，
不复用旧树。

判据：`grep -rlU $'\r' baseline/firmware/hekate --include=*.c` 应该只有
`loader/payload_00.h` / `payload_01.h`（bin2c 生成的构建产物，不属上游源码）。

### 10.2 `build.py` 的上游指纹把新版本判成"被篡改"

`build.py` 第一步会跑 `tests/upstream_test.py`，它比对
`tests/easyworld-baseline.json` 里 8 项指纹。那个文件钉的是 **6.5.4** 的哈希，
升级后必然不匹配：

```
AssertionError: Upstream code changed: bdk/storage/emmc.c
Command ... tests/upstream_test.py returned non-zero exit status 1
[失败] build.py 失败
```

也就是说：**菜单 3（只编 ARM）能过，菜单 2（完整打包）会失败** —— 这正是
"更新了但编不出 6.5.5" 的直接原因。

三处修改：

1. `tests/upstream_test.py` 重写：指纹计算抽成函数，支持
   `--update [--commit <sha>]` 重钉；校验失败时打印**哪几个文件变了**并提示重钉命令
   （不再只丢一句 AssertionError）。所有读写显式 `encoding="utf-8"`，不再依赖 `PYTHONUTF8`。
2. `sync.py` 在 `--apply` 的最后自动调 `upstream_test.py --update --commit <sha>`，
   并立刻再跑一次校验确认 PASS，失败就报错退出（不会留一个"build 必失败"的基线）。
3. `rebuild.sh clean` 顺手删掉 `loader/payload_0*.h`。

### 10.3 升级后的实测产物（6.5.5）

`build.cmd 2`（完整构建）跑通，6 分 03 秒，0 错误：

| 文件 | 字节 | SHA-256 |
|---|---|---|
| `out\hekate.bin` | 107,236 | `a9aacc512e5128b96c2a647e6b6fb5d82101a215f85f1f3ae5823d444fc0640b` |
| `out\nyx.bin` | 1,410,409 | `616dbe052ed258e13989b8a898610a2ba6197f765c4c4c9b937f051dbf8d15f4` |
| `out\libsys_minerva.bso` | 147,380 | `18e43c399914362afcf3666ef9c2524ba647c2fcd400edaffee9b082eb5467f4` |
| `out\libsys_lp0.bso` | 33,372 | `8b0d547438083b63986687d487454a591e7b558cf3f9147cea015412c8eccaad` |
| `out\auto-emu.zip` | 2,821,461 | `cc0c8c5dd710103e141baa0ecaaeb19b74bc2d873fa3c935bedda3742c15e2e0` |

`payload.bin` 与 `nyx.bin` 变了（上游改 pkg1/pkg2 与 Nyx 1.9.5），两个 sysmodule
和 `res.pak`/`thk.bin` 没变 —— 与上游改动面一致。`sha256.json` 里是大写哈希，
与产物逐条相符。

**还没上真机。** 6.5.5 能不能起、能不能建 emuMMC，要按 §1 的判据确认固件版本后实机验证。

---

## 9. 2026-11-21 演练：在隔离副本里真的升到 6.5.5

为了证明 `--apply` 这条路真的能走通（而不只是 dry-run 好看），把整个 `AutoEmu/`
复制到 `_work/rehearsal/`，在副本里执行了一次完整升级 + 编译。**真实 `baseline/`
仍然是 6.5.4，没有动过。**

> 后来在真实 `baseline/` 上也做完了升级，见 §10。本节保留当时的隔离演练记录。

```
$ python tools/sync.py --ref v6.5.5 --apply
开始同步 ...
  备份当前基线：baseline\.backup\hekate-6.5.4-20261121-002456.zip（449 文件）
  已替换 baseline\firmware\hekate
  已应用 patches/autotask.patch
  自检通过：ns_task.c/h 就位，ns-toolbox 路径已改写
  res.pak  无变化（405,504 字节）
  thk.bin  无变化（7,936 字节）
  已更新 UPSTREAM.md
完成。
```

随后 `build.cmd arm` 编译成功（45 秒，增量）：

| 产物 | 6.5.4（当前基线） | 6.5.5（演练） | 变化 |
|---|---|---|---|
| `hekate.bin` | 107,160 `35ea3d14` | 107,236 `a9aacc51` | 变（pkg1/pkg2 固件适配） |
| `nyx.bin` | 1,410,321 `1a1ddc57` | 1,410,409 `616dbe05` | 变（Nyx 1.9.4→1.9.5） |
| `libsys_minerva.bso` | 147,380 | 147,380 | **不变** |
| `libsys_lp0.bso` | 33,372 | 33,372 | **不变** |
| `res.pak` / `thk.bin` | 405,504 / 7,936 | 同 | **不变** |

结论三条：

1. `--apply` 全流程可用，备份、补丁、自检、资源更新都正常；
2. 6.5.5 的定制源码**能编过**，产物大小合理（hekate 107 KB 量级、末尾 `ICTC49`）；
3. 只有 `hekate.bin` 与 `nyx.bin` 变，两个 sysmodule 和资源没动 —— 与上游改动面一致。

> 这次演练还抓到一个假结论：升级后 `MANIFEST.txt` 仍写"与发布件逐字节相同"，
> 因为那句话是**写死的**。现已改成调用 `verify/summary.py` 实际比对后输出，
> 找不到发布件就写"未比对"，不再假装相同。
