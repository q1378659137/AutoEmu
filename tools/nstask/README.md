# nstask —— 自动创建任务标记工具

纯 C（C11），零第三方依赖，自带 SHA-256。用来**看懂**和**核对** `ready.flag` / `task.bin` /
`state.bin`，不是在正常流程里"生成"标记。

## 编译

```bat
build.cmd
```

或：

```bash
gcc -O2 -Wall -Wextra -std=c11 -o bin/nstask.exe main.c nstask.c sha256.c
```

## 用法

```bat
nstask selftest
nstask dump "H:\ready.flag"
nstask dump "H:\ready.flag" --mbr "H:\sector0.bin" --sectors 62333952
nstask state "H:\bootloader\ns-toolbox\state.bin"
```

- `dump` 解析 128 字节清单并打印全部字段；给了 `--mbr` 和 `--sectors` 时，
  额外做与 Switch 侧 `ns_layout_valid()` 相同的逐字段比对
- `state` 解析 Switch 侧写的 32 字节状态（state=1 可重试 / state=2 只允许恢复）
- `selftest` 用内置向量验证 SHA-256、编解码往返、CRC32 稳定性、layout 正反例
- `encode` 仅用于对照测试，正常流程不需要

## 怎么取 MBR

不需要工具，用 PowerShell 直接读扇区 0：

```powershell
$fs = [System.IO.File]::OpenRead("\\.\PhysicalDriveN")   # N 换成 SD 卡编号
$buf = New-Object byte[] 512
[void]$fs.Read($buf, 0, 512)
[System.IO.File]::WriteAllBytes("F:\sector0.bin", $buf)
$fs.Close()
```

需要管理员权限。或者用 `nstask dump` 只打印字段，跟 DiskGenius / HxD 里看到的
偏移 440、450、454 对一遍也行。

## 输出

UTF-8。在 GBK 控制台里直接跑可能显示乱码，重定向到文件或用 Windows Terminal 查看即可。

## 与生产实现的关系

`nstask.c` 与 `NsToolbox.Core/EmuTask.cs` 是同一协议的两种实现。改动任一处，
必须同步 `baseline/firmware/hekate/nyx/nyx_gui/frontend/ns_task.h`，然后跑
`selftest` + `--nstask` 对拍（见 `../../UPGRADE.md` §4）。
