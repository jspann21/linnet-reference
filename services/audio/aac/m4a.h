#ifndef LINNET_AAC_M4A_H
#define LINNET_AAC_M4A_H
#include "aac.h"
#include "services/audio/alac/alac.h"
struct ln_aac_m4a {
    struct ln_aac core;struct ln_alac container;
    uint64_t total_frames,frame,seek_target;
    uint32_t rate,channels,lead_remaining;
    bool opened,seeking,pending,packet_ready;int error;
    uint64_t meta_cursor,meta_end,meta_ends[5],tag_frames;
    uint32_t meta_parents[5],meta_depth,meta_atoms,meta_phase,meta_type;
    uint32_t tag_lead,tag_tail;
    bool meta_done,tag_mean,tag_name,tag_data,tag_valid,tag_seen;
    uint64_t entry_frames;uint32_t entry_lead,entry_tail;
    uint8_t meta_buffer[256];
    /* Separate metadata/media windows avoid a seek for every STCO, STSZ and AU. */
    ln_aac_read_fn source_read;void *source_context;
    uint64_t cache_offset[2],cache_request_offset;
    uint32_t cache_bytes[2],cache_request_bytes;
    uint8_t *cache_request_buffer;
    uint8_t cache_victim,cache_filling;bool cache_pending;
    uint8_t read_cache[2][16384];
};
void ln_aac_m4a_init(struct ln_aac_m4a *,ln_aac_read_fn,void *,uint64_t file_size);
int ln_aac_m4a_open_step(struct ln_aac_m4a *);
int ln_aac_m4a_decode(struct ln_aac_m4a *,int16_t *,uint32_t capacity,uint32_t *frames);
/* Exact trimmed timeline seek. Forward/equal targets reuse valid overlap,
 * PNS RNG and demux state; backward targets or invalid overlap restart/decode.
 * No indexed fast-seek claim. Pending reads must drain first. decode reopens
 * automatically when the admitted seek requires a restart. */
bool ln_aac_m4a_seek(struct ln_aac_m4a *,uint64_t frame);
#endif
