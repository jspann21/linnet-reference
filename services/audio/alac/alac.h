#ifndef LINNET_ALAC_H
#define LINNET_ALAC_H
#include <stdbool.h>
#include <stdint.h>
#include "third_party/alac/decomp.h"
typedef int (*ln_alac_read_fn)(void *,uint64_t,uint8_t *,uint32_t);
enum ln_alac_result { LN_ALAC_PENDING=0,LN_ALAC_READY=1,LN_ALAC_EOF=2,
    LN_ALAC_IO=-1,LN_ALAC_FORMAT=-2,LN_ALAC_UNSUPPORTED=-3,LN_ALAC_ARGUMENT=-4 };
struct ln_alac_time {uint32_t count,delta;};
struct ln_alac_chunk {uint32_t first,count;};
struct ln_alac {
    ln_alac_read_fn read;void *context;alac_file core;
    uint64_t file_size,cursor,ends[8],atom_start,atom_end,mdat_start,mdat_end;
    uint64_t media_start[8],media_end[8],track_start;
    uint64_t sizes_offset,chunks_offset,packet_offset,total_frames,frame,seek_target;
    uint32_t parents[8],depth,atoms,tracks,seen,atom_type,body_bytes;
    uint32_t media_count,track_depth;
    uint32_t rate,channels,packets,chunks,default_size,chunk_width,time_count,chunk_count;
    uint32_t packet,packet_size,chunk_index,chunk_first,chunk_packets,chunk_ordinal;
    uint32_t size_scan,next_packet,next_chunk;
    uint64_t next_offset;
    bool next_valid;
    uint32_t pcm_count,pcm_cursor,skip,phase,decode_phase;
    uint32_t codec,asc_bytes,current_packet_frames,lead_trim,tail_trim;
    uint32_t movie_scale,edit_duration;
    uint64_t read_offset;
    uint32_t read_total,read_done;
    uint8_t asc[64];
    struct ln_alac_time times[128];struct ln_alac_chunk map[1024];
    int32_t pcm[2][4096];uint8_t buffer[32768];
    bool pending,opened,allow_aac,track_probe,time_regular,extends_to_eof;int error;
    /* Independent media/table windows; AAC supplies its own outer cache. */
    ln_alac_read_fn source_read;void *source_context;
    uint64_t cache_offset[2],cache_request_offset;
    uint32_t cache_bytes[2],cache_request_bytes;
    uint8_t *cache_request_buffer;
    uint8_t cache_victim,cache_filling;bool cache_pending;
    uint8_t read_cache[2][16384];
};
/* Exact immutable asynchronous reads, same ownership contract as PCM. Calls to
 * the upstream core are serialized: coefficient scratch is static. M4A support
 * is nonfragmented, one audio track, <=8 media extents, integer16 mono/stereo, <=4096 frames/packet,
 * <=32768 compressed bytes/packet, <=1M packets/chunks,
 * <=128 ALAC time runs and1024 sample-to-chunk runs. No resampling or encryption. */
void ln_alac_init(struct ln_alac *,ln_alac_read_fn,void *,uint64_t file_size);
int ln_alac_open_step(struct ln_alac *);
int ln_alac_decode(struct ln_alac *,int16_t *stereo,uint32_t capacity,uint32_t *frames);
bool ln_alac_seek(struct ln_alac *,uint64_t frame);
/* Shared bounded M4A demux for the AAC facade. codec is17 AAC-LC or18 ALAC.
 * read_packet returns1 with buffer/packet_size/current_packet_frames and advances
 * packet,0 pending,2 EOF. No next call until the consumer finishes this buffer.
 * total_frames is the encoded sample timeline. Discard lead_trim decoded frames;
 * each packet's valid frames are current_packet_frames (last may be shorter).
 * AAC reduces rounded timestamps to its fixed packet size. Edits may remove
 * less than one trailing AAC packet via tail_trim; movie-tick rounding alone
 * does not change the sample count. ALAC retains exact STTS packet timing.
 * A raw timeline seek stores the intra-packet discard in skip; caller consumes
 * it. Single nonnegative rate1 edit is accepted, negative/multiple edits reject.
 * ASC is <=64 bytes. AAC access units are <=8191 bytes. */
void ln_m4a_init(struct ln_alac *,ln_alac_read_fn,void *,uint64_t file_size);
int ln_m4a_open_step(struct ln_alac *);
int ln_m4a_read_packet(struct ln_alac *);
bool ln_m4a_seek_indexed(struct ln_alac *,uint32_t packet,uint64_t offset);
#endif
