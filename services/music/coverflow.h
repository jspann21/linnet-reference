#ifndef LINNET_COVERFLOW_H
#define LINNET_COVERFLOW_H
#include "ui/runtime/ui.h"
#if defined(LINNET_COVERFLOW)
void ln_coverflow_visible(bool visible);
void ln_coverflow_step(bool allow_read);
/* Request cancellation and return true only after all catalog-buffer I/O has
 * drained. The caller keeps the library DRAINING until the lease is released. */
bool ln_coverflow_release_catalog(void);
#if defined(LINNET_COVERFLOW_PACKED)
/* Drain and abandon artwork that shares STAGE; retain inhibition through any
 * subsequent upload/verify/update progress callbacks until the next boot. */
bool ln_coverflow_stage_claim(void);
/* Bounded synchronous admission for upload BEGIN and persistent verification. */
bool ln_coverflow_stage_prepare(void);
#endif
bool ln_coverflow_move(int32_t delta);
uint32_t ln_coverflow_count(void);
bool ln_coverflow_active(void);
bool ln_coverflow_select(void);
uint32_t ln_coverflow_tick(uint32_t now);
uint32_t ln_coverflow_deadline(void);
uint32_t ln_coverflow_io_deadline(void);
#if !defined(LINNET_PROFILE_RELEASE)
void ln_coverflow_diagnostics(uint32_t words[16]);
#if LINNET_COVERFLOW_SCANLINE
void ln_coverflow_render_diagnostics(uint32_t words[16]);
#endif
#endif
const char *ln_coverflow_text(bool artist);
/* Retained, verified native square, matched by playback path and CRC; no I/O. */
const uint16_t *ln_coverflow_playback_preview(const char *path,uint32_t crc);
#if defined(LINNET_SOC_PP5022)
/* Unoccupied artwork-array/lease tail; revoked allocations get a new epoch. */
uint8_t *ln_coverflow_files_memory(uint32_t *bytes,uint32_t *epoch);
#endif
void ln_coverflow_draw(const struct ln_ui_canvas_context *c);
#endif
#endif
