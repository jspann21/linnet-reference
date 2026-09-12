#include "mp3.h"
#include "third_party/libmad/codeclib.h"
#include "hal/pp5020/platform.h"
#if !defined(LINNET_PROFILE_RELEASE)
static struct ln_mp3_timing timing;
static void timing_add(uint32_t *value,uint32_t amount)
{*value=amount>UINT32_MAX-*value?UINT32_MAX:*value+amount;}
static void timing_span(uint32_t *calls,uint32_t *total,uint32_t *maximum,uint32_t started)
{uint32_t elapsed=ln_time_us()-started;timing_add(calls,1);timing_add(total,elapsed);if(elapsed>*maximum)*maximum=elapsed;}
void ln_mp3_timing_snapshot(struct ln_mp3_timing *out){if(out)*out=timing;}
#define MP3_TIME_BEGIN(name) uint32_t name=ln_time_us()
#define MP3_TIME_END(name,calls,total,maximum) timing_span(&(calls),&(total),&(maximum),name)
#else
#define MP3_TIME_BEGIN(name)
#define MP3_TIME_END(name,calls,total,maximum)
#endif
static int fail(struct ln_mp3 *d,int error){d->error=error;return error;}
#define RESYNC_BYTES 65536u
#define RESYNC_ERRORS 65536u
void ln_mp3_init(struct ln_mp3 *d,ln_mp3_read_fn read,void *context,uint64_t size)
{
    ln_mad_set(d,0,sizeof(*d));d->read=read;d->context=context;d->file_size=size;
    d->stream.main_data=&d->reservoir;d->frame.sbsample=&d->subband;
    d->frame.sbsample_prev=&d->subband;d->frame.overlap=&d->overlap;
    mad_stream_init(&d->stream);mad_frame_init(&d->frame);mad_synth_init(&d->synth);
    d->need_input=true;
}
bool ln_mp3_seek(struct ln_mp3 *d,uint64_t frame)
{
    if(!d||!d->read||d->pending||(d->gapless&&frame>d->total_frames))return false;
    ln_mp3_read_fn read=d->read;void *context=d->context;uint64_t size=d->file_size;
    ln_mp3_init(d,read,context,size);d->seek_target=frame;d->seeking=frame!=0;return true;
}
static int finish(struct ln_mp3 *d)
{
    if(!d->compressed_frames)return fail(d,LN_MP3_FORMAT);
    if(d->gapless&&d->decoded_frames!=d->total_frames){
        uint32_t samples=(d->frame.header.flags&MAD_FLAG_LSF_EXT)?576u:1152u;
        /* Some tagged files have lost their final MPEG frame. Only accept
         * physical EOF with exactly that one frame absent, after all valid
         * PCM has drained. Earlier resynchronization or a larger shortage
         * still means corruption. Publish the actual length; never invent
         * samples or abort the player's already queued audible tail. */
        if(!d->eof||!d->decoded_frames||d->trim_remaining||
           d->pcm_cursor!=d->synth.pcm.length||d->decoded_frames>=d->total_frames||
           d->recoveries!=d->consecutive_recoveries||
           d->total_frames+d->lead_trim+d->tail_trim!=((uint64_t)d->compressed_frames+1u)*samples||
           d->decoded_frames+d->lead_trim!=(uint64_t)d->compressed_frames*samples)
            return fail(d,LN_MP3_FORMAT);
        d->total_frames=d->decoded_frames;
    }
    if(d->seeking)return fail(d,LN_MP3_ARGUMENT);
    return LN_MP3_EOF;
}
static int read_step(struct ln_mp3 *d,uint64_t offset,uint8_t *buffer,uint32_t count)
{
    if(offset>d->file_size||count>d->file_size-offset)return fail(d,LN_MP3_FORMAT);
    int r=d->read(d->context,offset,buffer,count);d->pending=r==0;
    return r<0?fail(d,LN_MP3_IO):r;
}
static int initialize(struct ln_mp3 *d)
{
    if(d->file_size<10)return fail(d,LN_MP3_FORMAT);
    int r=read_step(d,0,d->input,10);if(r!=1)return r;
    uint8_t *b=d->input;
    if(b[0]=='I'&&b[1]=='D'&&b[2]=='3'){
        if(b[3]<2||b[3]>4||b[4]==255||(b[6]|b[7]|b[8]|b[9])&128)return fail(d,LN_MP3_FORMAT);
        uint32_t size=((uint32_t)b[6]<<21)|((uint32_t)b[7]<<14)|((uint32_t)b[8]<<7)|b[9];
        d->read_offset=10u+(uint64_t)size+((b[3]==4&&(b[5]&16))?10u:0u);
        if(d->read_offset>d->file_size)return fail(d,LN_MP3_FORMAT);
    }else{d->valid=10;d->read_offset=10;d->unsynced_bytes=10;}
    d->initialized=true;return 0;
}
static int refill(struct ln_mp3 *d)
{
    if(!d->refilling){
        uint32_t consumed=0;
        if(d->stream.next_frame){
            if(d->stream.next_frame<d->input||d->stream.next_frame>d->input+d->valid)return fail(d,LN_MP3_FORMAT);
            consumed=(uint32_t)(d->stream.next_frame-d->input);
        }
        d->retained=d->valid-consumed;
        ln_mad_move(d->input,d->input+consumed,d->retained);
        d->read_bytes=8192u-d->retained;if(d->read_bytes>4096)d->read_bytes=4096;
        /* Count admitted new bytes, not repeated polls or retained overlap.
         * Bound bad-file reads independently of libmad's resync progress. */
        if(d->unsynced_bytes>=RESYNC_BYTES)return fail(d,LN_MP3_FORMAT);
        if(d->read_bytes>RESYNC_BYTES-d->unsynced_bytes)d->read_bytes=RESYNC_BYTES-d->unsynced_bytes;
        if(d->read_bytes>d->file_size-d->read_offset)d->read_bytes=(uint32_t)(d->file_size-d->read_offset);
        if(!d->read_bytes&&d->read_offset!=d->file_size)return fail(d,LN_MP3_UNSUPPORTED);
        d->refilling=true;
    }
    if(d->read_bytes){
        int r=read_step(d,d->read_offset,d->input+d->retained,d->read_bytes);if(r!=1)return r;
        d->read_offset+=d->read_bytes;
        d->unsynced_bytes+=d->read_bytes;
    }
    d->valid=d->retained+d->read_bytes;d->eof=d->read_offset==d->file_size;
    if(d->eof)ln_mad_set(d->input+d->valid,0,MAD_BUFFER_GUARD);
    mad_stream_buffer(&d->stream,d->input,d->valid+(d->eof?MAD_BUFFER_GUARD:0));
    d->refilling=false;d->need_input=false;return 0;
}
static int16_t pcm16(mad_fixed_t value)
{
    if(value>=MAD_F_ONE)return 32767;
    if(value<=-MAD_F_ONE)return -32768;
    return (int16_t)(value>>(MAD_F_FRACBITS-15));
}
static uint32_t be32(const uint8_t *b)
{return ((uint32_t)b[0]<<24)|((uint32_t)b[1]<<16)|(b[2]<<8)|b[3];}
static bool tag(const uint8_t *b,const char *s)
{return b[0]==(uint8_t)s[0]&&b[1]==(uint8_t)s[1]&&b[2]==(uint8_t)s[2]&&b[3]==(uint8_t)s[3];}
/* The Xing frame is metadata and must not enter the synthesis filter. LAME
 * stores encoder delay/padding in packed 12-bit fields. As in the known-good
 * Rockbox mpa decoder, Layer III synthesis adds 529 leading samples and reduces
 * the trailing trim by 529. Bound every optional field by the actual frame. */
static int first_frame(struct ln_mp3 *d)
{
    const uint8_t *b=d->stream.this_frame,*end=d->stream.next_frame;
    if(!b||!end||b<d->input||end>d->input+d->valid||end<b)return -1;
    uint32_t bytes=(uint32_t)(end-b);
    bool low=(d->frame.header.flags&MAD_FLAG_LSF_EXT)!=0;
    uint32_t offset=4u+(low?(d->channels==1?9u:17u):(d->channels==1?17u:32u));
    if(bytes<offset+8u||(!tag(b+offset,"Xing")&&!tag(b+offset,"Info")))return 0;
    uint32_t flags=be32(b+offset+4),cursor=offset+8,count=0;
    if(flags&~15u)return -1;
    if(flags&1u){if(bytes-cursor<4)return -1;count=be32(b+cursor);cursor+=4;}
    if(flags&2u){if(bytes-cursor<4)return -1;uint32_t length=be32(b+cursor);if(length>d->file_size)return -1;cursor+=4;}
    if(flags&4u){if(bytes-cursor<100)return -1;cursor+=100;}
    if(flags&8u){if(bytes-cursor<4)return -1;cursor+=4;}
    if(!count||count>(d->file_size>>2)||bytes-cursor<24)return 1;
    if(!tag(b+cursor,"LAME")&&!tag(b+cursor,"Lavc")&&!tag(b+cursor,"Lavf"))return 1;
    uint32_t delay=((uint32_t)b[cursor+21]<<4)|(b[cursor+22]>>4);
    uint32_t padding=((uint32_t)(b[cursor+22]&15)<<8)|b[cursor+23];
    uint64_t samples=(uint64_t)count*(low?576u:1152u);
    if(delay>2880||padding<529||padding>2304||samples<=delay+padding)return 1;
    d->lead_trim=delay+529u;d->tail_trim=padding-529u;d->trim_remaining=d->lead_trim;
    d->total_frames=samples-delay-padding;d->gapless=true;return 1;
}
/* Drain at most one synthesized MPEG frame, bounded by caller capacity.
 * Sharing this path lets a newly synthesized frame reach the PCM ring without
 * another executive round trip; no second MPEG frame is decoded here. */
static int drain_pcm(struct ln_mp3 *d,int16_t *output,uint32_t capacity,uint32_t *frames)
{
        if(d->seeking){
            uint32_t discard=d->synth.pcm.length-d->pcm_cursor;
            if(discard>d->seek_target-d->decoded_frames)discard=(uint32_t)(d->seek_target-d->decoded_frames);
            d->pcm_cursor+=discard;d->decoded_frames+=discard;
            if(d->decoded_frames==d->seek_target)d->seeking=false;
            return 0;
        }
        MP3_TIME_BEGIN(pcm_started);
        uint32_t count=d->synth.pcm.length-d->pcm_cursor;if(count>capacity)count=capacity;
        const mad_fixed_t *left=d->synth.pcm.samples[0]+d->pcm_cursor;
        int16_t *out=output,*end=output+count*2u;
        if(d->channels==1){
            while(out!=end){int16_t sample=pcm16(*left++);*out++=sample;*out++=sample;}
        }else{
            const mad_fixed_t *right=d->synth.pcm.samples[1]+d->pcm_cursor;
            while(out!=end){*out++=pcm16(*left++);*out++=pcm16(*right++);}
        }
#if !defined(LINNET_PROFILE_RELEASE)
        timing_add(&timing.pcm_frames,count);
#endif
        MP3_TIME_END(pcm_started,timing.pcm_calls,timing.pcm_us,timing.pcm_max_us);
        d->pcm_cursor+=count;d->decoded_frames+=count;*frames=count;return 1;
}
int ln_mp3_decode(struct ln_mp3 *d,int16_t *output,uint32_t capacity,uint32_t *frames)
{
    if(frames)*frames=0;
    if(!d||!d->read||!output||!capacity||!frames)return LN_MP3_ARGUMENT;
    if(d->error)return d->error;
    if(!d->initialized)return initialize(d);
    if(d->gapless&&d->decoded_frames==d->total_frames)return finish(d);
    if(d->pcm_cursor<d->synth.pcm.length)return drain_pcm(d,output,capacity,frames);
    if(d->need_input)return refill(d);
    /* Keep four full MPEG-1 frames of ordinary decoding before the target
     * to rebuild both IMDCT overlap and synthesis history. Scanned frames
     * retain the bit reservoir, CRC checks and exact trimmed sample count. */
    bool scan=d->seeking&&d->first_frame_checked&&
        d->seek_target-d->decoded_frames>5u*1152u;
    d->stream.options=scan?MAD_OPTION_SCAN:0;
    MP3_TIME_BEGIN(frame_started);
    int frame_result=mad_frame_decode(&d->frame,&d->stream);
    MP3_TIME_END(frame_started,timing.frame_calls,timing.frame_us,timing.frame_max_us);
    if(frame_result){
        if(d->stream.error==MAD_ERROR_BUFLEN){
            if(d->eof)return finish(d);
            d->need_input=true;return 0;
        }
        if(!MAD_RECOVERABLE(d->stream.error))return fail(d,LN_MP3_FORMAT);
        /* EOF guard is not media data; no attempt to resynchronize beyond it. */
        if(d->eof&&d->stream.this_frame>=d->input+d->valid)
            return finish(d);
        d->recoveries++;
        if(++d->consecutive_recoveries>=RESYNC_ERRORS)return fail(d,LN_MP3_FORMAT);
        return 0;
    }
    if(d->frame.header.layer!=MAD_LAYER_III)return fail(d,LN_MP3_UNSUPPORTED);
    uint32_t rate=d->frame.header.samplerate,channels=MAD_NCHANNELS(&d->frame.header);
    if(d->rate&&(d->rate!=rate||d->channels!=channels))return fail(d,LN_MP3_UNSUPPORTED);
    d->unsynced_bytes=d->consecutive_recoveries=0;
    d->rate=rate;d->channels=channels;
    if(!d->first_frame_checked){
        d->first_frame_checked=true;int metadata=first_frame(d);
        if(metadata<0)return fail(d,LN_MP3_FORMAT);
        if(metadata)return 0;
    }
    if(scan){
        uint32_t samples=32u*MAD_NSBSAMPLES(&d->frame.header),skip=d->trim_remaining;
        if(skip>samples)skip=samples;
        d->trim_remaining-=skip;samples-=skip;
        if(d->gapless&&samples>d->total_frames-d->decoded_frames)
            samples=(uint32_t)(d->total_frames-d->decoded_frames);
        d->decoded_frames+=samples;
        d->synth.phase=(d->synth.phase+MAD_NSBSAMPLES(&d->frame.header))%16u;
        d->synth.pcm.length=0;d->pcm_cursor=0;++d->compressed_frames;return 0;
    }
    MP3_TIME_BEGIN(synth_started);
    mad_synth_frame(&d->synth,&d->frame);
    MP3_TIME_END(synth_started,timing.synth_calls,timing.synth_us,timing.synth_max_us);
    d->pcm_cursor=0;d->compressed_frames++;
    if(d->trim_remaining){
        uint32_t skip=d->trim_remaining;if(skip>d->synth.pcm.length)skip=d->synth.pcm.length;
        d->pcm_cursor=skip;d->trim_remaining-=skip;
    }
    if(d->gapless){
        uint64_t remaining=d->total_frames-d->decoded_frames;
        if(d->synth.pcm.length-d->pcm_cursor>remaining)d->synth.pcm.length=(uint16_t)(d->pcm_cursor+(uint32_t)remaining);
    }
    return d->pcm_cursor<d->synth.pcm.length?drain_pcm(d,output,capacity,frames):0;
}
