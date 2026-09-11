#ifndef LINNET_MUSIC_PLAYER_H
#define LINNET_MUSIC_PLAYER_H
#include <stdint.h>
#include <stdbool.h>
struct ln_dsp_config;
enum ln_player_phase {LN_PLAYER_IDLE,LN_PLAYER_OPEN,LN_PLAYER_HEADER,LN_PLAYER_PRIME,
    LN_PLAYER_PLAY,LN_PLAYER_PAUSE,LN_PLAYER_DRAIN,LN_PLAYER_STOPPING,LN_PLAYER_ERROR};
enum ln_player_next_phase {LN_PLAYER_NEXT_NONE=0,LN_PLAYER_NEXT_OPENING,LN_PLAYER_NEXT_READY,
    LN_PLAYER_NEXT_COMMITTED,LN_PLAYER_NEXT_FAILED,LN_PLAYER_NEXT_CANCELING};
struct ln_player_status {uint32_t phase,error,generation,rate,decoded,rendered,underruns;uint64_t frames;
    uint32_t next_phase,next_error,gapless_joins,missed_joins;};
struct ln_player_transition {uint32_t token;bool gapless,manual;uint64_t boundary;uint32_t underruns;};
bool ln_player_open(const char *path);
/* Zero expected_bytes skips library size validation. Position is in decoded
 * source samples and is applied before the first audible frame. */
bool ln_player_open_at(const char *path,uint64_t expected_bytes,uint64_t position);
/* Config is copied and validated before admission. NULL selects unity.
 * A supplied config requires its actual design rate; a decoded rate mismatch
 * fails before submitting PCM. The caller may release config after this call. */
bool ln_player_open_configured(const char *path,uint64_t expected_bytes,uint64_t position,
                               const struct ln_dsp_config *config,uint32_t config_rate);
bool ln_player_pause(bool pause);
/* Toggle the latest accepted intent, including pending pause/seek and priming. */
bool ln_player_toggle_pause(void);
bool ln_player_seek(uint64_t frame);
bool ln_player_prepare_next(const char *path,uint64_t expected_bytes,uint32_t token);
bool ln_player_prepare_next_configured(const char *path,uint64_t expected_bytes,uint32_t token,
                                      const struct ln_dsp_config *config,uint32_t config_rate);
/* Once PCM enters the ring cancellation returnsfalse; use stop/seek to flush.
 * Earlier cancellation drains storage ownership before freeing the decoder.
 * Consume a completed transition before cancel/seek; Stop remains an override. */
bool ln_player_cancel_next(void);
/* Intent only: a matching READY decoder is promoted by step after current I/O
 * drains and old HAL PCM is stopped. No source reopen or future queued PCM is
 * reused. Emits a manual, non-gapless transition and starts the new track even
 * from pause. Stop/cancel can supersede; other controls refuse while pending. */
bool ln_player_skip_prepared_next(uint32_t token);
bool ln_player_take_transition(struct ln_player_transition *);
uint64_t ln_player_position(void);
void ln_player_stop(void);
void ln_player_stop_for_restart(void);
void ln_player_step(void);
bool ln_player_busy(void);
uint32_t ln_player_deadline(uint32_t now);
void ln_player_snapshot(struct ln_player_status *out);
/* Background reads get three quarters of a second of PCM where ring size
 * permits; writes/artwork keep their separate near-full policy. */
uint32_t ln_player_background_frames(uint32_t rate);
/* Queue intent lets a short current track use its remaining audible runway
 * to finish preparing the next track before the irreversible finish marker. */
void ln_player_expect_next(bool expected);
bool ln_player_prefetch_urgent(void);
#if !defined(LINNET_PROFILE_RELEASE)
struct ln_player_timing {uint32_t decode_calls,decode_us,decode_max_us,dsp_calls,dsp_frames,dsp_us,dsp_max_us,runtime_calls,runtime_us,runtime_max_us,music_us,storage_us,link_us;};
void ln_player_timing_snapshot(struct ln_player_timing *out);
uint32_t ln_player_decoder_kind(void);
void ln_player_timing_runtime(uint32_t elapsed);
void ln_player_timing_stage(uint32_t stage,uint32_t elapsed);
#endif
#endif
