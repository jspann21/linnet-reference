#ifndef LINNET_MUSIC_ARTWORK_H
#define LINNET_MUSIC_ARTWORK_H
#include <stdbool.h>
#include <stdint.h>
void ln_music_art_request(const char *path,uint32_t crc);
void ln_music_art_prefetch(const char *path,uint32_t crc);
/* Called only from the outer executive. An admitted operation always drains,
 * even when allow_read is false because the PCM ring needs priority. */
void ln_music_art_step(bool allow_read);
const uint16_t *ln_music_art_pixels(void);
uint32_t ln_music_art_revision(void);
#endif
