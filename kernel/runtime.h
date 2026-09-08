#ifndef LINNET_RUNTIME_H
#define LINNET_RUNTIME_H
#include <stdint.h>
#include <stdbool.h>
enum { LN_INPUT_WHEEL=1, LN_INPUT_BUTTON=2, LN_INPUT_HOLD=3, LN_INPUT_HEADPHONE=4 };
enum { LN_CONTROL_SLEEP=1,LN_CONTROL_WAKE=2,LN_CONTROL_BACKLIGHT=3,LN_CONTROL_COP_RESET=4,LN_CONTROL_ANIMATION=5,LN_CONTROL_CLEAR_SYNTHETIC=6,LN_CONTROL_RESET_SHELL=7 };
bool ln_runtime_init(void);
void ln_runtime_step(void);
#if !defined(LINNET_PROFILE_RELEASE)
/* RND1 v1 dirty-render and publication inclusive timing; dev OS only. */
void ln_runtime_render_timing(uint32_t words[16]);
#endif
void ln_runtime_idle(void);
int ln_runtime_inject(uint32_t kind,int32_t value,uint32_t sequence);
uint32_t ln_runtime_state(uint32_t *output,uint32_t capacity_words);
int ln_runtime_control(uint32_t command,uint32_t argument);
const uint16_t *ln_runtime_framebuffer(void);
uint32_t ln_runtime_frame_crc(void);
uint32_t ln_runtime_ui_state(uint32_t *output,uint32_t capacity_words);
#endif
