/* 独立校验：直接用 Switch 侧那份 ns_task.h 的 inline 判据，
   不经过 Python、也不经过 nstask.exe，避免"自己验自己"。
   用法：check_layout <ready.flag> <sector0.bin> <sectors> */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ns_task.h"

static unsigned char *read_all(const char *path, long *len)
{
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(2); }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char *b = malloc(n ? n : 1);
    if (fread(b, 1, n, f) != (size_t)n) { fprintf(stderr, "short read\n"); exit(2); }
    fclose(f);
    if (len) *len = n;
    return b;
}

int main(int argc, char **argv)
{
    if (argc < 4) { fprintf(stderr, "usage: %s <flag> <mbr> <sectors>\n", argv[0]); return 3; }
    long flen = 0, mlen = 0;
    unsigned char *fb = read_all(argv[1], &flen);
    unsigned char *mb = read_all(argv[2], &mlen);
    unsigned long sectors = strtoul(argv[3], NULL, 10);

    if (flen != 128) { printf("flag size %ld != 128\n", flen); return 1; }
    if (mlen < 512) { printf("mbr size %ld < 512\n", mlen); return 1; }

    ns_task_t t;
    memcpy(&t, fb, sizeof t);

    int man = ns_manifest_valid(&t);
    int lay = ns_layout_valid(&t, mb, (uint32_t)sectors);
    printf("ns_manifest_valid = %d\n", man);
    printf("ns_layout_valid   = %d\n", lay);

    /* 反例：改签名字节，应该变成 0 */
    unsigned char mm[512];
    memcpy(mm, mb, 512);
    mm[441] ^= 0xFF;
    printf("negate(signature) = %d  (expect 0)\n", ns_layout_valid(&t, mm, (uint32_t)sectors));
    /* 反例：扇区数减 1，应该变成 0 */
    printf("negate(sectors)   = %d  (expect 0)\n", ns_layout_valid(&t, mb, (uint32_t)sectors - 1));

    return (man == 1 && lay == 1) ? 0 : 1;
}
