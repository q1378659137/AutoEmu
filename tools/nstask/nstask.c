#include "ns_task_format.h"

#include <string.h>

static void put_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

static uint32_t get_u32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

uint32_t ns_crc32(const void *data, uint32_t length)
{
    const uint8_t *p = (const uint8_t *)data;
    uint32_t crc = 0xFFFFFFFFu;
    while (length--) {
        crc ^= *p++;
        for (int n = 0; n < 8; n++)
            crc = (crc >> 1) ^ ((crc & 1u) ? 0xEDB88320u : 0u);
    }
    return ~crc;
}

int ns_task_encode(const ns_task_fields *f, uint8_t out[NS_TASK_SIZE])
{
    if (!f || !out) return -100;

    memset(out, 0, NS_TASK_SIZE);
    memcpy(out, NS_TASK_MAGIC, 8);
    put_u32(out + 8,  NS_TASK_VERSION);
    put_u32(out + 12, f->disk_sectors);
    put_u32(out + 16, f->signature);
    put_u32(out + 20, f->main_start);
    put_u32(out + 24, f->main_count);
    put_u32(out + 28, f->raw_start);
    put_u32(out + 32, f->raw_count);
    put_u32(out + 36, f->full_size);
    put_u32(out + 40, f->payload_size);
    memcpy(out + 44, f->payload_hash, 32);
    memcpy(out + 76, f->id, 16);
    put_u32(out + 124, ns_crc32(out, 124));
    return 0;
}

int ns_task_decode(const uint8_t in[NS_TASK_SIZE], ns_task_fields *f)
{
    if (!in || !f) return -100;

    if (memcmp(in, NS_TASK_MAGIC, 8) != 0) return -1;
    if (get_u32(in + 8) != NS_TASK_VERSION) return -2;

    static const uint8_t zero32[32] = { 0 };
    if (memcmp(in + 92, zero32, 32) != 0) return -4;
    if (get_u32(in + 124) != ns_crc32(in, 124)) return -3;

    f->disk_sectors = get_u32(in + 12);
    f->signature    = get_u32(in + 16);
    f->main_start   = get_u32(in + 20);
    f->main_count   = get_u32(in + 24);
    f->raw_start    = get_u32(in + 28);
    f->raw_count    = get_u32(in + 32);
    f->full_size    = get_u32(in + 36);
    f->payload_size = get_u32(in + 40);
    memcpy(f->payload_hash, in + 44, 32);
    memcpy(f->id, in + 76, 16);

    if (f->disk_sectors == 0) return -5;
    if (f->signature == 0) return -6;
    if (f->main_start != NS_MAIN_START) return -7;
    if (f->main_count <= NS_MAIN_MIN_COUNT) return -8;
    if (f->raw_start != f->main_start + f->main_count) return -9;
    if (f->raw_count < NS_RAW_MIN_COUNT) return -10;
    if ((uint64_t)f->raw_start + f->raw_count > f->disk_sectors) return -11;
    if (f->full_size > 2) return -12;
    if (f->payload_size < NS_PAYLOAD_MIN || f->payload_size > NS_PAYLOAD_MAX) return -13;
    return 0;
}

int ns_task_check_layout(const ns_task_fields *f, const uint8_t mbr[512], uint32_t disk_sectors)
{
    if (!f || !mbr) return -100;

    if (disk_sectors != f->disk_sectors) return -27;
    if (mbr[510] != 0x55 || mbr[511] != 0xAA) return -21;
    if (get_u32(mbr + 440) != f->signature) return -20;

    /* 分区项 1（偏移 446）：主数据分区 */
    if (mbr[450] != 0x0C && mbr[450] != 0x07) return -22;
    if (get_u32(mbr + 454) != f->main_start) return -24;
    if (get_u32(mbr + 458) != f->main_count) return -24;

    /* 分区项 2（偏移 462）：emuMMC 隐藏分区 */
    if (mbr[466] != 0xF0) return -23;
    if (get_u32(mbr + 470) != f->raw_start) return -25;
    if (get_u32(mbr + 474) != f->raw_count) return -25;

    static const uint8_t zero32[32] = { 0 };
    if (memcmp(mbr + 478, zero32, 32) != 0) return -26;
    return 0;
}

int ns_task_check_range(const ns_task_fields *f, uint32_t start, uint32_t count)
{
    if (!f || count == 0) return -101;
    if (start < f->raw_start) return -102;
    if ((uint64_t)start + count > (uint64_t)f->raw_start + f->raw_count) return -102;
    return 0;
}

const char *ns_task_error(int code)
{
    switch (code) {
    case 0:   return "OK";
    case -1:  return "magic 不是 NSTASK01";
    case -2:  return "version 不是 1";
    case -3:  return "CRC32 不匹配";
    case -4:  return "reserved 区非零";
    case -5:  return "disk_sectors 为 0";
    case -6:  return "signature 为 0";
    case -7:  return "main_start 不是 0x8000";
    case -8:  return "main_count 不大于 0x400000（分区太小）";
    case -9:  return "raw_start 不等于 main_start + main_count";
    case -10: return "raw_count 小于 0x80F000";
    case -11: return "raw 分区超出磁盘末尾";
    case -12: return "full_size 不在 0..2";
    case -13: return "payload_size 不在 0x120..0x30000";
    case -20: return "MBR 磁盘签名与任务不符";
    case -21: return "MBR 缺少 0x55AA 标记";
    case -22: return "MBR 主分区类型不是 0x0C/0x07";
    case -23: return "MBR 第二分区类型不是 0xF0";
    case -24: return "MBR 主分区起止与任务不符";
    case -25: return "MBR emuMMC 分区起止与任务不符";
    case -26: return "MBR 第二分区 478 起 32 字节非零";
    case -27: return "整卡扇区数与任务不符";
    default:  return "未知错误";
    }
}
