#include "services/audio/vorbis/vorbis.h"
#include "third_party/vorbis/codec_internal.h"
void ln_vorbis_pool_bind(struct ln_vorbis*);
void ln_vorbis_pool_reset(struct ln_vorbis*);
void ln_vorbis_scratch_clear(struct ln_vorbis*);
#if defined(__arm__)
int ln_vorbis_guard(uintptr_t*,int(*)(struct ln_vorbis*),struct ln_vorbis*);
#endif
static int guarded(struct ln_vorbis*s,int(*fn)(struct ln_vorbis*))
{
    ln_vorbis_pool_bind(s);int result;
#if defined(__arm__)
    result=ln_vorbis_guard(s->jump,fn,s);
#else
    result=setjmp(s->jump)?LN_PCM_UNSUPPORTED:fn(s);
#endif
    if(result==LN_PCM_UNSUPPORTED&&s->error){ln_vorbis_pool_reset(s);return result;}
    ln_vorbis_scratch_clear(s);return result;
}
static uint32_t le(const uint8_t*p){return p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static int fail(struct ln_vorbis*s,int e){return s->error=e;}
static uint32_t checksum(const uint8_t*p,uint32_t n)
{uint32_t v=0;for(uint32_t i=0;i<n;++i){v^=(uint32_t)((i>=22u&&i<26u)?0:p[i])<<24;for(uint32_t j=0;j<8;++j)v=(v<<1)^((v&0x80000000u)?0x04c11db7u:0);}return v;}
static int packet_step(struct ln_vorbis*s)
{
    if(s->page_ready){
        while(s->segment<s->segments){uint32_t n=s->page[27u+s->segment++];
            if(n>sizeof(s->packet)-s->packet_size)return fail(s,LN_PCM_UNSUPPORTED);
            for(uint32_t i=0;i<n;++i)s->packet[s->packet_size+i]=s->page[s->body+i];s->body+=n;s->packet_size+=n;
            if(n<255u){bool last=true;for(uint32_t i=s->segment;i<s->segments;++i)if(s->page[27u+i]<255u)last=false;
                s->op=(ogg_packet){s->packet,(long)s->packet_size,s->packets==0,last&&s->page_eos,
                    last?(int64_t)s->page_granule:-1,(int64_t)s->packets++};
                s->packet_size=0;return 1;}
        }
        s->page_ready=false;s->page_have=0;s->page_need=27;
        if(s->page_eos){if(s->packet_size||s->cursor!=s->file_size)return fail(s,LN_PCM_UNSUPPORTED);
            /* Granules may include a nonzero origin. Publish the zero-based
             * total only after every EOS packet and its PCM have drained. */
            s->total_frames=s->frame;s->ended=true;return LN_PCM_EOF;}
    }
    if(s->cursor==s->file_size)return fail(s,LN_PCM_FORMAT);
    if(s->page_need>s->file_size-s->cursor+s->page_have)return fail(s,LN_PCM_FORMAT);
    uint32_t n=s->page_need-s->page_have;if(n>4096u)n=4096u;
    if(n){int result=s->read(s->context,s->cursor,s->page+s->page_have,n);s->pending=result==0;
        if(result<0)return fail(s,LN_PCM_IO);if(!result)return 0;s->page_have+=n;s->cursor+=n;if(s->page_have<s->page_need)return 0;}
    if(s->page_need==27u){
        if(le(s->page)!=0x5367674fu||s->page[4]||(s->page[5]&~7u))return fail(s,LN_PCM_FORMAT);
        uint32_t serial=le(s->page+14),sequence=le(s->page+18);
        if(!s->packets){if(!(s->page[5]&2u)||sequence)return fail(s,LN_PCM_FORMAT);s->serial=serial;}
        else if(serial!=s->serial||(s->page[5]&2u)||sequence!=s->sequence)return fail(s,LN_PCM_UNSUPPORTED);
        s->sequence=sequence+1u;s->segments=s->page[26];
        if(!s->segments)return fail(s,LN_PCM_UNSUPPORTED);
        if(((s->page[5]&1u)!=0)!=(s->packet_size!=0))return fail(s,LN_PCM_FORMAT);
        s->page_need=27u+s->segments;return 0;
    }
    if(s->page_need==27u+s->segments){uint32_t bytes=0;for(uint32_t i=0;i<s->segments;++i)bytes+=s->page[27u+i];
        if(!bytes)return fail(s,LN_PCM_FORMAT);s->page_need+=bytes;return 0;}
    if(checksum(s->page,s->page_need)!=le(s->page+22))return fail(s,LN_PCM_FORMAT);
    s->page_granule=le(s->page+6)|((uint64_t)le(s->page+10)<<32);s->page_eos=(s->page[5]&4u)!=0;
    if(s->page_granule!=UINT64_MAX&&s->page_granule>INT64_MAX)return fail(s,LN_PCM_FORMAT);
    if(s->page_eos&&s->page_granule==UINT64_MAX)return fail(s,LN_PCM_FORMAT);
    s->page_ready=true;s->segment=0;s->body=27u+s->segments;return 0;
}
void ln_vorbis_init(struct ln_vorbis*s,ln_pcm_read_fn read,void*context,uint64_t bytes)
{if(!s)return;*s=(struct ln_vorbis){0};s->read=read;s->context=context;s->file_size=bytes;s->page_need=27;ln_vorbis_pool_reset(s);}
static int header(struct ln_vorbis*s)
{
    if(!s->headers)vorbis_info_init(&s->info);
    uint8_t expected=s->headers==0?1u:s->headers==1?3u:5u;
    if(s->op.bytes<7||s->packet[0]!=expected||vorbis_synthesis_headerin(&s->info,&s->op))return LN_PCM_FORMAT;
    if(s->info.channels<1||s->info.channels>2||s->info.rate<8000||s->info.rate>96000)return LN_PCM_UNSUPPORTED;
    codec_setup_info*c=s->info.codec_setup;if(c->blocksizes[1]>8192)return LN_PCM_UNSUPPORTED;
    ++s->headers;
    if(s->headers==3){if(vorbis_synthesis_init(&s->dsp,&s->info)||vorbis_block_init(&s->dsp,&s->block))return LN_PCM_FORMAT;
        s->sample_rate=(uint32_t)s->info.rate;s->channels=(uint32_t)s->info.channels;s->opened=true;}
    return 1;
}
int ln_vorbis_open_step(struct ln_vorbis*s)
{
    if(!s||!s->read)return LN_PCM_ARGUMENT;if(s->error)return s->error;if(s->opened)return 1;
    int result=packet_step(s);if(result!=1)return result==LN_PCM_EOF?fail(s,LN_PCM_FORMAT):result;
    result=guarded(s,header);if(result<0)return fail(s,result);return s->opened?1:0;
}
static int synthesize(struct ln_vorbis*s)
{return vorbis_synthesis(&s->block,&s->op)||vorbis_synthesis_blockin(&s->dsp,&s->block)?LN_PCM_FORMAT:1;}
int ln_vorbis_decode(struct ln_vorbis*s,int16_t*out,uint32_t capacity,uint32_t*frames)
{
    if(!s||!out||!frames||!capacity)return LN_PCM_ARGUMENT;*frames=0;if(s->error)return s->error;if(!s->opened){int r=ln_vorbis_open_step(s);return r<0?r:0;}
    int32_t**pcm;int available=vorbis_synthesis_pcmout(&s->dsp,&pcm);
    if(available>0){uint32_t n=(uint32_t)available;if(n>capacity)n=capacity;
        if(s->frame<s->discard_to){uint64_t remaining=s->discard_to-s->frame;if(remaining<n)n=(uint32_t)remaining;
            vorbis_synthesis_read(&s->dsp,(int)n);s->frame+=n;return 0;}
        for(uint32_t i=0;i<n;++i)for(uint32_t ch=0;ch<2;++ch){int32_t raw=pcm[s->channels==1?0:ch][i];
            int32_t value=raw>=0?raw/512:-(int32_t)(((uint32_t)(-(int64_t)raw)+511u)/512u);
            if(value>32767)value=32767;if(value<-32768)value=-32768;out[2u*i+ch]=(int16_t)value;}
        vorbis_synthesis_read(&s->dsp,(int)n);s->frame+=n;*frames=n;return 1;}
    if(s->ended)return s->frame<s->discard_to?fail(s,LN_PCM_FORMAT):LN_PCM_EOF;
    int result=packet_step(s);if(result!=1)return result==LN_PCM_EOF&&s->frame<s->discard_to?fail(s,LN_PCM_FORMAT):result;
    result=guarded(s,synthesize);return result<0?fail(s,result):0;
}
void ln_vorbis_close(struct ln_vorbis*s){if(!s)return;ln_vorbis_pool_reset(s);s->opened=false;s->ended=true;}
bool ln_vorbis_seek(struct ln_vorbis*s,uint64_t frame)
{if(!s||s->pending||(s->total_frames&&frame>s->total_frames))return false;ln_pcm_read_fn read=s->read;void*context=s->context;uint64_t bytes=s->file_size;ln_vorbis_init(s,read,context,bytes);s->discard_to=frame;return true;}
