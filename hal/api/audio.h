#ifndef LINNET_HAL_AUDIO_H
#define LINNET_HAL_AUDIO_H
#include <stdint.h>
#include <stdbool.h>
/* Covers bounded next-file chain verification while current audio continues.
 * 256KiB at stereo16-bit gives1.49s at44.1kHz; startup primes only8192frames. */
#define LINNET_AUDIO_RING_FRAMES 65536u
struct ln_audio_status {
    uint32_t rate, queued, free_frames, consumed, submitted, interrupts;
    uint32_t underruns, silence_frames, fault, playing, paused, initialized;
    uint32_t last_irq_us, max_irq_us;
    int32_t volume_db_tenths;
    /* FIFO empty at completion entry is a sample, not an underflow latch. */
    uint32_t fifo_empty_irqs, max_completion_interval_us, max_completion_late_us;
};
bool ln_audio_init(uint32_t rate);
uint32_t ln_audio_submit(const int16_t *pcm, uint32_t frames);
uint32_t ln_audio_capacity(void);
bool ln_audio_start(void);
void ln_audio_finish(void);
void ln_audio_pause(void);
bool ln_audio_stop(void);
/* Discard a stream after verified DMA idle, retaining codec power and volume.
 * A successful halt requires init before submitting the replacement stream. */
bool ln_audio_halt(void);
bool ln_audio_volume(int32_t db_tenths);
void ln_audio_irq(void);
void ln_audio_service(uint32_t now);
void ln_audio_snapshot(struct ln_audio_status *out);
#endif
