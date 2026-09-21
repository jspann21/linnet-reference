#ifndef LINNET_COVERFLOW_H
#define LINNET_COVERFLOW_H
#include "ui/runtime/ui.h"
#if defined(LINNET_COVERFLOW)
void ln_coverflow_visible(bool visible);
void ln_coverflow_step(bool allow_read);
void ln_coverflow_move(int32_t delta);
uint32_t ln_coverflow_count(void);
bool ln_coverflow_active(void);
bool ln_coverflow_select(void);
uint32_t ln_coverflow_tick(uint32_t now);
uint32_t ln_coverflow_deadline(void);
uint32_t ln_coverflow_io_deadline(void);
#if !defined(LINNET_PROFILE_RELEASE)
void ln_coverflow_diagnostics(uint32_t words[16]);
#if defined(LINNET_TARGET_VIDEO5G_M25)
void ln_coverflow_render_diagnostics(uint32_t words[16]);
#endif
#endif
const char *ln_coverflow_text(bool artist);
void ln_coverflow_draw(const struct ln_ui_canvas_context *c);
#endif
#endif
