/* NS Toolbox one-shot handoff. GPL-2.0-only; see repository LICENSE. */
#ifndef NS_TASK_H
#define NS_TASK_H
#include <stdint.h>
#include <string.h>
#define NS_DIR "bootloader/ns-toolbox"
#define NS_READY "ready.flag"
#define NS_RESTORE "ready.flag.restore"
#define NS_BACKUP "payload.bin.backup"
typedef struct {
    uint8_t magic[8];
    uint32_t version, disk_sectors, signature, main_start, main_count, raw_start, raw_count, full_size, payload_size;
    uint8_t payload_hash[32], id[16], reserved[32];
    uint32_t crc;
} ns_task_t;
_Static_assert(sizeof(ns_task_t) == 128, "PC/Switch manifest layout");
static inline uint32_t ns_crc(const void *buffer, uint32_t length) {
    const uint8_t *p = buffer; uint32_t crc = ~0u;
    while (length--) { crc ^= *p++; for (int n = 0; n < 8; n++) crc = (crc >> 1) ^ ((crc & 1) ? 0xEDB88320u : 0); }
    return ~crc;
}
static inline uint32_t ns_u32(const void *ptr) { const uint8_t *b = ptr; return b[0] | (uint32_t)b[1]<<8 | (uint32_t)b[2]<<16 | (uint32_t)b[3]<<24; }
static inline int ns_manifest_valid(const ns_task_t *t) {
    uint8_t zeros[32] = {0};
    return !memcmp(t->magic,"NSTASK01",8) && t->version == 1 && t->disk_sectors && t->signature &&
        t->main_start == 0x8000 && t->main_count > 0x400000 &&
        (uint64_t)t->main_start + t->main_count == t->raw_start && t->raw_count >= 0x80F000 &&
        (uint64_t)t->raw_start + t->raw_count <= t->disk_sectors && t->full_size <= 2 &&
        t->payload_size >= 0x120 && t->payload_size <= 0x30000 &&
        !memcmp(t->reserved, zeros, 32) && ns_crc(t, 124) == t->crc;
}
static inline int ns_layout_valid(const ns_task_t *t, const uint8_t *m, uint32_t sectors) {
    uint8_t zeros[32] = {0};
    return ns_manifest_valid(t) && sectors == t->disk_sectors && ns_u32(m+440) == t->signature &&
        m[510] == 0x55 && m[511] == 0xAA && (m[450] == 0x0C || m[450] == 7) && m[466] == 0xF0 &&
        ns_u32(m+454) == t->main_start && ns_u32(m+458) == t->main_count &&
        ns_u32(m+470) == t->raw_start && ns_u32(m+474) == t->raw_count && !memcmp(m+478,zeros,32);
}
static inline int ns_range_valid(const ns_task_t *t, uint32_t start, uint32_t count) {
    return count && start >= t->raw_start && (uint64_t)start + count <= (uint64_t)t->raw_start + t->raw_count;
}
int ns_task_pending(void);
int ns_task_active(void);
int ns_task_begin(int part, uint32_t sector, void *gui);
void ns_task_complete(void *gui, int result);
void ns_task_start(void *unused);
void ns_task_chainload(void *buffer, uint32_t size);
#endif
