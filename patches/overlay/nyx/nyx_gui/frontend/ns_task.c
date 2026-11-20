/* Automatic Part 1 selection and one-shot startup handoff for easyworld/hekate.
 * Creation and its UI remain in the upstream Chinese implementation.
 * Copyright (c) 2026 NS Toolbox contributors. GPL-2.0-only. */
#include <bdk.h>
#include <stdlib.h>
#include <string.h>
#include <libs/fatfs/ff.h>
#include "gui.h"
#include "gui_emummc_tools.h"
#include "fe_emummc_tools.h"
#include "ns_task.h"

static ns_task_t task;
static emmc_tool_gui_t *current_gui;
static int active;
static const char *asset_names[] = { "payload.bin", "nyx.bin", "libsys_minerva.bso", "libsys_lp0.bso", "res.pak", "thk.bin", "nyx.ini", "payload.old", "state.bin" };

static int read_exact(const char *path, void *out, u32 size)
{
    FIL fp; UINT n = 0;
    if (f_open(&fp, path, FA_READ)) return 1;
    int result = f_size(&fp) != size || f_read(&fp, out, size, &n) || n != size;
    if (f_close(&fp)) result = 1;
    return result;
}
static int write_exact(const char *path, const void *data, u32 size)
{
    FIL fp; UINT n = 0;
    if (f_open(&fp, path, FA_WRITE | FA_CREATE_ALWAYS)) return 1;
    int result = f_write(&fp, data, size, &n) || n != size;
    if (f_sync(&fp)) result = 1;
    if (f_close(&fp)) result = 1;
    return result;
}
static int unlink_if_present(const char *path)
{
    FRESULT r = f_unlink(path); return r != FR_OK && r != FR_NO_FILE && r != FR_NO_PATH;
}
static int state_read()
{
    ns_task_t restore;
    int restoring = !f_stat(NS_RESTORE, NULL);
    if (restoring) {
        if (!read_exact(NS_RESTORE, &restore, sizeof(restore)) && !memcmp(&restore,&task,sizeof(task)))
            return 2; // A restore/cleanup transaction must never repeat creation.
        // A torn first checkpoint write can still use the previously saved completed state.
    }
    if (f_stat(NS_DIR "/state.bin", NULL) == FR_NO_FILE) return restoring ? -1 : 0;
    u8 data[32];
    if (read_exact(NS_DIR "/state.bin", data, 32) || memcmp(data,"NSSTATE1",8) ||
        memcmp(data + 8, task.id, 16) || ns_u32(data + 28) != ns_crc(data,28)) return -1;
    u32 state = ns_u32(data+24); return state == 2 ? 2 : state == 1 && !restoring ? 1 : -1;
}
static int state_write(u32 value)
{
    u8 data[32] = {0}, check[32];
    memcpy(data,"NSSTATE1",8); memcpy(data+8,task.id,16);
    memcpy(data+24,&value,4); u32 crc=ns_crc(data,28); memcpy(data+28,&crc,4);
    return write_exact(NS_DIR "/state.bin",data,32) || read_exact(NS_DIR "/state.bin",check,32) || memcmp(data,check,32);
}
static void *load_original()
{
    const char *path = !f_stat(NS_BACKUP,NULL) ? NS_BACKUP : "payload.bin";
    u32 size = 0; void *buffer = sd_file_read(path, &size); u8 hash[32];
    if (!buffer) return NULL;
    if (size != task.payload_size || se_sha_hash_256_oneshot(hash,buffer,size) || memcmp(hash,task.payload_hash,32))
    { free(buffer); return NULL; }
    return buffer;
}


static void message(const char *text)
{
    if (current_gui) lv_label_set_text(current_gui->label_finish, text);
    else {
        lv_obj_t *bg = lv_obj_create(lv_scr_act(), NULL);
        lv_obj_set_style(bg, &mbox_darken);
        lv_obj_set_size(bg, LV_HOR_RES, LV_VER_RES);
        lv_obj_t *box = lv_mbox_create(bg, NULL);
        lv_obj_set_width(box, LV_HOR_RES / 9 * 6);
        lv_mbox_set_text(box, text);
        static const char *buttons[] = { "\222关闭", "" };
        lv_mbox_add_btns(box, buttons, nyx_mbox_action);
        lv_obj_align(box, NULL, LV_ALIGN_CENTER, 0, 0);
        lv_obj_set_top(box, true);
    }
    manual_system_maintenance(true);
}
static int finish_restore()
{
    void *original=load_original();
    if (!original) { message("原启动文件校验失败, 请连接电脑工具恢复启动."); return 1; }
    message("正在恢复原启动文件...");
    ns_task_t checkpoint;
    if (write_exact(NS_RESTORE,&task,sizeof(task)) || read_exact(NS_RESTORE,&checkpoint,sizeof(checkpoint)) ||
        memcmp(&checkpoint,&task,sizeof(task))) goto error;
    // Keep the original backup through copy, rename and read-back verification.
    if (write_exact("payload.bin.restore",original,task.payload_size)) goto error;
    u8 *check=malloc(task.payload_size);
    if (read_exact("payload.bin.restore",check,task.payload_size) || memcmp(check,original,task.payload_size)) { free(check); goto error; }
    free(check);
    if (unlink_if_present(NS_DIR "/payload.old")) goto error;
    if (!f_stat("payload.bin",NULL) && f_rename("payload.bin",NS_DIR "/payload.old")) goto error;
    if (f_rename("payload.bin.restore","payload.bin")) goto error;
    check=malloc(task.payload_size);
    int bad=read_exact("payload.bin",check,task.payload_size) || memcmp(check,original,task.payload_size); free(check);
    if (bad) goto error;
    // All code/resources are in RAM. Delete only the task's known private files.
    for (u32 i=0;i<ARRAY_SIZE(asset_names);i++) {
        char path[128]; s_printf(path,NS_DIR "/%s",asset_names[i]);
        if (unlink_if_present(path)) goto error;
    }
    // ready.flag also contains the manifest, allowing PC recovery during cleanup.
    if (unlink_if_present(NS_DIR "/task.bin") || unlink_if_present(NS_DIR) ||
        unlink_if_present(NS_BACKUP) || unlink_if_present("ready.flag.tmp") || unlink_if_present(NS_READY) || unlink_if_present(NS_RESTORE)) goto error;
    message("完成, 正在启动原引导...");
    ns_task_chainload(original,task.payload_size);
    return 0;
error:
    free(original);
    message("启动文件恢复未完成, 请连接电脑工具恢复启动."); return 1;
}

int ns_task_pending(void)
{
    if (sd_mount()) return 0;
    int pending = !f_stat(NS_READY, NULL) || !f_stat(NS_RESTORE, NULL);
    sd_unmount();
    return pending;
}

int ns_task_active(void) { return active; }

void ns_task_start(void *unused)
{
    current_gui = NULL;
    active = 0;
    if (sd_mount()) { message("无法读取SD卡, 请连接电脑工具."); return; }
    if ((read_exact(NS_READY, &task, sizeof(task)) || !ns_manifest_valid(&task)) &&
        (read_exact(NS_RESTORE, &task, sizeof(task)) || !ns_manifest_valid(&task)))
    { message("自动创建标记无效, 请连接电脑工具恢复启动."); return; }
    int state = state_read();
    if (state == 2) { finish_restore(); return; }
    ns_task_t recorded;
    mbr_t mbr;
    if (read_exact(NS_DIR "/task.bin", &recorded, sizeof(recorded)) || memcmp(&task, &recorded, sizeof(task)) ||
        sdmmc_storage_read(&sd_storage, 0, 1, &mbr) || !ns_layout_valid(&task, (u8 *)&mbr, sd_storage.sec_cnt))
    { message("SD卡与准备任务不一致, 请连接电脑工具."); return; }
    void *original = load_original();
    if (!original || state < 0) { free(original); message("原启动文件或任务记录无效, 请连接电脑工具恢复启动."); return; }
    free(original);
    active = 1;
    sd_unmount();
    // Interrupted tasks use the original partition selection dialog, avoiding an automatic rewrite on every boot.
    create_emummc_raw_auto(state == 0);
}

int ns_task_begin(int part, uint32_t sector, void *gui)
{
    current_gui = gui;
    int state = sd_mount() ? -1 : state_read();
    if (state == 2) { finish_restore(); current_gui = NULL; return 1; }
    if (state < 0 || part != 1 || sector != task.raw_start + 0x8000 || state_write(1))
    { message("无法开始第1部分, 请连接电脑工具检查此卡."); current_gui = NULL; return 1; }
    return 0;
}

void ns_task_complete(void *gui, int result)
{
    if (!active || result) { current_gui = NULL; return; } // Leave upstream error/cancellation messages and files in place.
    current_gui = gui;
    if (sd_mount()) { message("无法读取SD卡, 已保留原启动备份."); current_gui = NULL; return; }
    u32 sector = 0;
    emummc_cfg_t cfg;
    load_emummc_cfg(&cfg);
    int invalid = read_exact("emuMMC/RAW1/raw_based", &sector, 4) || sector != task.raw_start + 0x8000 ||
        cfg.enabled != 1 || cfg.sector != sector || !cfg.path || strcmp(cfg.path, "emuMMC/RAW1");
    free(cfg.path); free(cfg.nintendo_path);
    if (invalid || state_write(2)) { message("创建结果未保存完成, 已保留原启动备份. 请连接电脑工具."); current_gui = NULL; return; }
    finish_restore();
    current_gui = NULL;
}
