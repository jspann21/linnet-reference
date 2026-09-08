#include "m4a.h"
static int fail(struct ln_aac_m4a *d,int error){d->error=error;return error;}
static int demux_result(int result)
{if(result==LN_ALAC_UNSUPPORTED)return LN_AAC_UNSUPPORTED;if(result==LN_ALAC_ARGUMENT)return LN_AAC_ARGUMENT;return result;}
static uint32_t be32(const uint8_t *b){return (uint32_t)b[0]<<24|(uint32_t)b[1]<<16|(uint32_t)b[2]<<8|b[3];}
#define TAG(a,b,c,e) ((uint32_t)(a)<<24|(uint32_t)(b)<<16|(uint32_t)(c)<<8|(uint32_t)(e))
static bool text_is(const uint8_t *p,uint32_t n,const char *s){
    uint32_t i=0;while(i<n&&s[i]&&p[i]==(uint8_t)s[i])++i;return i==n&&!s[i];
}
static bool smpb(struct ln_aac_m4a *d,const uint8_t *p,uint32_t n){
    uint64_t values[4];uint32_t i=0;
    for(uint32_t field=0;field<4;++field){
        while(i<n&&p[i]==' ')++i;
        uint64_t value=0;uint32_t digits=0;
        while(i<n&&p[i]!=' '){
            uint32_t c=p[i++],v=c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:16;
            if(v>15||digits++==16)return false;value=(value<<4)|v;
        }
        if(!digits)return false;values[field]=value;
    }
    if(values[0]||values[1]>UINT32_MAX||values[2]>UINT32_MAX||!values[3])return false;
    d->entry_lead=(uint32_t)values[1];d->entry_tail=(uint32_t)values[2];d->entry_frames=values[3];return true;
}
static int meta_read(struct ln_aac_m4a *d,uint64_t offset,uint32_t bytes){
    if(offset>d->container.file_size||bytes>d->container.file_size-offset)return fail(d,LN_AAC_FORMAT);
    int r=d->container.read(d->container.context,offset,d->meta_buffer,bytes);
    d->pending=r==0;return r<0?fail(d,LN_AAC_IO):r;
}
/* Optional iTunes gapless metadata. Walk only its declared atom hierarchy,
 * one <=256-byte exact read per call; never scan media bytes for a string. */
static int metadata_step(struct ln_aac_m4a *d){
    if(d->meta_done)return 1;
    uint64_t end=d->meta_depth?d->meta_ends[d->meta_depth-1]:d->container.file_size;
    if(!d->meta_phase){
        if(d->meta_cursor==end){
            if(!d->meta_depth){d->meta_done=true;return 1;}
            if(d->meta_parents[d->meta_depth-1]==TAG('-','-','-','-')&&d->tag_mean&&d->tag_name){
                if(!d->tag_data||!d->tag_valid||d->tag_seen)return fail(d,LN_AAC_FORMAT);
                d->tag_seen=true;d->tag_lead=d->entry_lead;d->tag_tail=d->entry_tail;d->tag_frames=d->entry_frames;
            }
            --d->meta_depth;return 0;
        }
        if(d->meta_cursor>end||end-d->meta_cursor<8||d->meta_atoms>=4096)return fail(d,LN_AAC_FORMAT);
        int r=meta_read(d,d->meta_cursor,8);if(r!=1)return r;
        ++d->meta_atoms;uint32_t size=be32(d->meta_buffer);d->meta_type=be32(d->meta_buffer+4);
        d->meta_cursor+=8;
        if(size==1){d->meta_phase=1;return 0;}
        if(size&&size<8)return fail(d,LN_AAC_FORMAT);
        if(size&&(uint64_t)size-8>end-d->meta_cursor)return fail(d,LN_AAC_FORMAT);
        d->meta_end=size?d->meta_cursor+(uint64_t)size-8:end;
        if(d->meta_end>end)return fail(d,LN_AAC_FORMAT);
        d->meta_phase=2;return 0;
    }
    if(d->meta_phase==1){
        if(end-d->meta_cursor<8)return fail(d,LN_AAC_FORMAT);
        int r=meta_read(d,d->meta_cursor,8);if(r!=1)return r;
        uint64_t size=(uint64_t)be32(d->meta_buffer)<<32|be32(d->meta_buffer+4);
        if(size<16||size>end-(d->meta_cursor-8))return fail(d,LN_AAC_FORMAT);
        d->meta_end=d->meta_cursor-8+size;d->meta_cursor+=8;d->meta_phase=2;return 0;
    }
    uint32_t type=d->meta_type,parent=d->meta_depth?d->meta_parents[d->meta_depth-1]:0;
    bool descend=(!parent&&type==TAG('m','o','o','v'))||
        (parent==TAG('m','o','o','v')&&type==TAG('u','d','t','a'))||
        (parent==TAG('u','d','t','a')&&type==TAG('m','e','t','a'))||
        (parent==TAG('m','e','t','a')&&type==TAG('i','l','s','t'))||
        (parent==TAG('i','l','s','t')&&type==TAG('-','-','-','-'));
    if(descend){
        if(d->meta_depth==5)return fail(d,LN_AAC_FORMAT);
        if(type==TAG('m','e','t','a')){
            if(d->meta_end-d->meta_cursor<4)return fail(d,LN_AAC_FORMAT);
            int r=meta_read(d,d->meta_cursor,4);if(r!=1)return r;
            if(be32(d->meta_buffer))return fail(d,LN_AAC_UNSUPPORTED);d->meta_cursor+=4;
        }
        if(type==TAG('-','-','-','-'))d->tag_mean=d->tag_name=d->tag_data=d->tag_valid=false;
        d->meta_parents[d->meta_depth]=type;d->meta_ends[d->meta_depth++]=d->meta_end;
    }else{
        uint64_t bytes=d->meta_end-d->meta_cursor;
        if(parent==TAG('-','-','-','-')&&(type==TAG('m','e','a','n')||type==TAG('n','a','m','e')||type==TAG('d','a','t','a'))){
            if(bytes<=sizeof d->meta_buffer&&bytes>=4){
                int r=meta_read(d,d->meta_cursor,(uint32_t)bytes);if(r!=1)return r;
                if(type==TAG('m','e','a','n'))d->tag_mean=!be32(d->meta_buffer)&&text_is(d->meta_buffer+4,(uint32_t)bytes-4,"com.apple.iTunes");
                else if(type==TAG('n','a','m','e'))d->tag_name=!be32(d->meta_buffer)&&text_is(d->meta_buffer+4,(uint32_t)bytes-4,"iTunSMPB");
                else {d->tag_data=true;d->tag_valid=bytes>=8&&be32(d->meta_buffer)==1&&smpb(d,d->meta_buffer+8,(uint32_t)bytes-8);}
            }
        }
        d->meta_cursor=d->meta_end;
    }
    d->meta_phase=0;return 0;
}
/* The outer decoder owns exactly one outstanding immutable read. Keep its
 * identity while a larger, bounded source read fills one of two windows. */
static int cached_read(void *context,uint64_t offset,uint8_t *buffer,uint32_t bytes)
{
    struct ln_aac_m4a *d=context;uint64_t size=d->container.file_size;
    if(!bytes||bytes>16384||offset>size||bytes>size-offset)return -1;
    uint32_t slot=d->cache_filling;
    if(d->cache_pending){
        if(offset!=d->cache_request_offset||bytes!=d->cache_request_bytes||buffer!=d->cache_request_buffer)return -1;
    }else{
        for(uint32_t i=0;i<2;i++){
            if(offset>=d->cache_offset[i]&&offset-d->cache_offset[i]<=d->cache_bytes[i]&&
               bytes<=d->cache_bytes[i]-(uint32_t)(offset-d->cache_offset[i])){
                uint32_t at=(uint32_t)(offset-d->cache_offset[i]);
                for(uint32_t j=0;j<bytes;j++)buffer[j]=d->read_cache[i][at+j];
                d->cache_victim=(uint8_t)(i^1u);return 1;
            }
        }
        slot=d->cache_victim;d->cache_filling=(uint8_t)slot;
        d->cache_offset[slot]=offset;d->cache_bytes[slot]=0;
        d->cache_request_offset=offset;d->cache_request_bytes=bytes;d->cache_request_buffer=buffer;
    }
    uint32_t fill=size-d->cache_offset[slot]>16384?16384:(uint32_t)(size-d->cache_offset[slot]);
    int result=d->source_read(d->source_context,d->cache_offset[slot],d->read_cache[slot],fill);
    d->cache_pending=result==0;if(result!=1)return result;
    d->cache_bytes[slot]=fill;d->cache_victim=(uint8_t)(slot^1u);
    for(uint32_t j=0;j<bytes;j++)buffer[j]=d->read_cache[slot][j];
    return 1;
}
void ln_aac_m4a_init(struct ln_aac_m4a *d,ln_aac_read_fn read,void *context,uint64_t size)
{
    uint8_t *b=(uint8_t *)d;for(uint32_t i=0;i<sizeof(*d);i++)b[i]=0;
    d->source_read=read;d->source_context=context;
    ln_m4a_init(&d->container,cached_read,d,size);
}
int ln_aac_m4a_open_step(struct ln_aac_m4a *d)
{
    if(!d)return LN_AAC_ARGUMENT;if(d->error)return d->error;if(d->opened)return 1;
    int r=ln_m4a_open_step(&d->container);d->pending=d->container.pending;
    if(r!=1)return r<0?fail(d,demux_result(r)):r;
    if(d->container.codec!=17)return fail(d,LN_AAC_UNSUPPORTED);
    r=metadata_step(d);if(r!=1)return r;
    for(uint32_t i=0;i<d->container.time_count;i++){
        uint32_t duration=d->container.times[i].delta;
        if(!duration||duration>1024||(duration!=1024&&(i+1u!=d->container.time_count||d->container.times[i].count!=1)))
            return fail(d,LN_AAC_UNSUPPORTED);
    }
    r=ln_aac_raw_init(&d->core,d->container.asc,d->container.asc_bytes);if(r!=1)return fail(d,r);
    if(d->core.rate!=d->container.rate||d->core.channels!=d->container.channels)return fail(d,LN_AAC_FORMAT);
    d->rate=d->core.rate;d->channels=d->core.channels;
    d->total_frames=d->container.total_frames-d->container.lead_trim;d->lead_remaining=d->container.lead_trim;
    if(d->tag_seen){
        uint64_t trims=(uint64_t)d->tag_lead+d->tag_tail;
        if(trims>d->container.total_frames||d->tag_frames!=d->container.total_frames-trims||
           (d->container.lead_trim&&d->container.lead_trim!=d->tag_lead))return fail(d,LN_AAC_FORMAT);
        d->total_frames=d->tag_frames;d->lead_remaining=d->tag_lead;
    }
    d->opened=true;return 1;
}
int ln_aac_m4a_decode(struct ln_aac_m4a *d,int16_t *out,uint32_t capacity,uint32_t *frames)
{
    if(frames)*frames=0;if(!d||!out||!capacity||!frames)return LN_AAC_ARGUMENT;
    if(d->error)return d->error;
    if(!d->opened){int r=ln_aac_m4a_open_step(d);return r==1?0:r;}
    if(d->core.pcm_cursor<d->core.pcm_frames){
        uint32_t count=d->core.pcm_frames-d->core.pcm_cursor;
        if(d->seeking){
            if(count>d->seek_target-d->frame)count=(uint32_t)(d->seek_target-d->frame);
            d->core.pcm_cursor+=count;d->frame+=count;
            if(d->frame==d->seek_target)d->seeking=false;return 0;
        }
        if(count>capacity)count=capacity;
        if(count>d->total_frames-d->frame)count=(uint32_t)(d->total_frames-d->frame);
        if(!count){d->core.pcm_cursor=d->core.pcm_frames;return 0;}
        for(uint32_t i=0;i<count*2u;i++)out[i]=d->core.pcm[d->core.pcm_cursor*2u+i];
        d->core.pcm_cursor+=count;d->frame+=count;*frames=count;return 1;
    }
    if(!d->packet_ready){
        int r=ln_m4a_read_packet(&d->container);d->pending=d->container.pending;
        if(r==2)return d->frame==d->total_frames&&!d->seeking?2:fail(d,LN_AAC_FORMAT);
        if(r!=1)return r<0?fail(d,demux_result(r)):r;
        d->packet_ready=true;return 0;
    }
    uint32_t count=d->container.current_packet_frames;
    uint32_t skip=d->lead_remaining;if(skip>count)skip=count;
    uint32_t available=count-skip;
    bool discard=!available||(d->seeking&&d->seek_target-d->frame>=available);
    bool intermediate=discard&&d->seeking&&d->seek_target-d->frame>=(uint64_t)available+1024u;
    int r=intermediate?ln_aac_raw_skip_synthesis(&d->core,d->container.buffer,d->container.packet_size):
        discard?ln_aac_raw_discard(&d->core,d->container.buffer,d->container.packet_size):
        ln_aac_raw_decode(&d->core,d->container.buffer,d->container.packet_size);
    if(r!=1)return fail(d,r);
    d->packet_ready=false;d->core.pcm_frames=d->container.current_packet_frames;
    d->lead_remaining-=skip;
    /* Keep the crossing AU materialized. A completely discarded AU advances
     * the trimmed timeline now, leaving no stale PCM across seek retargets. */
    if(discard){d->core.pcm_cursor=count;d->frame+=available;if(d->frame==d->seek_target)d->seeking=false;}
    else d->core.pcm_cursor=skip;
    return 0;
}
bool ln_aac_m4a_seek(struct ln_aac_m4a *d,uint64_t frame)
{
    if(!d||!d->opened||d->pending||d->container.pending||d->core.pending||frame>d->total_frames)return false;
    /* Preserve forward recurrence only while overlap is valid. A retarget
     * after skipped synthesis reconstructs state from the beginning. */
    if(!d->error&&!d->container.error&&!d->core.error&&!d->core.overlap_invalid&&frame>=d->frame){
        d->seek_target=frame;d->seeking=frame!=d->frame;return true;
    }
    ln_aac_read_fn read=d->source_read;void *context=d->source_context;uint64_t size=d->container.file_size;
    ln_aac_m4a_init(d,read,context,size);d->seek_target=frame;d->seeking=frame!=0;return true;
}
