#ifndef LINNET_PP5020_DISPLAY_H
#define LINNET_PP5020_DISPLAY_H

#define LINNET_DISPLAY_MAILBOX 0x11ffd000
#define LINNET_DISPLAY_CAPABILITY 0x3244434c
#define LINNET_DISPLAY_MAGIC 0x31505344
#define LINNET_DISPLAY_QUEUE_CAPACITY 8
#define LINNET_DISPLAY_PIXELS 38720
#define LINNET_DISPLAY_BYTES 77440

/* Fixed uncached mailbox ABI shared with the resident COP assembly worker. */
#define LN_DISPLAY_MAGIC 0
#define LN_DISPLAY_GENERATION 4
#define LN_DISPLAY_HEAD 8
#define LN_DISPLAY_TAIL 12
#define LN_DISPLAY_ENABLED 16
#define LN_DISPLAY_PAUSE 20
#define LN_DISPLAY_PAUSED 24
#define LN_DISPLAY_STATE 28
#define LN_DISPLAY_BUFFER 32
#define LN_DISPLAY_STARTED 36
#define LN_DISPLAY_PAIRS 40
#define LN_DISPLAY_COMPLETED 44
#define LN_DISPLAY_FAILURES 48
#define LN_DISPLAY_ERROR 52
#define LN_DISPLAY_HIGH_WATER 60
#define LN_DISPLAY_COMMAND 64
#define LN_DISPLAY_X_CURSOR 68
#define LN_DISPLAY_Y_CURSOR 72
#define LN_DISPLAY_PAIRS_LEFT 76
#define LN_DISPLAY_ROWS_LEFT 80
#define LN_DISPLAY_BLOCK_ROWS 84
#define LN_DISPLAY_X 88
#define LN_DISPLAY_Y 92
#define LN_DISPLAY_WIDTH 96
#define LN_DISPLAY_HEIGHT 100
#define LN_DISPLAY_BUDGET 108
#define LN_DISPLAY_TICKS 112
#define LN_DISPLAY_RESETS 116
#define LN_DISPLAY_PROBE 120
#define LN_DISPLAY_PROBE_ACK 124
#define LN_DISPLAY_QUEUE 128

#ifndef __ASSEMBLER__
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Live presentation certificate fields; no cached state or COP control. */
struct ln_display_presentation {
    uint32_t frames_submitted, frames_completed, failures, resets, generation;
};
void ln_display_presentation_snapshot(struct ln_display_presentation *output);

struct ln_display_metrics {
    uint32_t frames_submitted, frames_completed, jobs_completed, pairs_written;
    uint32_t queue_high_water, failures, last_error, resets;
    uint32_t generation, queued_jobs, cop_capable, cop_active;
    uint32_t max_present_us, head, tail;
};

bool ln_display_init(void);
/* High byte: pause/fill/resume stage; lower bytes retain failure diagnostics. */
uint32_t ln_display_init_error(void);
uint16_t *ln_display_framebuffer(void); /* CPU-owned RGB565 draw buffer, 220x176. */
/* Optional idle-only full-frame transaction. NULL retains ordinary rendering.
 * On success, synchronously repaint all 220x176 pixels and call present before
 * any other executive work. Ordinary framebuffer access and snapshots return
 * NULL during the transaction. Row scanout imports this frame on next access;
 * column scanout transposes the cached draw buffer at publication. */
uint16_t *ln_display_direct_framebuffer(void);
bool ln_display_damage(int32_t x, int32_t y, int32_t width, int32_t height);
/* Snapshot and queue for the panel frame pulse; false when busy or no damage. */
bool ln_display_present(void);
void ln_display_column_mode(bool enabled);
/* CPU fallback performs at most max_pairs steps (clamped to 256); COP mode
 * handles sync timeout and observes completion. No polling wait inside service. */
bool ln_display_service(uint32_t max_pairs);
void ln_display_sync_irq(void);
#if !defined(LINNET_PROFILE_RELEASE)
void ln_display_sync_diagnostics(uint32_t output[16]);
void ln_display_blit_diagnostics(uint32_t output[16]);
uint32_t ln_display_column_mismatches(void);
#endif
bool ln_display_busy(void);
bool ln_display_cop_capable(void);
/* Upgrade the verified resident monitor's timer/progress race guard while it
 * is parked. One ARM condition field changes; no worker relocation or restart.
 * Accepts the already corrected monitor. Intended before enabling CPU cache. */
bool ln_display_upgrade_monitor(void);
bool ln_display_upgrade_blit(void);
/* Clock rendezvous diagnostics: error, capability, COP_CTL, enabled, state,
 * pause request, pause ACK, nonce ACK. Error codes: 1 capability absent,
 * 2 nonce timeout, 3 already parked by caller, 4 prepare-pause timeout,
 * 5 park timeout, 6 resume timeout, 7 cancellation timeout,
 * 8 unsupported monitor, 9 monitor patch verification failure. */
uint32_t ln_display_cop_error(void);
void ln_display_cop_diagnostics(uint32_t output[8]);
bool ln_display_reset(void); /* Quiesce, discard pending jobs, queue a full redraw. */
bool ln_display_quiesce(void);
void ln_display_get_metrics(struct ln_display_metrics *output);
/* Immutable until the next present or direct-frame transaction begins. */
const uint16_t *ln_display_snapshot(void);
uint32_t ln_display_snapshot_crc32(void);
size_t ln_display_capture(uint8_t *output, size_t capacity);
#endif
#endif
