#ifndef NS_HOST_BDK_H
#define NS_HOST_BDK_H
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef unsigned int UINT;
typedef struct { u8 bytes[512]; } mbr_t;
typedef struct { u32 sec_cnt; } sdmmc_storage_t;
extern sdmmc_storage_t sd_storage;
int sd_mount(void);
void sd_unmount(void);
int sdmmc_storage_read(sdmmc_storage_t *, u32, u32, void *);
void *sd_file_read(const char *, u32 *);
int se_sha_hash_256_oneshot(void *, const void *, u32);
void manual_system_maintenance(int);
#define ARRAY_SIZE(a) (sizeof(a)/sizeof(*(a)))
#define s_printf sprintf
#define true 1
#define false 0
#define _GUI_H_
#define _GUI_EMUMMC_TOOLS_H_
#define _FE_EMUMMC_TOOLS_H_
typedef struct { int unused; } lv_obj_t;
typedef struct { lv_obj_t *label_finish; } emmc_tool_gui_t;
typedef struct { int enabled; u32 sector; char *path, *nintendo_path; } emummc_cfg_t;
void load_emummc_cfg(emummc_cfg_t *);
void create_emummc_raw_auto(int);
extern int mbox_darken;
#define LV_HOR_RES 1280
#define LV_VER_RES 720
#define LV_ALIGN_CENTER 0
#define nyx_mbox_action NULL
lv_obj_t *lv_obj_create(lv_obj_t *, void *);
lv_obj_t *lv_scr_act(void);
lv_obj_t *lv_mbox_create(lv_obj_t *, void *);
void lv_obj_set_style(lv_obj_t *, void *);
void lv_obj_set_size(lv_obj_t *, int, int);
void lv_obj_set_width(lv_obj_t *, int);
void lv_mbox_set_text(lv_obj_t *, const char *);
void lv_mbox_add_btns(lv_obj_t *, const char **, void *);
void lv_obj_align(lv_obj_t *, void *, int, int, int);
void lv_obj_set_top(lv_obj_t *, int);
void lv_label_set_text(lv_obj_t *, const char *);
#endif
