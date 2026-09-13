#ifndef LINNET_MUSIC_QUEUE_VIEW_H
#define LINNET_MUSIC_QUEUE_VIEW_H
#include "queue.h"
#define LN_QUEUE_VIEW_ROWS 48u
enum ln_queue_view_action {LN_QUEUE_VIEW_PLAY=0,LN_QUEUE_VIEW_REMOVE,LN_QUEUE_VIEW_MOVE_UP,LN_QUEUE_VIEW_MOVE_DOWN};
/* Copies a bounded immutable queue snapshot; queue_revision must change for
 * ordering/source/cursor changes. Providers and inputs perform no I/O. */
void ln_music_queue_view_open(const struct ln_queue *,uint32_t queue_revision);
void ln_music_queue_view_update(const struct ln_queue *,uint32_t queue_revision);
void ln_music_queue_view_close(void);
void ln_music_queue_view_window(uint32_t first);
void ln_music_queue_view_visible_rows(uint32_t rows);
/* Root grants external query ownership only after browser suspension/drain and
 * search closure/drain. Pending viewer work always drains, even after close.
 * Root must wait !busy before granting the external slot to another service. */
void ln_music_queue_view_step(bool allow_query);
bool ln_music_queue_view_busy(void);
uint32_t ln_music_queue_view_count(void);
const char *ln_music_queue_view_label(uint32_t playback_ordinal);
uint32_t ln_music_queue_view_revision(void);
bool ln_music_queue_view_select(uint32_t playback_ordinal,uint32_t action);
bool ln_music_queue_view_take_action(uint32_t *playback_ordinal,uint32_t *action,uint32_t *queue_revision);
#endif
