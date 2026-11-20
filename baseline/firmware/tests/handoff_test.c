// Exercise the production handoff with an in-memory SD filesystem. No device access.
#include <assert.h>
#include <setjmp.h>
#include "../hekate/nyx/nyx_gui/frontend/ns_task.c"
static struct { char path[128]; u8 data[2048]; unsigned size; } files[32];
static mbr_t disk_mbr;
sdmmc_storage_t sd_storage;
int mbox_darken;
static lv_obj_t object;
static emmc_tool_gui_t gui = { &object };
static int opened, auto_first, chained, cfg_valid;
static const char *fail_write_path;
static const char *fail_unlink_path;
static jmp_buf exit_payload;
static int find(const char *path) {
    for (int i=0;i<32;i++) if (!strcmp(path,files[i].path)) return i;
    return -1;
}
static void put(const char *path,const void *data,unsigned size) {
    int i=find(path);
    if(i<0) { for(i=0;i<32&&*files[i].path;i++) {} assert(i<32);strcpy(files[i].path,path); }
    assert(size<=sizeof(files[i].data));memcpy(files[i].data,data,size);files[i].size=size;
}
int sd_mount(void) { return 0; }
void sd_unmount(void) {}
int sdmmc_storage_read(sdmmc_storage_t *s,u32 sector,u32 count,void *out) {
    assert(s==&sd_storage&&sector==0&&count==1); // Handoff never reads console GPT or duplicates its capacity decisions.
    memcpy(out,&disk_mbr,512);return 0;
}
void *sd_file_read(const char *path,u32 *size) {
    int i=find(path);if(i<0)return NULL;*size=files[i].size;
    void *data=malloc(*size);memcpy(data,files[i].data,*size);return data;
}
int se_sha_hash_256_oneshot(void *out,const void *data,u32 size) {
    // Deterministic hash stub; hardware SHA implementation is unchanged upstream.
    u32 crc=ns_crc(data,size);for(int i=0;i<8;i++)memcpy((u8 *)out+4*i,&crc,4);return 0;
}
void manual_system_maintenance(int unused) {}
void create_emummc_raw_auto(int first) { opened++;auto_first=first; }
void load_emummc_cfg(emummc_cfg_t *cfg) {
    memset(cfg,0,sizeof(*cfg));cfg->enabled=cfg_valid;cfg->sector=task.raw_start+0x8000;
    cfg->path=malloc(12);strcpy(cfg->path,"emuMMC/RAW1");
}
void ns_task_chainload(void *data,uint32_t size) {
    assert(size==task.payload_size);assert(find(NS_READY)<0&&find(NS_BACKUP)<0&&find(NS_RESTORE)<0);
    int i=find("payload.bin");assert(i>=0&&!memcmp(files[i].data,data,size));free(data);chained++;longjmp(exit_payload,1);
}
lv_obj_t *lv_obj_create(lv_obj_t *p,void *s) { return &object; }
lv_obj_t *lv_scr_act(void) { return &object; }
lv_obj_t *lv_mbox_create(lv_obj_t *p,void *s) { return &object; }
void lv_obj_set_style(lv_obj_t *p,void *s) {}
void lv_obj_set_size(lv_obj_t *p,int w,int h) {}
void lv_obj_set_width(lv_obj_t *p,int w) {}
void lv_mbox_set_text(lv_obj_t *p,const char *s) {}
void lv_mbox_add_btns(lv_obj_t *p,const char **s,void *f) {}
void lv_obj_align(lv_obj_t *p,void *q,int a,int x,int y) {}
void lv_obj_set_top(lv_obj_t *p,int top) {}
void lv_label_set_text(lv_obj_t *p,const char *s) {}
FRESULT f_stat(const char *p,void *info) { return find(p)<0?FR_NO_FILE:FR_OK; }
FRESULT f_open(FIL *fp,const char *p,int mode) {
    int i=find(p);if(mode&FA_CREATE_ALWAYS){put(p,"",0);i=find(p);}
    if(i<0)return FR_NO_FILE;fp->index=i;return 0;
}
unsigned f_size(FIL *fp) { return files[fp->index].size; }
FRESULT f_read(FIL *fp,void *data,unsigned n,unsigned *read) {
    *read=n<files[fp->index].size?n:files[fp->index].size;memcpy(data,files[fp->index].data,*read);return 0;
}
FRESULT f_write(FIL *fp,const void *data,unsigned n,unsigned *written) {
    *written=0;if(fail_write_path&&!strcmp(fail_write_path,files[fp->index].path))return 1;
    assert(n<=sizeof(files[fp->index].data));memcpy(files[fp->index].data,data,n);files[fp->index].size=n;*written=n;return 0;
}
FRESULT f_sync(FIL *fp) { return 0; }
FRESULT f_close(FIL *fp) { return 0; }
FRESULT f_unlink(const char *p) {
    if(fail_unlink_path&&!strcmp(p,fail_unlink_path))return 1;
    int i=find(p);if(i<0)return FR_NO_FILE;*files[i].path=0;return 0;
}
FRESULT f_rename(const char *from,const char *to) {
    int i=find(from);if(i<0||find(to)>=0)return 1;strcpy(files[i].path,to);return 0;
}
static void setup(void) {
    memset(files,0,sizeof(files));memset(&task,0,sizeof(task));memset(&disk_mbr,0,sizeof(disk_mbr));
    active=opened=chained=cfg_valid=0;auto_first=-1;current_gui=NULL;fail_write_path=fail_unlink_path=NULL;
    memcpy(task.magic,"NSTASK01",8);task.version=1;task.disk_sectors=sd_storage.sec_cnt=0x8000000;
    task.signature=123;task.main_start=0x8000;task.raw_start=0x6000000;task.main_count=task.raw_start-task.main_start;
    task.raw_count=0x180f800;task.payload_size=1024;
    u8 payload[1024];memset(payload,0x73,sizeof(payload));se_sha_hash_256_oneshot(task.payload_hash,payload,sizeof(payload));
    task.crc=ns_crc(&task,124);assert(ns_manifest_valid(&task));
    put(NS_READY,&task,sizeof(task));put(NS_DIR "/task.bin",&task,sizeof(task));put(NS_BACKUP,payload,sizeof(payload));
    put("payload.bin","temporary",9);put(NS_DIR,"",0);put(NS_DIR "/nyx.ini","private",7);
    put("bootloader/update.bin","publisher",9);put("bootloader/sys/nyx.bin","publisher",9);
    u8 *m=disk_mbr.bytes;m[450]=0x0c;m[466]=0xf0;m[510]=0x55;m[511]=0xaa;
    memcpy(m+440,&task.signature,4);memcpy(m+454,&task.main_start,4);memcpy(m+458,&task.main_count,4);
    memcpy(m+470,&task.raw_start,4);memcpy(m+474,&task.raw_count,4);
}
static void ready_result(void) { u32 sector=task.raw_start+0x8000;put("emuMMC/RAW1/raw_based",&sector,4);cfg_valid=1; }
int main(void) {
    setup();assert(ns_task_pending());ns_task_start(NULL);assert(opened==1&&auto_first==1&&find(NS_DIR "/state.bin")<0);
    assert(ns_task_begin(1,task.raw_start+0x8000,&gui)==0&&state_read()==1);
    ns_task_complete(&gui,1);assert(!chained&&find(NS_BACKUP)>=0&&state_read()==1);
    opened=0;current_gui=NULL;ns_task_start(NULL);assert(opened==1&&auto_first==0); // Retry uses the original selection dialog.
    setup();ns_task_start(NULL);assert(ns_task_begin(2,task.raw_start+0x8000,&gui)!=0&&find(NS_DIR "/state.bin")<0);
    setup();fail_write_path=NS_DIR "/state.bin";ns_task_start(NULL);assert(ns_task_begin(1,task.raw_start+0x8000,&gui)!=0&&!chained);
    setup();ns_task_start(NULL);assert(!ns_task_begin(1,task.raw_start+0x8000,&gui));ns_task_complete(&gui,0);assert(!chained&&find(NS_BACKUP)>=0);
    setup();ns_task_start(NULL);assert(!ns_task_begin(1,task.raw_start+0x8000,&gui));ready_result();
    if(!setjmp(exit_payload))ns_task_complete(&gui,0);
    assert(chained==1&&find(NS_DIR "/nyx.ini")<0&&find(NS_DIR)<0&&find("bootloader/update.bin")>=0&&find("bootloader/sys/nyx.bin")>=0);
    const char *failures[]={NS_RESTORE,"payload.bin.restore"};
    for(unsigned n=0;n<ARRAY_SIZE(failures);n++) {
        setup();ns_task_start(NULL);assert(!ns_task_begin(1,task.raw_start+0x8000,&gui));ready_result();fail_write_path=failures[n];
        ns_task_complete(&gui,0);assert(!chained&&find(NS_BACKUP)>=0);
        fail_write_path=NULL;current_gui=NULL;opened=0;
        if(!setjmp(exit_payload))ns_task_start(NULL);
        assert(chained==1&&opened==0);
    }
    setup();ns_task_start(NULL);assert(!ns_task_begin(1,task.raw_start+0x8000,&gui));ready_result();fail_unlink_path=NS_DIR "/nyx.ini";
    ns_task_complete(&gui,0);assert(!chained&&find(NS_RESTORE)>=0&&find(NS_BACKUP)>=0);
    fail_unlink_path=NULL;current_gui=NULL;opened=0;
    if(!setjmp(exit_payload))ns_task_start(NULL);
    assert(chained==1&&opened==0);
    setup();files[find(NS_BACKUP)].data[0]^=1;ns_task_start(NULL);assert(!opened&&!chained&&find(NS_BACKUP)>=0);
    setup();disk_mbr.bytes[440]^=1;ns_task_start(NULL);assert(!opened&&!chained);
    puts("PASS production Chinese handoff: automatic Part 1, native retry, failure/cancel retention, original-payload recovery and interrupted cleanup; no GPT reads");
}
