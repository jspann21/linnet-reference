#ifndef LINNET_STORAGE_SERVICE_H
#define LINNET_STORAGE_SERVICE_H
#include <stdbool.h>
#include <stdint.h>
#include "linnet_target.h"
#include "services/storage/fat32.h"
#define LN_STORAGE_MEDIA_MAX_READ (LINNET_STORAGE_MAX_READ_SECTORS * 512u)

/* One asynchronous read-only media operation shares the filesystem owner.
 * Admission returns1, busy0, invalid-1. Poll the same caller generation until
 * nonzero before releasing its buffer. Cancellation stops lookup, proof and
 * transfer work before another sector, drains the admitted block request, and
 * returns STALE without relabeling an error that FAT already observed. */
int ln_storage_media_open(const char *path,uint32_t generation);
/* Reads below512 bytes suppress speculative block read-ahead for this owner;
 * bulk requests retain streaming read-ahead. The media bound fits the largest
 * native video record and avoids restarting FAT positioning within a record. */
int ln_storage_media_read(const struct ln_fat32_file *file,uint32_t offset,
                          void *buffer,uint32_t length,uint32_t generation);
int ln_storage_media_poll(uint32_t generation,struct ln_fat32_file *file,
                          uint32_t *transferred);
/* Bounded callers that return to the executive may defer the recursive full
 * runtime callback. Owner, generation and cancellation semantics are unchanged;
 * block/ATA progress, recovery, USB and watchdog service still run. Synchronous
 * drain loops must retain ordinary polling to service the runtime while waiting. */
int ln_storage_media_poll_deferred(uint32_t generation,struct ln_fat32_file *file,
                                   uint32_t *transferred);
/* Existing video entry retains the same deferred-runtime behavior. */
int ln_storage_media_poll_video(uint32_t generation,struct ln_fat32_file *file,
                                uint32_t *transferred);
void ln_storage_media_cancel(uint32_t generation);
enum ln_storage_file { LN_STORAGE_OS0=0,LN_STORAGE_OS1=1,LN_STORAGE_BOOT0=2,
    LN_STORAGE_BOOT1=3,LN_STORAGE_STATE0=4,LN_STORAGE_STATE1=5,LN_STORAGE_SCRATCH=6,LN_STORAGE_WORK=7,
    LN_STORAGE_MUSIC0=8,LN_STORAGE_MUSIC1=9,LN_STORAGE_UPDATE0=10,LN_STORAGE_UPDATE1=11,
    LN_STORAGE_THEME0=12,LN_STORAGE_THEME1=13,LN_STORAGE_LIST0=14,LN_STORAGE_LIST1=15 };
void ln_storage_init(void);
void ln_storage_step(void);
/* Executive-only entry: full runtime must run after the bounded storage step. */
void ln_storage_step_deferred(void);
bool ln_storage_busy(void);
bool ln_storage_mounted(void);
uint32_t ln_storage_disk_sector_bytes(void);
bool ln_storage_startup_complete(void);
bool ln_storage_prepared(void);
/* 1 writable,0 pending directory proof renewal,-1 unavailable/unsafe.
 * Starts bounded asynchronous proof work only with no active storage owner. */
int ln_storage_prepare_writes(void);
uint32_t ln_storage_next_deadline(uint32_t now);
/* True only for a busy storage owner whose pending sector or initialization
 * is waiting on a future block/ATA transition; output is that transition's deadline. */
bool ln_storage_idle_wait(uint32_t now,uint32_t *deadline);
void ln_storage_state(uint32_t words[24]);
/* Fixed file IDs, never arbitrary raw disk addresses. One owner at a time. */
int ln_storage_read(uint32_t file,uint32_t offset,void *buffer,uint32_t length);
int ln_storage_write(uint32_t file,uint32_t offset,const void *buffer,uint32_t length);
uint32_t ln_storage_capacity(uint32_t file);
int ln_storage_flush(void);
/* Bounded asynchronous fixed-file operations use the same exclusive owner as
 * media reads. Admission:1 accepted (ticket set),0 busy,-1 invalid/unsafe.
 * Keep buffers unchanged/alive until poll returns nonzero for that ticket.
 * Writes include FAT's flush barrier; explicit flush remains available for
 * publication protocols. Poll drains accepted work even after caller policy
 * changes; neither a failed admission nor a stale poll releases another owner. */
int ln_storage_async_read(uint32_t file,uint32_t offset,void *buffer,uint32_t length,uint32_t *ticket);
int ln_storage_async_write(uint32_t file,uint32_t offset,const void *buffer,uint32_t length,uint32_t *ticket);
int ln_storage_async_flush(uint32_t *ticket);
int ln_storage_async_poll(uint32_t ticket,uint32_t *transferred);
/* Bounded executive poll; service runtime after returning to the caller. */
int ln_storage_async_poll_deferred(uint32_t ticket,uint32_t *transferred);
int ln_storage_quiesce(void);
int ln_storage_resume(void);
int ln_storage_recover(void);
int ln_storage_disk_mode(void);
int ln_storage_restart(void);
#if !defined(LINNET_PROFILE_RELEASE)
enum ln_storage_schedule {LN_STORAGE_SCHEDULE_IDLE=0,LN_STORAGE_SCHEDULE_FAT_RUNNABLE=1,
    LN_STORAGE_SCHEDULE_COMPLETION_RUNNABLE=2,LN_STORAGE_SCHEDULE_BLOCK_RUNNABLE=3,
    LN_STORAGE_SCHEDULE_BLOCK_WAIT=4};
/* Development-only read-only classification. BLOCK_WAIT is the only class
 * governed solely by the returned future block/ATA deadline. */
enum ln_storage_schedule ln_storage_schedule_state(uint32_t now,uint32_t *deadline);
/* Records one existing runtime-idle decision without changing that decision. */
void ln_storage_schedule_observe(uint32_t now);
/* Scheduler diagnostics: 24 words of sampled opportunity and latency data. */
void ln_storage_schedule_performance(uint32_t words[24]);
/* Poll timing: magic/reserved/init epoch/flags, then completed inclusive counters:
 * media poll calls/us/nested calls/us, progress calls/us/nested calls/us,
 * all storage-service FAT poll calls/us, progress runtime callback calls/us.
 * Media polls exclude stale owners. Nested is same-function reentry only.
 * Flags: bits0..11 counter saturation,28 active span,29 depth/reset anomaly,
 * 30 elapsed >=2^31 us,31 exhausted epoch. Reject flagged snapshots/deltas;
 * compare only same epoch, with SIOP ATA epoch and host time brackets.
 * Spans overlap; total minus nested is top-level inclusive, not CPU time. */
void ln_storage_media_performance(uint32_t words[16]);
int ln_storage_publication_fault(uint32_t stage);
int ln_storage_maintenance_begin(void);
void ln_storage_maintenance_end(bool success);
#endif
void ln_storage_progress(void *context);
#if defined(LINNET_IMAGE_BOOT) && LINNET_BOOT_SELECTOR_ROCKBOX
/* choice 1 boots Linnet; choice 2 validates and starts the configured Rockbox image. */
void ln_storage_boot_choice(uint32_t choice);
#endif
void ln_storage_boot(void);
void ln_storage_healthy(uint32_t readiness);
int ln_storage_update(uint32_t action,const uint8_t *data,uint32_t length,uint32_t offset);
void ln_storage_update_state(uint32_t words[16]);
/* Cached state only: safe for UI rendering, no storage access or publication. */
void ln_storage_update_snapshot(uint32_t words[16]);
/* Cached optional history: UINT32_MAX unavailable,0 none, reason1/2 in low
 * byte and failed slot0/1 in byte1. No storage I/O. */
uint32_t ln_storage_update_history(void);
int ln_storage_settings(bool write,uint8_t *data,uint32_t *length);
/* Optional theme sidecars: 1 success, 0 retry later, -1 unavailable or failed.
 * Reads and writes require normal storage admission and a prepared volume. */
int ln_storage_theme(bool write,uint8_t *data,uint32_t *length);
int ln_storage_file_resize(uint32_t action,uint32_t length);
#endif
