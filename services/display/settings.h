#ifndef LINNET_DISPLAY_SETTINGS_H
#define LINNET_DISPLAY_SETTINGS_H
#include <stdbool.h>
#include <stdint.h>
void ln_display_settings_init(void);
#if !defined(LINNET_PROFILE_RELEASE)
void ln_display_settings_diagnostics(uint32_t words[8]);
#endif
bool ln_display_settings_boot_ready(void);
bool ln_display_clock_12(void);
void ln_display_clock_toggle(void);
/* Terminal shutdown/Sync flush bypasses theme presentation; normal runtime uses
 * step_ready below. Paused/stopped audio admission remains required for all I/O. */
void ln_display_settings_step(bool may_write);
/* Normal runtime: theme publication requires the completed frame's revision.
 * Loading and unrelated settings are independent of theme presentation. */
void ln_display_settings_step_ready(bool may_write,bool theme_presented,uint32_t presented_revision);
uint32_t ln_display_theme_revision(void);
/* Bounded memory-only final frame check after storage preparation/read callbacks.
 * The runtime override verifies this revision's completed frame is still valid;
 * it must remain bounded with no blocking I/O or application callbacks.
 * Local completion tracking may change. Weak default is false. */
bool ln_display_theme_presented(uint32_t revision);
uint32_t ln_display_backlight_timeout_us(void);
uint32_t ln_display_settings_revision(void);
/* UINT32_MAX keeps the compiled default; persistence stores the stable theme ID. */
uint32_t ln_display_theme_index(void);
bool ln_display_theme_set(uint32_t index);
void ln_display_game_best_set(uint32_t index,uint16_t score);
const char *ln_display_theme_status(void);
bool ln_display_settings_pending(void);
bool ln_display_settings_adjust(int32_t direction);
/* User supplied nominal capacity; does not alter charge limits or gauge voltage. */
uint32_t ln_auto_shutdown_seconds(bool headphones);
bool ln_auto_shutdown_adjust(bool headphones,int32_t direction);
uint32_t ln_battery_capacity_mah(void);
const char *ln_battery_capacity_label(void);
bool ln_battery_capacity_adjust(int32_t direction);
/* Caller supplies a cached storage snapshot; rendering performs no storage I/O. */
bool ln_display_update_status(const char *build,const uint32_t state[16],uint32_t history);
const char *ln_display_settings_label(void);
/* Shared settings owner: preserves the opaque music payload and display value. */
int ln_display_settings_music(bool write,uint8_t *data,uint32_t *length);
/* Restore only: 1 valid envelope, 0 temporarily unavailable, -1 malformed. */
int ln_display_settings_music_restore(uint8_t *data,uint32_t *length);
bool ln_display_settings_photo_get(uint8_t out[16]);
void ln_display_settings_photo_set(const uint8_t in[16]);
bool ln_display_settings_video_get(uint32_t out[2]);
void ln_display_settings_video_set(const uint32_t in[2]);
bool ln_display_settings_video_options_get(uint8_t *out);
void ln_display_settings_video_options_set(uint8_t options);
struct ln_ui_node;
const char *ln_display_settings_text(const struct ln_ui_node *,uint32_t,const char *);
#endif
