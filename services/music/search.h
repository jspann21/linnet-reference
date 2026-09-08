#ifndef LINNET_MUSIC_SEARCH_H
#define LINNET_MUSIC_SEARCH_H
#include <stdint.h>
#include <stdbool.h>
#define LN_MUSIC_SEARCH_PREFIX 32u
#define LN_MUSIC_SEARCH_ROWS 12u
/* Input/provider functions record intent only. step owns asynchronous queries
 * after the browser has suspended and drained its existing query. */
void ln_music_search_open(void);
void ln_music_search_close(void);
void ln_music_search_step(void);
bool ln_music_search_busy(void);
bool ln_music_search_active(void);
uint32_t ln_music_search_count(void);
const char *ln_music_search_label(uint32_t row);
const char *ln_music_search_prefix(void);
const char *ln_music_search_hint(void);
const char *ln_music_search_title(void);
uint32_t ln_music_search_revision(void);
uint32_t ln_music_search_navigation(void);
bool ln_music_search_select(uint32_t row);
void ln_music_search_left(void);
void ln_music_search_right(void);
/* True means returned from results to editor; false means search closed. */
bool ln_music_search_back(void);
void ln_music_search_window(uint32_t first);
bool ln_music_search_take_track(uint32_t *track);
#endif
