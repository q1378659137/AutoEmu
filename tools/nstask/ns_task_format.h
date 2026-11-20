/* NS Toolbox 自动创建任务协议 —— PC 侧参考实现
 *
 * 与 Switch 侧 `nyx/nyx_gui/frontend/ns_task.h` 逐字段一致；
 * 与托管层 `NsToolbox.Core/EmuTask.cs` 的 Encode/Decode 逐字节一致。
 * 三者任何一处改动都必须同步另外两处，否则 PC 写的标记 Switch 不认。
 *
 * 128 字节、小端、固定布局：
 *   0x00  magic[8]      "NSTASK01"
 *   0x08  version       必须为 1
 *   0x0C  disk_sectors  整卡 512 字节扇区数
 *   0x10  signature     MBR 偏移 440 处的磁盘签名（PC 端随机生成）
 *   0x14  main_start    主分区起始扇区，恒为 0x8000
 *   0x18  main_count    主分区扇区数，必须 > 0x400000
 *   0x1C  raw_start     emuMMC 分区起始扇区 = main_start + main_count
 *   0x20  raw_count     emuMMC 分区扇区数，必须 >= 0x80F000
 *   0x24  full_size     0=缩容(12GiB) 1=32GB 2=64GB
 *   0x28  payload_size  原 payload.bin 字节数，0x120..0x30000
 *   0x2C  payload_hash[32]  原 payload.bin 的 SHA-256
 *   0x4C  id[16]        任务随机 ID
 *   0x5C  reserved[32]  必须全零
 *   0x7C  crc           CRC-32(data[0..0x7B])
 */
#ifndef NS_TASK_FORMAT_H
#define NS_TASK_FORMAT_H

#include <stdint.h>
#include <stddef.h>

#define NS_TASK_SIZE        128
#define NS_TASK_MAGIC       "NSTASK01"
#define NS_TASK_VERSION     1u
#define NS_MAIN_START       0x8000u
#define NS_MAIN_MIN_COUNT   0x400000u
#define NS_RAW_MIN_COUNT    0x80F000u
#define NS_PAYLOAD_MIN      0x120u
#define NS_PAYLOAD_MAX      0x30000u

/* 保留文件 / 目录，与 Switch 侧 NS_DIR / NS_READY 等宏对应 */
#define NS_DIR              "bootloader/ns-toolbox"
#define NS_READY            "ready.flag"
#define NS_RESTORE          "ready.flag.restore"
#define NS_BACKUP           "payload.bin.backup"
#define NS_TASK_BIN         NS_DIR "/task.bin"
#define NS_STATE_BIN        NS_DIR "/state.bin"

/* state.bin：32 字节，NSSTATE1 + task id(16) + state(4) + CRC32(4) */
#define NS_STATE_MAGIC      "NSSTATE1"
#define NS_STATE_SIZE       32

typedef struct {
    uint32_t disk_sectors;
    uint32_t signature;
    uint32_t main_start;
    uint32_t main_count;
    uint32_t raw_start;
    uint32_t raw_count;
    uint32_t full_size;
    uint32_t payload_size;
    uint8_t  payload_hash[32];
    uint8_t  id[16];
} ns_task_fields;

uint32_t ns_crc32(const void *data, uint32_t length);

/* 把字段序列化成 128 字节（含 CRC）。返回 0 成功。 */
int  ns_task_encode(const ns_task_fields *f, uint8_t out[NS_TASK_SIZE]);

/* 解析并做 manifest 级校验（magic/version/范围/reserved/CRC）。返回 0 成功。 */
int  ns_task_decode(const uint8_t in[NS_TASK_SIZE], ns_task_fields *f);

/* 与 MBR + 整卡扇区数做一致性校验（对应 Switch 侧 ns_layout_valid）。
 * mbr 必须是 sector 0 的 512 字节。返回 0 成功，否则返回负的错误码。 */
int  ns_task_check_layout(const ns_task_fields *f, const uint8_t mbr[512], uint32_t disk_sectors);

/* 分区范围是否落在 emuMMC 分区内（对应 ns_range_valid）。 */
int  ns_task_check_range(const ns_task_fields *f, uint32_t start, uint32_t count);

const char *ns_task_error(int code);

#endif /* NS_TASK_FORMAT_H */
