#ifndef LINNET_MUSIC_BROWSER_H
#define LINNET_MUSIC_BROWSER_H
#include <stdbool.h>
#include <stdint.h>
#include "queue.h"

#define LN_MUSIC_BROWSER_ROWS 48u
/* Singleton, allocator-free browser. The outer executive calls step separately
 * from library_step. All other functions inspect memory or record intent only.
 * Owns the library's external group/member query slot exclusively. Selection and
 * prefetch slots remain available to the player. No group-sized allocation.
 * PODB group kinds must use the content compiler's ascending kind ordering.
 * Playback snapshots resolve the complete selected group before publication.
 */
void ln_music_browser_init(void);
void ln_music_browser_suspend(bool suspend);
/* Visibility gates speculative cache work, never an accepted playback intent. */
void ln_music_browser_set_visible(bool visible);
bool ln_music_browser_window_needed(void);
bool ln_music_browser_query_idle(void);
bool ln_music_browser_take_search(void);
void ln_music_browser_step(void);
uint32_t ln_music_browser_count(void);
const char *ln_music_browser_label(uint32_t row);
void ln_music_browser_window(uint32_t first);
void ln_music_browser_visible_rows(uint32_t rows);
bool ln_music_browser_select(uint32_t row);
struct ln_music_browser_queue {
    uint8_t library_hash[32];
    uint32_t count,cursor,tracks[LINNET_QUEUE_CAPACITY];
    uint32_t source,source_group;
};
enum ln_music_browser_queue_status { LN_BROWSER_QUEUE_IDLE=0,LN_BROWSER_QUEUE_LOADING=1,
    LN_BROWSER_QUEUE_READY=2,LN_BROWSER_QUEUE_CAPACITY=-1,LN_BROWSER_QUEUE_INVALID=-2 };
/* Select normally requests the full group including tracks before cursor.
 * Groups over64 publish a virtual source descriptor, bounded at100000 members.
 * tracks[] is populated only for source0; select_single explicitly requests one.
 * Window/navigation/new selection cancels and drains pending snapshot work. */
bool ln_music_browser_select_single(uint32_t row);
int ln_music_browser_queue_status(void);
bool ln_music_browser_take_queue(struct ln_music_browser_queue *out);
bool ln_music_browser_back(void);
const char *ln_music_browser_title(void);
uint32_t ln_music_browser_revision(void);
bool ln_music_browser_busy(void);
/* Advances for hierarchy changes, independently of cache publication. */
uint32_t ln_music_browser_navigation(void);
#endif
