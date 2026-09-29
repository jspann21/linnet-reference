#pragma once
#include <stdbool.h>
#include <stdint.h>
/* Nonblocking panel startup; call poll between executive/USB work. */
bool ln_n25_panel_start(bool diagnostic);
/* Adopt a quiesced Boot panel only after validating the OS handoff. */
bool ln_n25_panel_adopt(void);
uint32_t ln_n25_panel_type(void);
uint32_t ln_n25_panel_poll(void);
uint32_t ln_n25_panel_service(uint32_t pixels);
/* The caller retains this full 320x240 RGB565 frame until poll returns 3. */
bool ln_n25_panel_present(const uint16_t *pixels);
