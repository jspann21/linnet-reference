#include "services/music/player.h"
#include "services/music/decoder.h"
#include "services/storage/storage.h"
#include "services/audio/dsp.h"
#include "hal/api/audio.h"
#include "hal/api/platform.h"
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
#include "hal/api/ata.h"
#define PLAYER_MP3_CACHE_BYTES 0x300000u
#define PLAYER_MP3_CACHE(window) ((uint8_t *)(uintptr_t)(LINNET_STAGE_ADDRESS+0x100000u+(window)*PLAYER_MP3_CACHE_BYTES))
_Static_assert(0x100000u+2u*PLAYER_MP3_CACHE_BYTES+
    (LINNET_AUDIO_RING_FRAMES+1152u)*4u<=LINNET_STAGE_CAPACITY,
    "MP3 read cache overlaps PCM staging");
#endif
#if !defined(LINNET_PROFILE_RELEASE)
#include "kernel/development.h"
#endif
#define PLAYER_DECODE_FRAMES 1152u
/* Music, video and firmware upload have exclusive ownership of STAGE. */
#define RAW_PCM ((int16_t *)(uintptr_t)(LINNET_STAGE_ADDRESS+LINNET_STAGE_CAPACITY-LINNET_AUDIO_RING_FRAMES*4u))
#define EFFECT_PCM (RAW_PCM-PLAYER_DECODE_FRAMES*2u)
_Static_assert((LINNET_AUDIO_RING_FRAMES+PLAYER_DECODE_FRAMES)*4u<=LINNET_STAGE_CAPACITY,"PCM cache exceeds staging");
static uint32_t raw_head,effect_cursor;
static bool effect_pending;
enum slot_phase {SLOT_EMPTY,SLOT_OPEN,SLOT_DECODE,SLOT_EOF,SLOT_FAILED};
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
struct player_cache_window {uint32_t start,valid,target;bool filling;};
#endif
struct player_slot {
    struct ln_decoder decoder;struct ln_dsp dsp;struct ln_fat32_file media;
    char path[LN_FAT32_PATH_MAX+1];int16_t pcm[PLAYER_DECODE_FRAMES*2u];
    uint64_t expected,initial,position_base,submitted;
    uint32_t phase,generation,token,buffered,rate,config_rate;bool seek_initial;
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
    struct player_cache_window cache[2];
    uint32_t cache_current;
    bool cache_enabled,cache_initial,cache_pending;
#endif
};
static struct player_slot slots[2];
static bool (*file_configure)(uint32_t,struct ln_dsp_config *);
/* Each codec initializes its own arena when selected. Keep only ownership and
 * validity in zeroed BSS, avoiding a second multi-megabyte clear during boot. */
static union ln_decoder_workspace decoder_workspaces[2]
    __attribute__((section(".media_workspace"),aligned(8)));
static struct ln_player_status state;
#if !defined(LINNET_PROFILE_RELEASE)
static struct ln_player_timing timing;
static void timing_add(uint32_t *v,uint32_t n){*v=n>UINT32_MAX-*v?UINT32_MAX:*v+n;}
void ln_player_timing_snapshot(struct ln_player_timing *out){if(out)*out=timing;}
void ln_player_timing_runtime(uint32_t elapsed){timing_add(&timing.runtime_calls,1);timing_add(&timing.runtime_us,elapsed);if(elapsed>timing.runtime_max_us)timing.runtime_max_us=elapsed;}
void ln_player_timing_stage(uint32_t stage,uint32_t elapsed){if(stage==0)timing_add(&timing.music_us,elapsed);else if(stage==1)timing_add(&timing.storage_us,elapsed);else if(stage==2)timing_add(&timing.link_us,elapsed);}
#endif
static struct ln_player_transition transition;
static struct player_slot *io_owner;
static uint32_t io_offset,io_length;static uint8_t *io_buffer;static bool io_open;
static uint32_t audible,feed,generation_counter,last_consumed,join_underruns;
uint32_t ln_player_decoder_kind(void){return slots[audible].decoder.kind;}
static uint64_t consumed,submitted,audible_origin,join_boundary;
static bool stop_requested,seek_requested,pause_requested,have_next,cancel_next;
static bool skip_requested,seek_paused;
static bool audio_ready,join_pending,join_gapless,event_pending,finish_sent,stepping;
static uint64_t seek_target;
static bool next_expected,eof_waiting;
static uint32_t eof_deadline;
uint32_t ln_player_background_frames(uint32_t rate){
    uint32_t frames=rate/4u*3u;
    if(frames<8192u)frames=8192u;
    if(frames>LINNET_AUDIO_RING_FRAMES-2048u)frames=LINNET_AUDIO_RING_FRAMES-2048u;
    return frames;
}
static uint32_t prefetch_frames(uint32_t rate){
    /* Opening the next track can hold the shared reader for longer than the
     * ordinary background window. Refill current PCM before admitting it. */
    uint32_t frames=rate+rate/4u;
    if(frames<8192u)frames=8192u;
    if(frames>LINNET_AUDIO_RING_FRAMES-2048u)frames=LINNET_AUDIO_RING_FRAMES-2048u;
    return frames;
}
void ln_player_expect_next(bool expected){
    next_expected=expected&&!stop_requested&&!seek_requested&&!skip_requested&&
        state.phase!=LN_PLAYER_IDLE&&state.phase!=LN_PLAYER_STOPPING&&state.phase!=LN_PLAYER_ERROR;
}
bool ln_player_prefetch_urgent(void){
    return (next_expected||have_next)&&audio_ready&&slots[feed].phase==SLOT_EOF&&
        (state.phase==LN_PLAYER_PLAY||state.phase==LN_PLAYER_DRAIN);
}
static bool interrupted(void){return stop_requested||seek_requested||cancel_next||skip_requested;}
static uint32_t generation(void){if(++generation_counter==0||generation_counter>=0x10000000u)generation_counter=1;return generation_counter;}
static bool supported_rate(uint32_t rate){
    switch(rate){case 8000:case 11025:case 12000:case 16000:case 22050:case 24000:
    case 32000:case 44100:case 48000:case 88200:case 96000:return true;default:return false;}
}
static int poll_media(struct player_slot *s,struct ln_fat32_file *file,uint32_t *transferred){
    bool starting=state.phase==LN_PLAYER_OPEN||state.phase==LN_PLAYER_HEADER||state.phase==LN_PLAYER_PRIME;
    uint32_t began=ln_time_us();int result;
    for(uint32_t step=0;;step++){
        result=ln_storage_media_poll_deferred(s->generation,file,transferred);
        if(result||!starting||step==3u||interrupted())return result;
        uint32_t now=ln_time_us(),deadline;
        if(now-began>=500u||(ln_storage_idle_wait(now,&deadline)&&(int32_t)(deadline-now)>0))return 0;
    }
}
static int read_disk(struct player_slot *s,uint32_t offset,uint8_t *buffer,uint32_t length){
    if(io_owner&&io_owner!=s)return 0;
    if(!io_owner){
        if(have_next&&!join_pending&&s==&slots[audible^1u]&&audio_ready&&state.phase==LN_PLAYER_PLAY){
            struct ln_audio_status audio;ln_audio_snapshot(&audio);
            if(slots[feed].phase!=SLOT_EOF){
                if(audio.queued<prefetch_frames(audio.rate))return 0;
            }else if(eof_waiting&&(int32_t)(ln_time_us()-eof_deadline)>=0)return 0;
        }
        int r=ln_storage_media_read(&s->media,offset,buffer,length,s->generation);if(r<=0)return r;
        io_owner=s;io_open=false;io_offset=offset;io_length=length;io_buffer=buffer;
    }else if(io_open||io_offset!=offset||io_length!=length||io_buffer!=buffer)return -1;
    uint32_t transferred=0;int r=poll_media(s,0,&transferred);
    if(!r)return 0;io_owner=0;return r==1&&transferred==length?1:-1;
}
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
static int cache_hit(struct player_slot *s,uint32_t at,uint32_t length){
    for(uint32_t i=0;i<2u;++i){
        const struct player_cache_window *w=&s->cache[i];
        if(at>=w->start&&at-w->start<=w->valid&&length<=w->valid-(at-w->start))return (int)i;
    }
    return -1;
}
static bool cache_begin(struct player_slot *s,uint32_t window,uint32_t at,bool initial){
    if(at>=s->media.size)return false;
    uint64_t available=s->media.size-at;
    /* Every subsequent storage offset must remain representable. */
    if(available>UINT32_MAX-at)available=UINT32_MAX-at;
    if(!available)return false;
    struct player_cache_window *w=&s->cache[window];
    w->start=at;w->valid=0;w->target=initial?131072u:PLAYER_MP3_CACHE_BYTES;
    if(w->target>available)w->target=(uint32_t)available;
    w->filling=true;return true;
}
static int cache_progress(struct player_slot *s){
    for(uint32_t i=0;i<2u;++i){
        struct player_cache_window *w=&s->cache[i];
        if(!w->filling)continue;
        uint32_t chunk=w->target-w->valid;
        if(chunk>LN_STORAGE_MEDIA_MAX_READ)chunk=LN_STORAGE_MEDIA_MAX_READ;
        int r=read_disk(s,w->start+w->valid,PLAYER_MP3_CACHE(i)+w->valid,chunk);
        if(r<=0)return r;
        w->valid+=chunk;
        if(w->valid==w->target)w->filling=false;
        return 1;
    }
    return 1;
}
static int cache_copy(struct player_slot *s,uint32_t window,uint32_t at,uint8_t *buffer,uint32_t length){
    struct player_cache_window *w=&s->cache[window];
    __builtin_memcpy(buffer,PLAYER_MP3_CACHE(window)+(at-w->start),length);
    s->cache_current=window;
    if(cache_progress(s)<0)return -1;
    uint32_t consumed=at-w->start+length;
    uint32_t threshold=w->target/2u;if(threshold>524288u)threshold=524288u;
    if(!w->filling&&w->target-consumed<=threshold){
        uint32_t next=w->start+w->target,other=window^1u;
        struct player_cache_window *candidate=&s->cache[other];
        if(next<s->media.size&&!candidate->filling&&
           (candidate->start!=next||candidate->valid!=candidate->target)&&
           cache_begin(s,other,next,false)&&cache_progress(s)<0)return -1;
    }
    return 1;
}
#endif
static int read_media(void *context,uint64_t offset,uint8_t *buffer,uint32_t length){
    struct player_slot *s=context;if(offset>UINT32_MAX)return -1;
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
    if(s->cache_enabled&&length<=LN_STORAGE_MEDIA_MAX_READ){
        uint32_t at=(uint32_t)offset;
        if(length>UINT32_MAX-at)return read_disk(s,at,buffer,length);
        int hit=cache_hit(s,at,length);
        if(hit>=0)return cache_copy(s,(uint32_t)hit,at,buffer,length);
        if(cache_progress(s)<0)return -1;
        hit=cache_hit(s,at,length);
        if(hit>=0)return cache_copy(s,(uint32_t)hit,at,buffer,length);
        if(s->cache[0].filling||s->cache[1].filling)return 0;
        if(at>s->media.size||length>s->media.size-at)return -1;
        uint32_t window=s->cache_current^1u;
        if(!cache_begin(s,window,at,s->cache_initial))return read_disk(s,at,buffer,length);
        s->cache_initial=false;
        if(cache_progress(s)<0)return -1;
        hit=cache_hit(s,at,length);
        return hit>=0?cache_copy(s,(uint32_t)hit,at,buffer,length):0;
    }
#endif
    return read_disk(s,(uint32_t)offset,buffer,length);
}
static void clear_slot(struct player_slot *s){
    ln_decoder_close(&s->decoder);s->phase=SLOT_EMPTY;s->buffered=0;
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
    s->cache_enabled=s->cache_pending=false;s->cache[0].filling=s->cache[1].filling=false;
#endif
}
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
static bool cache_mp3(const char *name){
    uint32_t n=0;while(name[n])++n;
    if(n<4u||name[n-4u]!='.'||
       (name[n-3u]!='m'&&name[n-3u]!='M')||
       (name[n-2u]!='p'&&name[n-2u]!='P')||name[n-1u]!='3')return false;
    struct ln_ata_info media;ln_ata_snapshot(&media);
    return media.media_kind==LN_ATA_MEDIA_ROTATING;
}
static void activate_cache(struct player_slot *s){
    if(io_owner==s){s->cache_pending=true;return;}
    s->cache_enabled=cache_mp3(s->path);s->cache_pending=false;
    s->cache_initial=true;s->cache_current=1u;
    for(uint32_t i=0;i<2u;++i)s->cache[i]=(struct player_cache_window){0};
}
#endif
static bool name_copy(char *out,const char *name){
    if(!name||name[0]!='/')return false;uint32_t n=0;
    while(n<=LN_FAT32_PATH_MAX&&name[n])n++;if(!n||n>LN_FAT32_PATH_MAX)return false;
    for(uint32_t i=0;i<=n;i++)out[i]=name[i];return true;
}
static bool start_slot(struct player_slot *s,const char *name,uint64_t expected,uint64_t position,uint32_t token,
                       const struct ln_dsp *dsp,uint32_t config_rate){
    if(!name_copy(s->path,name))return false;
    s->expected=expected;s->initial=position;s->position_base=0;s->submitted=0;s->token=token;
    s->generation=generation();s->buffered=0;s->rate=0;s->seek_initial=position!=0;
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
    s->cache_enabled=s->cache_pending=false;s->cache_initial=true;s->cache_current=1u;
    for(uint32_t i=0;i<2u;++i)s->cache[i]=(struct player_cache_window){0};
#endif
    s->phase=SLOT_OPEN;s->dsp=*dsp;s->config_rate=config_rate;return true;
}
static void fail(uint32_t error){
    next_expected=eof_waiting=false;
    state.error=error;stop_requested=true;state.phase=LN_PLAYER_STOPPING;(void)ln_audio_stop();
    if(io_owner)ln_storage_media_cancel(io_owner->generation);
}
/* The pending owner alone polls storage, returning to the executive after
 * bounded work. Keep interruption checks for controls from other service paths. */
static int slot_step(struct player_slot *s){
    if(s->phase==SLOT_OPEN){
        if(io_owner&&io_owner!=s)return 0;
        if(!io_owner){int r=ln_storage_media_open(s->path,s->generation);if(r<=0)return r;io_owner=s;io_open=true;}
        int r=poll_media(s,&s->media,0);if(!r)return 0;io_owner=0;
        if(interrupted())return 0;
        if(r<0||(s->expected&&s->expected!=s->media.size))return -1;
        ln_decoder_init(&s->decoder,&decoder_workspaces[s-slots],read_media,s,s->media.size);s->phase=SLOT_DECODE;return 0;
    }
    if(s->phase==SLOT_EOF)return 2;if(s->phase!=SLOT_DECODE||s->buffered)return 0;
    uint32_t frames=0;
#if !defined(LINNET_PROFILE_RELEASE)
    uint32_t started=ln_time_us();
#endif
    int r=ln_decoder_decode(&s->decoder,s->pcm,PLAYER_DECODE_FRAMES,&frames);
#if !defined(LINNET_PROFILE_RELEASE)
    uint32_t elapsed=ln_time_us()-started;timing_add(&timing.decode_calls,1);timing_add(&timing.decode_us,elapsed);
    if(elapsed>timing.decode_max_us)timing.decode_max_us=elapsed;
#endif
    if(interrupted())return 0;if(r<0)return r;
    if(s->decoder.opened&&s->decoder.rate){
        s->rate=s->decoder.rate;if(!supported_rate(s->rate))return -4;
        if(file_configure&&!s->config_rate){struct ln_dsp_config config;
            if(!file_configure(s->rate,&config)||!ln_dsp_configure(&s->dsp,&config))return -4;
            s->config_rate=s->rate;}
        if(s->config_rate&&s->config_rate!=s->rate)return -4;
        if(s->seek_initial){
            if(io_owner)return 0;
            if(s->decoder.total_frames&&s->initial>=s->decoder.total_frames)s->initial=0;
            if(!ln_decoder_seek(&s->decoder,s->initial))return -3;
            s->position_base=s->initial;s->seek_initial=false;return 0;
        }
    }
    s->buffered=frames;if(r==2)s->phase=SLOT_EOF;return r;
}
static void next_failure(int error){
    struct player_slot *s=&slots[audible^1u];state.next_error=(uint32_t)(error<0?-error:error);
    state.next_phase=LN_PLAYER_NEXT_FAILED;s->phase=SLOT_FAILED;s->buffered=0;ln_decoder_close(&s->decoder);
}
static void advance_next(void){
    if(!have_next||join_pending||state.next_phase==LN_PLAYER_NEXT_FAILED||cancel_next)return;
    struct player_slot *s=&slots[audible^1u];int r=slot_step(s);if(interrupted())return;
    if(r<0){next_failure(r);return;}
    if(s->buffered&&s->rate)state.next_phase=LN_PLAYER_NEXT_READY;
    else if(s->phase==SLOT_EOF)next_failure(-2);
}
static bool initialize_audio(uint32_t rate){
    if(!ln_audio_init(rate))return false;last_consumed=raw_head=0;effect_pending=false;submitted=consumed;audio_ready=true;finish_sent=false;eof_waiting=false;return true;
}
static void process_pcm(struct player_slot *s,int16_t *pcm,uint32_t frames){
#if !defined(LINNET_PROFILE_RELEASE)
    uint32_t started=ln_time_us();
#endif
    ln_dsp_process(&s->dsp,pcm,frames);
#if !defined(LINNET_PROFILE_RELEASE)
    uint32_t elapsed=ln_time_us()-started;timing_add(&timing.dsp_calls,1);timing_add(&timing.dsp_frames,frames);timing_add(&timing.dsp_us,elapsed);
    if(elapsed>timing.dsp_max_us)timing.dsp_max_us=elapsed;
#endif
}
static bool submit_slot(struct player_slot *s){
    if(!s->buffered)return true;if(ln_audio_capacity()<s->buffered)return false;
    uint32_t at=raw_head&(LINNET_AUDIO_RING_FRAMES-1u);
    uint32_t first=LINNET_AUDIO_RING_FRAMES-at;
    if(first>s->buffered)first=s->buffered;
    __builtin_memcpy(RAW_PCM+2*at,s->pcm,first*4u);
    if(first<s->buffered)
        __builtin_memcpy(RAW_PCM,s->pcm+2*first,(s->buffered-first)*4u);
    raw_head+=s->buffered;process_pcm(s,s->pcm,s->buffered);
    if(ln_audio_submit(s->pcm,s->buffered)!=s->buffered){fail(14);return false;}
    s->submitted+=s->buffered;submitted+=s->buffered;s->buffered=0;return true;
}
static void refresh(const struct ln_audio_status *audio){
    consumed+=(uint32_t)(audio->consumed-last_consumed);last_consumed=audio->consumed;state.underruns=audio->underruns;
    if(join_pending&&consumed>join_boundary){
        uint32_t old=audible;audible=feed;audible_origin=join_boundary;
        bool clean=join_gapless&&audio->underruns==join_underruns;
        transition=(struct ln_player_transition){.token=slots[audible].token,.gapless=clean,.boundary=join_boundary,.underruns=audio->underruns};
        event_pending=true;join_pending=false;have_next=false;state.next_phase=LN_PLAYER_NEXT_NONE;state.next_error=0;
        if(clean)state.gapless_joins++;else state.missed_joins++;clear_slot(&slots[old]);
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
        activate_cache(&slots[audible]);
#endif
    }
    struct player_slot *s=&slots[audible];state.rate=s->rate;state.frames=s->decoder.total_frames;state.decoded=(uint32_t)s->submitted;
    uint64_t rendered=consumed-audible_origin;if(rendered>s->submitted)rendered=s->submitted;state.rendered=(uint32_t)rendered;
}
bool ln_player_open(const char *name){return ln_player_open_at(name,0,0);}
bool ln_player_open_at(const char *name,uint64_t bytes,uint64_t position){
    return ln_player_open_configured(name,bytes,position,0,0);
}
static bool prepare_dsp(struct ln_dsp *dsp,const struct ln_dsp_config *config,uint32_t rate){
    ln_dsp_init(dsp);return !config||(supported_rate(rate)&&ln_dsp_configure(dsp,config));
}
bool ln_player_configure(const struct ln_dsp_config *config,uint32_t rate){
    if(stop_requested||skip_requested||join_pending||event_pending)return false;
    if(state.phase==LN_PLAYER_IDLE||state.phase==LN_PLAYER_ERROR)return true;
    struct player_slot *s=&slots[audible];struct ln_dsp candidate;
    if(!config||!prepare_dsp(&candidate,config,rate)||(s->rate&&s->rate!=rate))return false;
    if(audio_ready){
        struct ln_audio_status audio;ln_audio_snapshot(&audio);
        uint32_t skip=audio.playing?2048u:0u;if(skip>audio.queued)skip=audio.queued;
        effect_cursor=audio.consumed+skip;effect_pending=effect_cursor!=raw_head;
    }
    s->dsp=candidate;s->config_rate=rate;return true;
}
bool ln_player_open_configured(const char *name,uint64_t bytes,uint64_t position,
                               const struct ln_dsp_config *config,uint32_t config_rate){
    if(state.phase!=LN_PLAYER_IDLE||ln_storage_busy()||!ln_storage_mounted())return false;
#if !defined(LINNET_PROFILE_RELEASE)
    if(ln_development_stage_busy())return false;
#endif
    struct ln_dsp dsp;if(!prepare_dsp(&dsp,config,config_rate))return false;
    file_configure=0;
    if(!start_slot(&slots[0],name,bytes,position,0,&dsp,config?config_rate:0))return false;
#if !defined(LINNET_PROFILE_RELEASE)
    timing=(struct ln_player_timing){0};
#endif
    audible=feed=0;state=(struct ln_player_status){.phase=LN_PLAYER_OPEN,.generation=slots[0].generation};
    io_owner=0;stop_requested=seek_requested=pause_requested=have_next=cancel_next=false;
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
    activate_cache(&slots[0]);
#endif
    skip_requested=seek_paused=false;
    effect_pending=audio_ready=join_pending=event_pending=finish_sent=next_expected=eof_waiting=false;consumed=submitted=audible_origin=0;last_consumed=0;return true;
}
bool ln_player_open_file(const struct ln_fat32_file *file,bool (*configure)(uint32_t,struct ln_dsp_config *)){
    if(!file||(file->attributes&24u)||!file->size||!ln_player_open("/FILE"))return false;
    struct player_slot*s=&slots[0];s->media=*file;file_configure=configure;
    ln_decoder_init(&s->decoder,&decoder_workspaces[0],read_media,s,file->size);s->phase=SLOT_DECODE;
    return true;
}
bool ln_player_prepare_next_configured(const char *name,uint64_t bytes,uint32_t token,
                                      const struct ln_dsp_config *config,uint32_t config_rate){
    if((state.phase!=LN_PLAYER_PRIME&&state.phase!=LN_PLAYER_PLAY&&state.phase!=LN_PLAYER_PAUSE&&state.phase!=LN_PLAYER_DRAIN)||join_pending||event_pending||cancel_next||skip_requested)return false;
    if(have_next&&state.next_phase!=LN_PLAYER_NEXT_FAILED)return false;
    struct player_slot *s=&slots[audible^1u];if(io_owner==s)return false;
    struct ln_dsp dsp;if(!prepare_dsp(&dsp,config,config_rate))return false;
    char checked_name[LN_FAT32_PATH_MAX+1];if(!name_copy(checked_name,name))return false;
    clear_slot(s);if(!start_slot(s,checked_name,bytes,0,token,&dsp,config?config_rate:0))return false;
    have_next=true;state.next_phase=LN_PLAYER_NEXT_OPENING;state.next_error=0;return true;
}
bool ln_player_cancel_next(void){
    if(event_pending)return false;
    if(skip_requested){ln_player_stop_for_restart();return true;}
    if(join_pending||state.next_phase==LN_PLAYER_NEXT_COMMITTED)return false;
    next_expected=eof_waiting=false;if(!have_next)return true;
    struct player_slot *s=&slots[audible^1u];
    if(io_owner==s){cancel_next=true;state.next_phase=LN_PLAYER_NEXT_CANCELING;ln_storage_media_cancel(s->generation);}
    else{clear_slot(s);have_next=false;state.next_phase=LN_PLAYER_NEXT_NONE;state.next_error=0;}return true;
}
bool ln_player_skip_prepared_next(uint32_t token){
    struct player_slot *next=&slots[audible^1u];
    if(!token||!have_next||state.next_phase!=LN_PLAYER_NEXT_READY||next->token!=token||
       !next->buffered||!next->rate||next->submitted||io_owner==next||
       join_pending||event_pending||interrupted()||pause_requested||
       (state.phase!=LN_PLAYER_PLAY&&state.phase!=LN_PLAYER_PAUSE&&state.phase!=LN_PLAYER_DRAIN))return false;
    skip_requested=true;next_expected=eof_waiting=false;
    if(io_owner)ln_storage_media_cancel(io_owner->generation);
    return true;
}
bool ln_player_take_transition(struct ln_player_transition *out){if(!out||!event_pending)return false;*out=transition;event_pending=false;return true;}
static void stop_player(bool restarting){
    seek_paused=next_expected=eof_waiting=false;
    if(state.phase==LN_PLAYER_IDLE){if(!restarting)(void)ln_audio_stop();return;}
    state.error=0;stop_requested=true;state.phase=LN_PLAYER_STOPPING;
    if(!(restarting?ln_audio_halt():ln_audio_stop()))state.error=20;
    if(io_owner)ln_storage_media_cancel(io_owner->generation);
}
void ln_player_stop(void){stop_player(false);}
void ln_player_stop_for_restart(void){stop_player(true);}
bool ln_player_pause(bool pause){
    if(skip_requested)return false;
    /* A seek owns a halted ring until cancellation drains and priming ends.
     * Remember the latest intent; start DMA only after fresh PCM is ready. */
    if(!stop_requested&&(seek_requested||state.phase==LN_PLAYER_PRIME)){
        seek_paused=pause;pause_requested=false;return true;
    }
    if(pause&&state.phase==LN_PLAYER_PLAY){pause_requested=true;eof_waiting=false;return true;}
    if(!pause&&state.phase==LN_PLAYER_PLAY&&pause_requested){pause_requested=false;return true;}
    if(!pause&&state.phase==LN_PLAYER_PAUSE){if(!ln_audio_start())return false;eof_waiting=false;state.phase=LN_PLAYER_PLAY;return true;}return false;
}
bool ln_player_toggle_pause(void){
    if(stop_requested||skip_requested)return false;
    if(seek_requested||state.phase==LN_PLAYER_PRIME)return ln_player_pause(!seek_paused);
    if(state.phase==LN_PLAYER_PLAY)return ln_player_pause(!pause_requested);
    if(state.phase==LN_PLAYER_PAUSE)return ln_player_pause(false);
    return false;
}
bool ln_player_seek(uint64_t frame){
    if(skip_requested||event_pending)return false;
    if(state.phase!=LN_PLAYER_PLAY&&state.phase!=LN_PLAYER_PAUSE&&state.phase!=LN_PLAYER_DRAIN)return false;
    if(state.frames&&frame>state.frames)return false;if(!ln_audio_halt()){fail(20);return false;}
    if(!seek_requested)seek_paused=state.phase==LN_PLAYER_PAUSE||pause_requested;
    seek_target=frame;seek_requested=true;next_expected=eof_waiting=false;if(io_owner)ln_storage_media_cancel(io_owner->generation);return true;
}
static bool drain_canceled(void){
    if(!io_owner)return true;int r=ln_storage_media_poll(io_owner->generation,0,0);if(!r)return false;
    ln_decoder_read_drained(&io_owner->decoder);io_owner=0;return true;
}
static void player_advance(void){
    if(state.phase==LN_PLAYER_IDLE)return;
    if(stop_requested){
        if(!drain_canceled())return;clear_slot(&slots[0]);clear_slot(&slots[1]);
        if(state.error)(void)ln_audio_stop();
        state.phase=state.error?LN_PLAYER_ERROR:LN_PLAYER_IDLE;stop_requested=seek_requested=pause_requested=false;
        effect_pending=have_next=cancel_next=join_pending=event_pending=audio_ready=skip_requested=seek_paused=false;state.next_phase=LN_PLAYER_NEXT_NONE;return;
    }
    if(skip_requested){
        if(!drain_canceled())return;
        if(stop_requested)return;
        struct player_slot *next=&slots[audible^1u];
        if(!have_next||state.next_phase!=LN_PLAYER_NEXT_READY||!next->buffered||next->submitted){fail(22);return;}
        if(!ln_audio_halt()){fail(20);return;}
        audio_ready=false;clear_slot(&slots[audible]);audible^=1u;feed=audible;
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
        activate_cache(next);
#endif
        next->generation=generation();next->submitted=0;next->position_base=0;
        consumed=submitted=audible_origin=0;last_consumed=0;
        join_pending=join_gapless=finish_sent=pause_requested=seek_paused=false;
        if(!initialize_audio(next->rate)){fail(11);return;}
        state.phase=LN_PLAYER_PRIME;state.generation=next->generation;state.rate=next->rate;
        state.frames=next->decoder.total_frames;state.decoded=state.rendered=state.underruns=state.error=0;
        transition=(struct ln_player_transition){.token=next->token,.manual=true,.gapless=false,.boundary=0,.underruns=0};
        event_pending=true;skip_requested=have_next=false;
        state.next_phase=LN_PLAYER_NEXT_NONE;state.next_error=0;return;
    }
    if(seek_requested){
        if(!drain_canceled())return;
        if(stop_requested)return;
        clear_slot(&slots[audible^1u]);have_next=cancel_next=join_pending=event_pending=false;state.next_phase=LN_PLAYER_NEXT_NONE;
        struct player_slot *s=&slots[audible];feed=audible;ln_decoder_read_drained(&s->decoder);
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
        s->cache_initial=true;s->cache_current=1u;
        for(uint32_t i=0;i<2u;++i)s->cache[i]=(struct player_cache_window){0};
#endif
        if(!ln_decoder_seek(&s->decoder,seek_target)||!initialize_audio(s->rate)){fail(21);return;}
        s->phase=SLOT_DECODE;s->buffered=0;s->submitted=0;s->position_base=seek_target;audible_origin=consumed;
        state.decoded=state.rendered=0;state.phase=LN_PLAYER_PRIME;seek_requested=pause_requested=false;
        (void)ln_dsp_configure(&s->dsp,&s->dsp.config);return;
    }
    if(cancel_next){
        if(!drain_canceled())return;clear_slot(&slots[audible^1u]);have_next=cancel_next=false;
        state.next_phase=LN_PLAYER_NEXT_NONE;state.next_error=0;
        if(stop_requested||seek_requested)return;
    }
    if(state.phase==LN_PLAYER_ERROR)return;
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
    if(io_owner&&io_owner->phase==SLOT_EOF){
        struct player_slot *finished=io_owner;
        ln_storage_media_cancel(finished->generation);
        if(!drain_canceled())return;
        finished->cache[0].filling=finished->cache[1].filling=false;
    }
#endif
    struct ln_audio_status audio={0};
    if(audio_ready){ln_audio_snapshot(&audio);refresh(&audio);if(audio.fault){fail(12);return;}}
#if defined(LINNET_SOC_PP5022) && defined(LINNET_IMAGE_OS)
    if(slots[audible].cache_pending&&io_owner!=&slots[audible])activate_cache(&slots[audible]);
#endif
    if(state.phase==LN_PLAYER_PAUSE)return;
    if(pause_requested&&!io_owner){pause_requested=false;ln_audio_pause();state.phase=LN_PLAYER_PAUSE;return;}
    if(state.phase==LN_PLAYER_DRAIN){
        if(have_next&&state.next_phase==LN_PLAYER_NEXT_OPENING)advance_next();if(interrupted())return;
        if(audio.queued||ln_time_us()-audio.last_irq_us<2000u)return;
        bool restart=have_next&&state.next_phase!=LN_PLAYER_NEXT_FAILED;
        if(!(restart?ln_audio_halt():ln_audio_stop())){fail(20);return;}audio_ready=false;
        if(have_next&&state.next_phase!=LN_PLAYER_NEXT_FAILED){
            if(state.next_phase!=LN_PLAYER_NEXT_READY)return;
            feed=audible^1u;join_boundary=consumed;join_gapless=false;join_underruns=0;
            join_pending=true;state.next_phase=LN_PLAYER_NEXT_COMMITTED;
            if(!initialize_audio(slots[feed].rate)){fail(11);return;}state.phase=LN_PLAYER_PRIME;
        }else{clear_slot(&slots[audible]);if(have_next)clear_slot(&slots[audible^1u]);have_next=false;state.phase=LN_PLAYER_IDLE;return;}
    }
    struct player_slot *s=&slots[feed];
    if(!audio_ready){
        int r=slot_step(s);if(interrupted())return;if(r<0){fail(3u+(uint32_t)-r);return;}
        if(!s->rate)return;if(!initialize_audio(s->rate)){fail(11);return;}
        state.rate=s->rate;state.frames=s->decoder.total_frames;state.phase=LN_PLAYER_PRIME;
    }
    ln_audio_snapshot(&audio);
    /* Current decoding has priority below the read runway. An already admitted
     * exact read must drain, but its decoder cannot chain another low-PCM read. */
    if(have_next&&!join_pending&&state.next_phase==LN_PLAYER_NEXT_OPENING&&
       (io_owner==&slots[audible^1u]||(!io_owner&&s->phase!=SLOT_EOF&&state.phase==LN_PLAYER_PLAY&&
        audio.queued>=prefetch_frames(audio.rate)))){
        advance_next();if(interrupted())return;
        ln_audio_snapshot(&audio);
        /* Poll the admitted background request, then use otherwise idle CPU
         * to replenish low PCM from the current decoder's cached input.
         * read_media still prevents it from borrowing the pending owner. */
        if(s->phase==SLOT_EOF||audio.queued>=prefetch_frames(audio.rate))return;
    }
    if(s->buffered){if(!submit_slot(s))return;}
    else if(s->phase!=SLOT_EOF&&audio.free_frames>=PLAYER_DECODE_FRAMES){
        int r=slot_step(s);if(interrupted())return;if(r<0){fail(13);return;}if(s->buffered&&!submit_slot(s))return;
    }
    /* Start after the background reserve is available. Next-track I/O still
     * waits for its larger runway; priming need not pay that cost up front. */
    if(state.phase==LN_PLAYER_PRIME&&(s->submitted>=ln_player_background_frames(s->rate)||s->phase==SLOT_EOF)){
        if(submitted==consumed){stop_player(false);return;}
        /* A paused seek fills a fresh ring while muted. Resume starts DMA;
         * priming must not briefly expose audio before returning to pause. */
        if(seek_paused){seek_paused=false;state.phase=LN_PLAYER_PAUSE;return;}
        if(!ln_audio_start()){fail(15);return;}state.phase=LN_PLAYER_PLAY;
    }
    if(s->phase!=SLOT_EOF){eof_waiting=false;return;}
    ln_audio_snapshot(&audio);
    if(!eof_waiting){
        /* Ring capacity bounds scaled to 65,536,000; supported rates bound
         * the remainder product to 95,999,000. Preserve exact microseconds
         * without a 64-bit division runtime on this freestanding target. */
        uint32_t scaled=audio.queued*1000u;
        uint32_t runway=audio.rate?(scaled/audio.rate)*1000u+
            ((scaled%audio.rate)*1000u)/audio.rate:0;
        if(runway>8000000u)runway=8000000u;
        eof_deadline=ln_time_us()+runway;eof_waiting=true;
    }
    bool runway=audio.queued&&(int32_t)(ln_time_us()-eof_deadline)<0;
    if(have_next&&!join_pending&&state.next_phase==LN_PLAYER_NEXT_OPENING){
        if(io_owner==&slots[audible^1u]||(!io_owner&&state.phase==LN_PLAYER_PLAY&&runway)){advance_next();return;}
    }
    if(have_next&&!join_pending&&state.next_phase==LN_PLAYER_NEXT_READY&&slots[audible^1u].rate==s->rate){
        struct player_slot *next=&slots[audible^1u];ln_audio_snapshot(&audio);if(audio.free_frames<next->buffered)return;
        join_boundary=submitted;join_gapless=audio.queued>0&&!finish_sent;join_underruns=audio.underruns;
        feed=audible^1u;join_pending=true;state.next_phase=LN_PLAYER_NEXT_COMMITTED;
        (void)submit_slot(next);return;
    }
    /* Metadata/history may still be arriving for a track shorter than the
     * usual runway. Waiting is bounded by audio already queued, never silence. */
    if(next_expected&&!have_next&&!join_pending&&runway)return;
    if(!finish_sent){ln_audio_finish();finish_sent=true;}state.phase=LN_PLAYER_DRAIN;
}
void ln_player_step(void){
    if(stepping)return;stepping=true;
    if(effect_pending&&!stop_requested&&!seek_requested&&!skip_requested&&!pause_requested){
        uint32_t count=raw_head-effect_cursor;if(count>PLAYER_DECODE_FRAMES)count=PLAYER_DECODE_FRAMES;
        for(uint32_t i=0;i<count;i++){
            uint32_t at=(effect_cursor+i)&(LINNET_AUDIO_RING_FRAMES-1u);
            __builtin_memcpy(EFFECT_PCM+2*i,RAW_PCM+2*at,4);
        }
        process_pcm(&slots[audible],EFFECT_PCM,count);
        (void)ln_audio_rewrite(effect_cursor,EFFECT_PCM,count);
        effect_cursor+=count;effect_pending=effect_cursor!=raw_head;
    }else player_advance();
    stepping=false;
}
bool ln_player_busy(void){return state.phase!=LN_PLAYER_IDLE&&state.phase!=LN_PLAYER_ERROR;}
uint32_t ln_player_deadline(uint32_t now){
    if(effect_pending)return now;
    /* An admitted read for the feeding decoder owns its input buffer until
     * storage completes. Another player turn cannot produce PCM from it.
     * Storage keeps runnable FAT/completion work awake and owns the bounded
     * disk wait. A next-track read still permits the current decoder to use
     * its cached input, so do not defer that independent work. */
    if(io_owner&&(io_owner==&slots[feed]||interrupted()))return now+200000u;
    if(state.phase==LN_PLAYER_OPEN||state.phase==LN_PLAYER_HEADER||state.phase==LN_PLAYER_PRIME||io_owner)return now;
    /* Decode and drain are separate bounded steps. Sleeping between them
     * caps MP3 production below44.1kHz even before accounting for compute. */
    if(stop_requested||seek_requested||cancel_next||pause_requested||skip_requested||
       (state.phase==LN_PLAYER_PLAY&&ln_audio_capacity()>=PLAYER_DECODE_FRAMES))return now;
    /* A settled pause has no decode work. Input IRQs and other service
     * deadlines still wake the executive; preserve the watchdog idle ceiling. */
    if(state.phase==LN_PLAYER_PAUSE)return now+200000u;
    return ln_player_busy()?now+10000u:now+200000u;
}
void ln_player_snapshot(struct ln_player_status *out){if(out)*out=state;}
uint64_t ln_player_position(void){
    uint64_t rendered=consumed-audible_origin;if(rendered>slots[audible].submitted)rendered=slots[audible].submitted;
    return slots[audible].position_base+rendered;
}
