#ifndef LINNET_GAMES_H
#define LINNET_GAMES_H
#include <stdint.h>
#include <stdbool.h>
#include "ui/runtime/ui.h"
#define LN_GAME_COUNT 12u
#define LN_GAME_MASK ((uint16_t)((1u<<LN_GAME_COUNT)-1u))
uint32_t ln_games_count(void);
const char *ln_games_label(uint32_t row);
const char *ln_games_description(uint32_t row);
void ln_games_start(uint32_t row);
int ln_games_input(uint32_t kind,int32_t value);
bool ln_games_tick(uint32_t now);
uint32_t ln_games_deadline(uint32_t now);
uint32_t ln_games_hud_revision(void);
bool ln_games_playing(void);
void ln_games_audio_step(void);
void ln_games_audio_stop(void);
const char *ln_games_text(const char *key);
void ln_games_configure(uint16_t mask);
void ln_games_best_set(uint32_t index,uint16_t value);
void ln_games_draw(const struct ln_ui_canvas_context *context);
#endif
