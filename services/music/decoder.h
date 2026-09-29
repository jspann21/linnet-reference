#ifndef LINNET_MUSIC_DECODER_H
#define LINNET_MUSIC_DECODER_H
#include "services/audio/codec_pcm.h"
#include "services/audio/mp3/mp3.h"
#include "services/audio/flac/flac.h"
#include "services/audio/alac/alac.h"
#include "services/audio/aac/aac.h"
#include "services/audio/aac/m4a.h"
/* The independently imported codec headers have different alignment macros.
 * Their already-declared structures retain each codec's native layout. */
#undef MEM_ALIGN_ATTR
#include "services/audio/vorbis/vorbis.h"
enum ln_decoder_kind {LN_DEC_UNKNOWN=0,LN_DEC_PCM,LN_DEC_MP3,LN_DEC_FLAC,LN_DEC_ALAC,LN_DEC_ADTS,LN_DEC_AAC_M4A,LN_DEC_VORBIS};
union ln_decoder_workspace {struct ln_pcm pcm;struct ln_mp3 mp3;struct ln_flac flac;struct ln_alac alac;
    struct ln_aac aac;struct ln_aac_m4a m4a;struct ln_vorbis vorbis;};
struct ln_decoder {
    union ln_decoder_workspace *data;
    ln_pcm_read_fn read;void *context;uint64_t size,total_frames;
    uint32_t kind,rate;bool opened;uint8_t signature[12];
};
void ln_decoder_init(struct ln_decoder *,union ln_decoder_workspace *,ln_pcm_read_fn,void *,uint64_t size);
int ln_decoder_decode(struct ln_decoder *,int16_t *,uint32_t,uint32_t *frames);
bool ln_decoder_seek(struct ln_decoder *,uint64_t frame);
/* Caller has drained/canceled the external read before either operation. */
void ln_decoder_read_drained(struct ln_decoder *);
void ln_decoder_close(struct ln_decoder *);
#endif
