#ifndef LINNET_MUSIC_LIBRARY_H
#define LINNET_MUSIC_LIBRARY_H
#include <stdbool.h>
#include <stdint.h>
#include "services/music/database.h"

#define LN_MUSIC_LIBRARY_ROWS 12u
enum ln_music_library_status {
    LN_LIBRARY_CLOSED=0,LN_LIBRARY_OPENING,LN_LIBRARY_VERIFYING,
    LN_LIBRARY_READY,LN_LIBRARY_ERROR,LN_LIBRARY_DRAINING
};
struct ln_music_library_row {
    struct ln_music_track track;
    uint32_t index;
    char title[256],artist[256],path[256],album[256];
    char art_path[256];uint32_t art_crc;
    /* Album strings are resolved for playback selections/prefetch, not windows. */
    bool album_ready;
};
/* Init is boot-only. Reload/cancel preserve every admitted storage buffer until
 * its operation drains. Call step from the outer executive, never recursively
 * from storage_progress. Missing/corrupt databases stop in ERROR until reload. */
void ln_music_library_init(void);
void ln_music_library_step(void);
uint32_t ln_music_library_deadline(uint32_t now);
void ln_music_library_reload(void);
void ln_music_library_cancel(void);
/* Pause new I/O during PCM low-water pressure; admitted operations still drain. */
void ln_music_library_pause(bool pause);
enum ln_music_library_status ln_music_library_status(void);
int ln_music_library_error(void);
uint32_t ln_music_library_count(void);
uint32_t ln_music_library_group_count(void);
uint32_t ln_music_library_revision(void);
uint32_t ln_music_library_verified_bytes(void);
/* Immutable payload identity for binding queue/resume state to this database. */
bool ln_music_library_identity(uint8_t out[32]);

/* A window contains up to12 consecutive track-table rows. Cached pointers remain
 * valid until window/reload/cancel; callers must not retain them across step.
 * Revision advances per six filled slots, at end of library, and for a selected
 * row, limiting repaint storms while preserving completed-page publication. */
/* Disable speculative rows while retaining caches and draining any admitted read. */
void ln_music_library_window_enable(bool enabled);
void ln_music_library_window(uint32_t first);
const struct ln_music_library_row *ln_music_library_row(uint32_t track_index);
/* New selection supersedes an older unresolved selection, draining its read.
 * take_selection copies an immutable snapshot and consumes the result. */
bool ln_music_library_select(uint32_t track_index);
bool ln_music_library_take_selection(struct ln_music_library_row *out);
/* Independent next-track metadata slot. Explicit selection has priority. */
bool ln_music_library_prefetch(uint32_t track_index);
/* Discard next-track metadata intent; an admitted reader drains before reuse. */
void ln_music_library_cancel_prefetch(void);
bool ln_music_library_take_prefetch(struct ln_music_library_row *out);

/* Dedicated playback resolver, independent of external browser/search results.
 * Intent supersedes prior request; use a fresh nonzero token per request. Old
 * admitted I/O drains before replacement. UINT32_MAX means ordinal out of range.
 * Cancellation/reload invalidates results. Resolve current then prefetch serially. */
bool ln_music_library_queue_member(uint32_t group,uint32_t ordinal,uint32_t token);
bool ln_music_library_take_queue_member(uint32_t *track,uint32_t *token);

/* One external query at a time. Search returns first matching track or UINT32_MAX.
 * Group lookup returns the record/name; member lookup maps group-relative ordinal
 * to a track. Results are consumed by the matching take function. Selection has
 * priority over an unstarted query; both have priority over cache filling. */
bool ln_music_library_search(const char *prefix);
/* kind=0 is a track; 1/2 is an artist/album with a tagged group index. */
struct ln_music_library_search_row { uint32_t index,kind,count; char title[256]; };
bool ln_music_library_search_at(const char *prefix,uint32_t ordinal);
/* index UINT32_MAX means no matching result at this ordinal. */
bool ln_music_library_take_search_row(struct ln_music_library_search_row *out);
/* Uses the shared external query slot. source0/1 takes a track index;
 * source2 maps group-relative ordinal first. Out-of-range member returns
 * index UINT32_MAX. Matching take function alone consumes this result. */
bool ln_music_library_view_row(uint32_t source,uint32_t group,uint32_t ordinal);
bool ln_music_library_take_view_row(struct ln_music_library_search_row *out);
bool ln_music_library_take_search(uint32_t *track_index);
bool ln_music_library_group(uint32_t group_index);
bool ln_music_library_take_group(struct ln_music_group *out,char name[256]);
bool ln_music_library_group_member(uint32_t group_index,uint32_t ordinal);
bool ln_music_library_take_member(uint32_t *track_index);
#endif
