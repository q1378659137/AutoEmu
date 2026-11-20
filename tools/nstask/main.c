/* nstask.exe —— 自动创建任务标记的诊断/生成工具
 *
 * 用途：
 *   dump     看懂一张卡上的 ready.flag 到底写了什么（磁盘签名、分区起止、payload 哈希）
 *   verify   判断 ready.flag 与这张卡的 MBR 是否配套（复现 Switch 侧的 ns_layout_valid）
 *   encode   生成一个 task（正常流程不需要，用于对照/测试）
 *   state    解析 Switch 侧写的 state.bin
 *   selftest 用内置向量验证协议实现没漂移（改完源码先跑这个）
 *
 * 输出为 UTF-8。
 */
#include "ns_task_format.h"
#include "sha256.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int read_file(const char *path, uint8_t **out, size_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return -1; }
    long n = ftell(f);
    if (n < 0) { fclose(f); return -1; }
    rewind(f);
    uint8_t *buf = (uint8_t *)malloc((size_t)n ? (size_t)n : 1);
    if (!buf) { fclose(f); return -1; }
    if (n && fread(buf, 1, (size_t)n, f) != (size_t)n) { free(buf); fclose(f); return -1; }
    fclose(f);
    *out = buf;
    *size = (size_t)n;
    return 0;
}

static int parse_hex(const char *s, uint8_t *out, size_t len)
{
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) s += 2;
    size_t n = strlen(s);
    if (n != len * 2) return -1;
    for (size_t i = 0; i < len; i++) {
        char a = s[i * 2], b = s[i * 2 + 1];
        int hi = (a >= '0' && a <= '9') ? a - '0' : (a >= 'a' && a <= 'f') ? a - 'a' + 10 : (a >= 'A' && a <= 'F') ? a - 'A' + 10 : -1;
        int lo = (b >= '0' && b <= '9') ? b - '0' : (b >= 'a' && b <= 'f') ? b - 'a' + 10 : (b >= 'A' && b <= 'F') ? b - 'A' + 10 : -1;
        if (hi < 0 || lo < 0) return -1;
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return 0;
}

static void hex(const uint8_t *p, size_t n, char *out, size_t outlen)
{
    static const char *D = "0123456789abcdef";
    size_t o = 0;
    for (size_t i = 0; i < n && o + 2 < outlen; i++) {
        out[o++] = D[p[i] >> 4];
        out[o++] = D[p[i] & 15];
    }
    out[o] = 0;
}

static void dump_fields(const ns_task_fields *f)
{
    char h[80];
    hex(f->payload_hash, 32, h, sizeof h);
    printf("  disk_sectors : %u (%.2f GiB)\n", f->disk_sectors, (double)f->disk_sectors * 512.0 / 1073741824.0);
    printf("  signature    : 0x%08X   <- MBR 偏移 440\n", f->signature);
    printf("  main         : start=%u (0x%X) count=%u\n", f->main_start, f->main_start, f->main_count);
    printf("  raw (emuMMC) : start=%u (0x%X) count=%u\n", f->raw_start, f->raw_start, f->raw_count);
    printf("  full_size    : %u (%s)\n", f->full_size,
           f->full_size == 0 ? "缩容 12GiB" : f->full_size == 1 ? "32GB 完整" : f->full_size == 2 ? "64GB 完整" : "非法");
    printf("  payload_size : %u\n", f->payload_size);
    printf("  payload_hash : %s\n", h);
    hex(f->id, 16, h, sizeof h);
    printf("  id           : %s\n", h);
}

static int cmd_dump(const char *path, const char *mbr_path, long sectors)
{
    uint8_t *buf = NULL;
    size_t n = 0;
    if (read_file(path, &buf, &n) != 0) { fprintf(stderr, "打不开 %s\n", path); return 1; }
    if (n != NS_TASK_SIZE) {
        fprintf(stderr, "长度是 %zu，应为 %d 字节 —— 这不像任务标记\n", n, NS_TASK_SIZE);
        free(buf);
        return 1;
    }
    ns_task_fields f;
    int rc = ns_task_decode(buf, &f);
    printf("%s\n", path);
    if (rc != 0) {
        printf("  解析失败：%s（%d）\n", ns_task_error(rc), rc);
        free(buf);
        return 1;
    }
    dump_fields(&f);
    printf("  CRC32        : 通过\n");

    if (mbr_path) {
        uint8_t *mbr = NULL;
        size_t mn = 0;
        if (read_file(mbr_path, &mbr, &mn) != 0 || mn != 512) {
            fprintf(stderr, "MBR 文件必须是 512 字节\n");
            free(mbr);
            free(buf);
            return 1;
        }
        uint32_t ds = (sectors > 0) ? (uint32_t)sectors : f.disk_sectors;
        int lrc = ns_task_check_layout(&f, mbr, ds);
        printf("  与 MBR 一致性：%s\n", ns_task_error(lrc));
        free(mbr);
        if (lrc != 0) { free(buf); return 1; }
    }
    free(buf);
    return 0;
}

static int cmd_state(const char *path)
{
    uint8_t *buf = NULL;
    size_t n = 0;
    if (read_file(path, &buf, &n) != 0) { fprintf(stderr, "打不开 %s\n", path); return 1; }
    if (n != NS_STATE_SIZE) { fprintf(stderr, "长度 %zu，应为 %d\n", n, NS_STATE_SIZE); free(buf); return 1; }
    if (memcmp(buf, NS_STATE_MAGIC, 8) != 0) { fprintf(stderr, "magic 不是 NSSTATE1\n"); free(buf); return 1; }
    uint32_t crc = (uint32_t)buf[28] | ((uint32_t)buf[29] << 8) | ((uint32_t)buf[30] << 16) | ((uint32_t)buf[31] << 24);
    uint32_t want = ns_crc32(buf, 28);
    uint32_t st = (uint32_t)buf[24] | ((uint32_t)buf[25] << 8) | ((uint32_t)buf[26] << 16) | ((uint32_t)buf[27] << 24);
    char h[40];
    hex(buf + 8, 16, h, sizeof h);
    printf("state.bin\n  id    : %s\n  state : %u (%s)\n  crc   : %s\n", h, st,
           st == 1 ? "已开始，可重试" : st == 2 ? "已创建，只允许恢复/清理" : "未知",
           crc == want ? "通过" : "不匹配");
    free(buf);
    return crc == want ? 0 : 1;
}

static int selftest(void)
{
    int fail = 0;

    uint8_t d[32];
    ns_sha256("abc", 3, d);
    char h[80];
    hex(d, 32, h, sizeof h);
    const char *want = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
    printf("sha256(\"abc\") %s\n", strcmp(h, want) == 0 ? "OK" : "FAIL");
    if (strcmp(h, want) != 0) { printf("  got %s\n", h); fail++; }

    ns_task_fields f;
    memset(&f, 0, sizeof f);
    f.disk_sectors = 62333952;
    f.signature = 0x1234ABCD;
    f.main_start = NS_MAIN_START;
    f.main_count = 37000000;
    f.raw_start = f.main_start + f.main_count;
    f.raw_count = 25168768 - 2048;
    f.full_size = 0;
    f.payload_size = 107160;
    ns_sha256("payload", 7, f.payload_hash);
    for (int i = 0; i < 16; i++) f.id[i] = (uint8_t)(i * 17 + 3);

    uint8_t enc[NS_TASK_SIZE];
    if (ns_task_encode(&f, enc) != 0) { printf("encode FAIL\n"); fail++; }
    ns_task_fields g;
    int rc = ns_task_decode(enc, &g);
    int same = rc == 0
        && g.disk_sectors == f.disk_sectors && g.signature == f.signature
        && g.main_start == f.main_start && g.main_count == f.main_count
        && g.raw_start == f.raw_start && g.raw_count == f.raw_count
        && g.full_size == f.full_size && g.payload_size == f.payload_size
        && memcmp(g.payload_hash, f.payload_hash, 32) == 0
        && memcmp(g.id, f.id, 16) == 0;
    printf("编解码往返 %s\n", same ? "OK" : "FAIL");
    if (!same) { printf("  %s\n", ns_task_error(rc)); fail++; }

    char crc_hex[16];
    uint32_t stored = (uint32_t)enc[124] | ((uint32_t)enc[125] << 8) | ((uint32_t)enc[126] << 16) | ((uint32_t)enc[127] << 24);
    snprintf(crc_hex, sizeof crc_hex, "%08X", stored);
    printf("CRC32 稳定 %s\n", stored == ns_crc32(enc, 124) ? "OK" : "FAIL");
    if (stored != ns_crc32(enc, 124)) fail++;
    printf("  (本向量 CRC = 0x%s，若算法被改动这里会变)\n", crc_hex);

    uint8_t mbr[512];
    memset(mbr, 0, sizeof mbr);
    mbr[440] = 0xCD; mbr[441] = 0xAB; mbr[442] = 0x34; mbr[443] = 0x12;
    mbr[450] = 0x0C; mbr[466] = 0xF0;
    /* 分区项的起止按小端显式写，不依赖主机字节序 */
    uint32_t le[4] = { f.main_start, f.main_count, f.raw_start, f.raw_count };
    const int at[4] = { 454, 458, 470, 474 };
    for (int k = 0; k < 4; k++)
        for (int b = 0; b < 4; b++)
            mbr[at[k] + b] = (uint8_t)(le[k] >> (b * 8));
    mbr[510] = 0x55; mbr[511] = 0xAA;

    rc = ns_task_check_layout(&f, mbr, f.disk_sectors);
    printf("layout 正例 %s\n", rc == 0 ? "OK" : "FAIL");
    if (rc != 0) { printf("  %s\n", ns_task_error(rc)); fail++; }

    mbr[441] ^= 0xFF;
    rc = ns_task_check_layout(&f, mbr, f.disk_sectors);
    printf("layout 反例（改签名）%s\n", rc == -20 ? "OK" : "FAIL");
    if (rc != -20) fail++;
    mbr[441] ^= 0xFF;

    rc = ns_task_check_layout(&f, mbr, f.disk_sectors - 1);
    printf("layout 反例（扇区数不符）%s\n", rc == -27 ? "OK" : "FAIL");
    if (rc != -27) fail++;

    printf("\n%s\n", fail ? "selftest 失败" : "selftest 全部通过");
    return fail ? 1 : 0;
}

static void usage(void)
{
    printf(
        "nstask —— 自动创建任务标记工具\n\n"
        "  nstask dump <ready.flag|task.bin> [--mbr <sector0.bin>] [--sectors N]\n"
        "  nstask state <state.bin>\n"
        "  nstask encode --sectors N --sig 0xXXXXXXXX --main-count N --raw-count N\n"
        "                [--full 0|1|2] [--payload <bin> | --payload-hash <64hex>]\n"
        "                [--id <32hex>] --out <file>\n"
        "  nstask selftest\n");
}

int main(int argc, char **argv)
{
    if (argc < 2) { usage(); return 3; }
    const char *cmd = argv[1];

    if (strcmp(cmd, "selftest") == 0) return selftest();

    if (strcmp(cmd, "dump") == 0) {
        if (argc < 3) { usage(); return 3; }
        const char *mbr = NULL;
        long sectors = 0;
        for (int i = 3; i < argc; i++) {
            if (strcmp(argv[i], "--mbr") == 0 && i + 1 < argc) mbr = argv[++i];
            else if (strcmp(argv[i], "--sectors") == 0 && i + 1 < argc) sectors = strtol(argv[++i], NULL, 10);
            else { fprintf(stderr, "未知参数 %s\n", argv[i]); return 3; }
        }
        return cmd_dump(argv[2], mbr, sectors);
    }

    if (strcmp(cmd, "state") == 0) {
        if (argc < 3) { usage(); return 3; }
        return cmd_state(argv[2]);
    }

    if (strcmp(cmd, "encode") == 0) {
        ns_task_fields f;
        memset(&f, 0, sizeof f);
        const char *payload = NULL, *phash = NULL, *idhex = NULL, *out = NULL;
        long long sectors = 0, main_count = 0, raw_count = 0, full = 0;
        unsigned long long sig = 0;
        int sig_set = 0;

        for (int i = 2; i < argc; i++) {
            const char *a = argv[i];
            const char *b = (i + 1 < argc) ? argv[i + 1] : NULL;
            if (!b) { fprintf(stderr, "%s 缺少取值\n", a); return 3; }
            if (strcmp(a, "--sectors") == 0) sectors = strtoll(b, NULL, 10);
            else if (strcmp(a, "--sig") == 0) { sig = strtoull(b, NULL, 0); sig_set = 1; }
            else if (strcmp(a, "--main-count") == 0) main_count = strtoll(b, NULL, 10);
            else if (strcmp(a, "--raw-count") == 0) raw_count = strtoll(b, NULL, 10);
            else if (strcmp(a, "--full") == 0) full = strtoll(b, NULL, 10);
            else if (strcmp(a, "--payload") == 0) payload = b;
            else if (strcmp(a, "--payload-hash") == 0) phash = b;
            else if (strcmp(a, "--id") == 0) idhex = b;
            else if (strcmp(a, "--out") == 0) out = b;
            else { fprintf(stderr, "未知参数 %s\n", a); return 3; }
            i++;
        }
        if (!out || sectors <= 0 || !sig_set || sig == 0 || main_count <= 0 || raw_count <= 0) { usage(); return 3; }

        f.disk_sectors = (uint32_t)sectors;
        f.signature = (uint32_t)sig;
        f.main_start = NS_MAIN_START;
        f.main_count = (uint32_t)main_count;
        f.raw_start = f.main_start + f.main_count;
        f.raw_count = (uint32_t)raw_count;
        f.full_size = (uint32_t)full;

        if (payload) {
            uint8_t *pb = NULL;
            size_t pn = 0;
            if (read_file(payload, &pb, &pn) != 0) { fprintf(stderr, "打不开 %s\n", payload); return 1; }
            f.payload_size = (uint32_t)pn;
            ns_sha256(pb, pn, f.payload_hash);
            free(pb);
        } else if (phash) {
            if (parse_hex(phash, f.payload_hash, 32) != 0) { fprintf(stderr, "哈希格式错\n"); return 3; }
            f.payload_size = NS_PAYLOAD_MAX;
        } else {
            fprintf(stderr, "需要 --payload 或 --payload-hash\n");
            return 3;
        }

        if (idhex) {
            if (parse_hex(idhex, f.id, 16) != 0) { fprintf(stderr, "id 格式错\n"); return 3; }
        } else {
            srand((unsigned)time(NULL));
            for (int i = 0; i < 16; i++) f.id[i] = (uint8_t)rand();
        }

        uint8_t enc[NS_TASK_SIZE];
        ns_task_encode(&f, enc);
        ns_task_fields chk;
        int rc = ns_task_decode(enc, &chk);
        if (rc != 0) { fprintf(stderr, "生成结果自检失败：%s\n", ns_task_error(rc)); return 1; }

        FILE *fp = fopen(out, "wb");
        if (!fp) { fprintf(stderr, "写不了 %s\n", out); return 1; }
        fwrite(enc, 1, NS_TASK_SIZE, fp);
        fclose(fp);
        printf("已写入 %s（%d 字节）\n", out, NS_TASK_SIZE);
        dump_fields(&f);
        return 0;
    }

    usage();
    return 3;
}
