#ifndef NS_HOST_FF_H
#define NS_HOST_FF_H
typedef int FRESULT;
typedef struct { int index; } FIL;
#define FR_OK 0
#define FR_NO_FILE 4
#define FR_NO_PATH 5
#define FA_READ 1
#define FA_WRITE 2
#define FA_CREATE_ALWAYS 4
FRESULT f_open(FIL *, const char *, int);
unsigned f_size(FIL *);
FRESULT f_read(FIL *, void *, unsigned, unsigned *);
FRESULT f_write(FIL *, const void *, unsigned, unsigned *);
FRESULT f_sync(FIL *);
FRESULT f_close(FIL *);
FRESULT f_stat(const char *, void *);
FRESULT f_unlink(const char *);
FRESULT f_rename(const char *, const char *);
#endif
