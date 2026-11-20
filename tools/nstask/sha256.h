/* 自包含 SHA-256，只为让 nstask.exe 不依赖 OpenSSL */
#ifndef NS_SHA256_H
#define NS_SHA256_H

#include <stdint.h>
#include <stddef.h>

typedef struct {
    uint32_t h[8];
    uint64_t len;
    uint8_t  buf[64];
    size_t   used;
} ns_sha256_ctx;

void ns_sha256_init(ns_sha256_ctx *c);
void ns_sha256_update(ns_sha256_ctx *c, const void *data, size_t len);
void ns_sha256_final(ns_sha256_ctx *c, uint8_t out[32]);
void ns_sha256(const void *data, size_t len, uint8_t out[32]);

#endif
