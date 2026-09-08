#ifndef LINNET_MUSIC_JOURNAL_H
#define LINNET_MUSIC_JOURNAL_H
#include <stdbool.h>
#include <stdint.h>
#define LN_MUSIC_JOURNAL_CAPACITY 128u
#define LN_MUSIC_JOURNAL_BANK_BYTES 4608u
#define LN_MUSIC_JOURNAL_NO_BANK UINT32_MAX
#define LN_MUSIC_JOURNAL_FAVORITE 1u
#define LN_MUSIC_JOURNAL_BOOKMARK 2u
#define LN_MUSIC_JOURNAL_RESUME 4u
enum ln_music_journal_result {
    LN_JOURNAL_VALID=1,LN_JOURNAL_VALID_EMPTY=2,
    LN_JOURNAL_BOTH_INVALID=-1,LN_JOURNAL_CONFLICT=-2,LN_JOURNAL_ARGUMENT=-3
};
struct ln_music_journal_record {
    uint64_t id;
    uint32_t flags,play_count;
    uint64_t bookmark_frame,resume_frame;
};
struct ln_music_journal {
    struct ln_music_journal_record records[LN_MUSIC_JOURNAL_CAPACITY];
    uint8_t library_hash[32];
    uint32_t count,sequence,version,durable_version,active_bank;
    uint32_t staged_sequence,staged_version,staged_bank;
    bool ready,has_durable,staged;
};
/* JRN1 bank is4608 bytes, little endian:
 * 0 magicJRN1;4 u16format1;6 u16header64;8 u32sequence;12 u32count;
 * 16 librarypayloadSHA256[32];48 u32eventversion;52..63 reservedzero;
 * 64:128 records(idu64,flagsu32,playcountu32,bookmarku64,resumeu64);
 * unusedrecords and4160..4603 arezero;4604 CRC32/ISO-HDLC of0..4603.
 * Flags are favorite1/bookmarkpresent2/resumepresent4. Positions are PCMframes.
 * A cleared presence flag requires corresponding frame0. IDs are unique;0 is
 * a valid ID. Sequence0 and eventversion0 are valid, including empty banks.
 * All-zero hash may bind an explicitly provisioned empty library later.
 * Two identical sequence0 empty banks are a valid initial durable journal.
 * Equal-sequence different contents and half-range sequence ambiguity reject.
 */

/* Explicit creation only; never use to conceal BOTH_INVALID. Initial state is
 * dirty until a snapshot is acknowledged. Load accepts either valid bank and
 * leaves the complete old state unchanged on both-invalid/conflict/argument.
 * Input/output byte buffers must not overlap the state object. */
void ln_music_journal_init(struct ln_music_journal *,const uint8_t library_hash[32]);
int ln_music_journal_load(struct ln_music_journal *,const uint8_t *bank_a,uint32_t bytes_a,
                          const uint8_t *bank_b,uint32_t bytes_b);
bool ln_music_journal_dirty(const struct ln_music_journal *);
const struct ln_music_journal_record *ln_music_journal_get(const struct ln_music_journal *,uint64_t id);
/* All setters fail on uninitialized/full state without eviction or partial
 * change. Clearing a missing value is a successful no-op. Existing records are
 * retained even when all properties clear; no implicit forgetting occurs. */
bool ln_music_journal_set_favorite(struct ln_music_journal *,uint64_t id,bool favorite);
bool ln_music_journal_set_bookmark(struct ln_music_journal *,uint64_t id,bool present,uint64_t frame);
bool ln_music_journal_set_resume(struct ln_music_journal *,uint64_t id,bool present,uint64_t frame);
bool ln_music_journal_played(struct ln_music_journal *,uint64_t id);
/* Deliberate library update keeps stable-ID preferences/counts and marks dirty.
 * Binding to a new hash never discards records belonging to missing old tracks. */
bool ln_music_journal_rebind(struct ln_music_journal *,const uint8_t library_hash[32]);
/* One immutable in-flight snapshot; encoding a clean state is rejected.
 * Returned bank is the inactive0/1 file;
 * version is the acknowledgment token. Version/bank pointers cannot alias state.
 * Events after encoding remain dirty after this version is acknowledged.
 * mark_durable is called only after complete write, flush and readback proof.
 * I/O failure must latch in the adapter; do not mark durable or automatically
 * retry. Reload both banks after uncertain publication before writing again.
 * discard_unsubmitted is only for a snapshot NEVER submitted to storage. */
bool ln_music_journal_encode_next(struct ln_music_journal *,uint8_t *bank,uint32_t bytes,
                                 uint32_t *version,uint32_t *target_bank);
bool ln_music_journal_mark_durable(struct ln_music_journal *,uint32_t version);
bool ln_music_journal_discard_unsubmitted(struct ln_music_journal *,uint32_t version);
#endif
