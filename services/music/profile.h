#ifndef LINNET_MUSIC_PROFILE_H
#define LINNET_MUSIC_PROFILE_H
#include "services/audio/dsp.h"
#define LN_MUSIC_PROFILE_BYTES 32u
enum ln_music_eq_preset {LN_MUSIC_EQ_FLAT,LN_MUSIC_EQ_BASS,LN_MUSIC_EQ_VOICE};
struct ln_music_profile {
    uint32_t preset,mode;int32_t balance,preamp_db_q16;
    bool replaygain,crossfeed;
};
void ln_music_profile_default(struct ln_music_profile *);
bool ln_music_profile_valid(const struct ln_music_profile *);
/* Rate must be one of the eleven native playback rates. Uses track gain only;
 * INT32_MIN means unknown/unity. Output is unchanged on failure. Bass/voice
 * apply one +3dB peaking band and -3dB preamp headroom; crossfeed is 700Hz/25%.
 * Apply through configured player admission, before that slot produces PCM. */
bool ln_music_profile_configure(const struct ln_music_profile *,uint32_t rate,
                               int32_t track_replaygain,struct ln_dsp_config *out);
/* Independent PROF record: magic@0,reservedu16@4=0,lengthu16@6=32,
 * flagsu32@8 (ReplayGain1,crossfeed2),presetu32@12,modeu32@16,
 * balancei32@20,preampQ16dBi32@24,CRC32@28 over bytes0..27. Little endian.
 * Embed alongside queue state in the caller's shared settings envelope. */
bool ln_music_profile_encode(const struct ln_music_profile *,uint8_t out[LN_MUSIC_PROFILE_BYTES]);
bool ln_music_profile_decode(struct ln_music_profile *,const uint8_t *,uint32_t bytes);
#endif
