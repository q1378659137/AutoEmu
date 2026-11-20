#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "../hekate/nyx/nyx_gui/frontend/ns_task.h"
static void put(uint8_t *p,uint32_t v) { memcpy(p,&v,4); }
int main(void) {
    ns_task_t t={0}; memcpy(t.magic,"NSTASK01",8); t.version=1;
    t.disk_sectors=0x8000000; t.signature=0x12345679; t.main_start=0x8000;
    t.raw_count=12u*0x200000+0xF800; t.raw_start=t.disk_sectors-t.raw_count-0x800;
    t.main_count=t.raw_start-t.main_start; t.payload_size=1024; t.crc=ns_crc(&t,124);
    uint8_t mbr[512]={0}; put(mbr+440,t.signature);mbr[510]=0x55;mbr[511]=0xAA;
    mbr[450]=0x0C;mbr[466]=0xF0;put(mbr+454,t.main_start);put(mbr+458,t.main_count);
    put(mbr+470,t.raw_start);put(mbr+474,t.raw_count);
    assert(ns_manifest_valid(&t));assert(ns_layout_valid(&t,mbr,t.disk_sectors));
    assert(ns_range_valid(&t,t.raw_start,t.raw_count));
    assert(!ns_range_valid(&t,t.raw_start-1,1));assert(!ns_range_valid(&t,t.raw_start,0));
    assert(!ns_range_valid(&t,t.raw_start+t.raw_count,1));assert(!ns_range_valid(&t,0xfffffff0,0x1000));
    for(int i=0;i<128;i++) { ns_task_t bad=t; ((uint8_t *)&bad)[i]^=1;assert(!ns_manifest_valid(&bad)); }
    int offsets[]={440,450,454,458,466,470,474,478,510};
    for(unsigned i=0;i<sizeof(offsets)/sizeof(int);i++) { mbr[offsets[i]]^=1;assert(!ns_layout_valid(&t,mbr,t.disk_sectors));mbr[offsets[i]]^=1; }
    assert(!ns_layout_valid(&t,mbr,t.disk_sectors-1));
    t.raw_start=0xfffffff0;t.raw_count=0x80F000;t.crc=ns_crc(&t,124);assert(!ns_manifest_valid(&t));
    assert(ns_crc("123456789",9)==0xCBF43926);
    puts("PASS Switch manifest CRC, layout, extra partitions, all-byte corruption and overflow guards");
}
