# NS Toolbox 自动创建组件

当前基于 easyworld/hekate 简体中文 v6.5.5 / Nyx 1.9.5：
https://github.com/easyworld/hekate/tree/ff0693843bf17e9a17e047cdda0fdfcd8ea5446a
这是 2026-10-30 查询时 master 和 v6.5.5 标签对应的最新提交；构建固定该提交，不在每次打包时自动追踪变化。

`hekate/` 包含完整对应源码与修改。许可证 GPL-2.0，见 `hekate/LICENSE`。
中文界面、字体、原始分区检测与创建逻辑均取自该提交。
`resources/res.pak` 与 `resources/thk.bin` 使用同版本官方配套资源，和 easyworld 上游打包方式一致：
https://github.com/CTCaer/hekate/releases/download/v6.5.4/hekate_ctcaer_6.5.4_Nyx_1.9.4.zip

自动化边界：
- 根目录 `payload.bin` 是从上述源码构建、修改依赖路径后的临时 hekate 引导文件。
- Nyx、Minerva、LP0、res.pak、thk.bin 在 `bootloader/ns-toolbox/` 加载。临时 Nyx 配置也写入该目录。
- 临时引导直接加载私有 Nyx，跳过更新 `bootloader/update.bin` 和原整合包自动启动 HOS。
- 有有效 ready.flag 时，打开原版简体中文虚拟系统管理与创建窗口，使用原版检测结果自动选择第1部分。无可用第1部分时保留原版分区选择弹窗，不自行选择其他分区。
- 创建窗口布局、中文文字、分区容量判断、BOOT0/BOOT1/GPP 复制、BIS、USER 格式化和 GPT 处理沿用 easyworld 实现。已移除旧自定义创建屏幕、eMMC GPT 预检、额外容量判断、逐块读回封装及自定义 BIS 修改。
- 原创建函数仅返回已有成功/失败结果供接续收尾，并保留 PC 已设置的 F0 隐藏类型；不再将其改回 E0。
- 成功后确认原版输出配置，恢复原 payload、删除临时文件并直接载入原引导。失败或取消保留原版界面与备份；不自动恢复为成功。
- 已开始但中断的任务再次开机显示原版分区选择界面，需要用户手动选择第1部分重试。已经完成创建的任务只继续恢复和清理。

重编译：安装 devkitPro/devkitARM，设置 DEVKITARM，然后运行 `python3 firmware/build.py`。
主项目 `build.py` 和 `build.ps1` 每次构建均先校验源文件摘要与组件；源码改变时必须重编译组件。
构建会生成 `assets/auto-emu.zip`、`firmware/build-info.json` 和 release 目录中的对应源码 ZIP。
星落与忘忧版本共用这套组件；PC 工具版本为 2.3，文件版本为 2.3.0.0；Switch 组件功能保持已实测的实现。

校验：`tests/upstream_test.py` 对照固定提交的摘要，核对原创建界面、分区容量判断、创建代码、GPT 解析、BIS 及中文字体。
`tests/handoff_test.c` 以真实接续代码加内存文件系统验证自动选择、中断重试、失败/取消保留、原启动文件恢复及恢复中断。该测试不读写真实设备，不模拟创建算法来冒充实机成功。

任务协议保持兼容：ready.flag 与私有 task.bin 均为128字节、小端、NSTASK01/version1；
字段见 NsToolbox.Core/EmuTask.cs 和 nyx/.../ns_task.h。state.bin 为32字节、
NSSTATE1 + task ID(16) + state(4) + CRC32(4)。state=1 是中断检查点；
state=2 是已创建检查点，只允许恢复/清理，不能再次自动创建。
ready.flag.restore 保存恢复阶段的完整任务副本，避免收尾断电后再次创建。
完整组件源码也内嵌于EXE，可用 --export-auto-source "组件源码.zip" 导出，相对文件名保存在原EXE旁。

需实机覆盖：读卡器/hekate UMS、Erista/Mariko/OLED、缩容/完整容量、
创建/恢复各阶段断电、低电量、拔卡和 I/O 错误。交叉编译与主机测试不代替实机验证。
