#include "alac.h"
#define TAG(a,b,c,d) (((uint32_t)(a)<<24)|((uint32_t)(b)<<16)|((uint32_t)(c)<<8)|(d))
static uint16_t be16(const uint8_t *p){return (uint16_t)((p[0]<<8)|p[1]);}
static uint32_t be32(const uint8_t *p){return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|(p[2]<<8)|p[3];}
static uint64_t be64(const uint8_t *p){return ((uint64_t)be32(p)<<32)|be32(p+4);}
static uint32_t divide_small(uint32_t value,uint32_t divisor,uint32_t *remainder)
{
    /* Sequential packets commonly remain inside the first chunk. */
    if(value<divisor){if(remainder)*remainder=value;return 0;}
    if(divisor==1u){if(remainder)*remainder=0;return value;}
    uint32_t quotient=0,r=0;
    for(uint32_t i=32;i;i--){r=(r<<1)|((value>>(i-1u))&1u);if(r>=divisor){r-=divisor;quotient|=1u<<(i-1u);}}
    if(remainder)*remainder=r;return quotient;
}
static int bad(struct ln_alac *a,int result){a->error=result;return result;}
static int read_bytes(struct ln_alac *a,uint64_t off,uint32_t count)
{
    if(!count||count>sizeof(a->buffer)||off>a->file_size||count>a->file_size-off)return bad(a,LN_ALAC_FORMAT);
    if(!a->read_total){a->read_offset=off;a->read_total=count;a->read_done=0;}
    if(a->read_offset!=off||a->read_total!=count)return bad(a,LN_ALAC_ARGUMENT);
    uint32_t bytes=count-a->read_done;if(bytes>16384)bytes=16384;
    int result=a->read(a->context,off+a->read_done,a->buffer+a->read_done,bytes);a->pending=result==0;
    if(result<0){a->read_total=0;return bad(a,LN_ALAC_IO);}if(!result)return 0;
    a->read_done+=bytes;if(a->read_done!=count)return 0;a->read_total=0;return 1;
}
/* The outer decoder owns exactly one outstanding immutable read. Keep its
 * identity while a larger, bounded source read fills one of two windows. */
static int cached_read(void *context,uint64_t offset,uint8_t *buffer,uint32_t bytes)
{
    struct ln_alac *d=context;uint64_t size=d->file_size;
    if(!bytes||bytes>16384||offset>size||bytes>size-offset)return -1;
    uint32_t slot=d->cache_filling;
    if(d->cache_pending){
        if(offset!=d->cache_request_offset||bytes!=d->cache_request_bytes||buffer!=d->cache_request_buffer)return -1;
    }else{
        uint32_t overlap=2;
        for(uint32_t i=0;i<2;i++){
            if(offset>=d->cache_offset[i]&&offset-d->cache_offset[i]<=d->cache_bytes[i]&&
               bytes<=d->cache_bytes[i]-(uint32_t)(offset-d->cache_offset[i])){
                uint32_t at=(uint32_t)(offset-d->cache_offset[i]);
                for(uint32_t j=0;j<bytes;j++)buffer[j]=d->read_cache[i][at+j];
                d->cache_victim=(uint8_t)(i^1u);return 1;
            }
            if(offset>=d->cache_offset[i]&&offset-d->cache_offset[i]<d->cache_bytes[i])overlap=i;
        }
        if(overlap!=d->cache_victim)overlap=2;
        slot=d->cache_victim;d->cache_filling=(uint8_t)slot;
        uint32_t retained=0;
        if(overlap<2){
            uint32_t at=(uint32_t)(offset-d->cache_offset[slot]);retained=d->cache_bytes[slot]-at;
            /* A packet can straddle the media window. Keep its cached prefix
             * and read only the new suffix, preserving the other table window. */
            for(uint32_t j=0;j<retained;j++)d->read_cache[slot][j]=d->read_cache[slot][at+j];
        }
        d->cache_offset[slot]=offset;d->cache_bytes[slot]=retained;
        d->cache_request_offset=offset;d->cache_request_bytes=bytes;d->cache_request_buffer=buffer;
    }
    uint32_t fill=size-d->cache_offset[slot]>16384?16384:(uint32_t)(size-d->cache_offset[slot]);
    uint32_t retained=d->cache_bytes[slot];
    int result=d->source_read(d->source_context,d->cache_offset[slot]+retained,d->read_cache[slot]+retained,fill-retained);
    d->cache_pending=result==0;if(result!=1)return result;
    d->cache_bytes[slot]=fill;d->cache_victim=(uint8_t)(slot^1u);
    for(uint32_t j=0;j<bytes;j++)buffer[j]=d->read_cache[slot][j];
    return 1;
}
void ln_alac_init(struct ln_alac *a,ln_alac_read_fn read,void *context,uint64_t size)
{
    uint8_t *p=(uint8_t *)a;for(uint32_t i=0;i<sizeof(*a);i++)p[i]=0;
    a->source_read=read;a->source_context=context;
    a->read=cached_read;a->context=a;a->file_size=size;a->ends[0]=size;
}
void ln_m4a_init(struct ln_alac *a,ln_alac_read_fn read,void *context,uint64_t size)
{ln_alac_init(a,read,context,size);a->allow_aac=true;
 /* AAC provides its own metadata/media cache around this demux. */
 a->read=read;a->context=context;}
static bool parent(struct ln_alac *a,uint32_t type){return a->depth&&a->parents[a->depth]==type;}
static bool once(struct ln_alac *a,uint32_t bit){if(a->seen&bit)return false;a->seen|=bit;return true;}
static bool descriptors(struct ln_alac *a,const uint8_t *b,uint32_t bytes,uint32_t depth)
{
    if(depth>4)return false;
    uint32_t at=0;
    while(at<bytes){
        uint32_t tag=b[at++],size=0,n=0;uint8_t byte;
        do{if(at==bytes||++n>4)return false;byte=b[at++];size=(size<<7)|(byte&127u);}while(byte&128u);
        if(size>bytes-at)return false;
        const uint8_t *p=b+at;uint32_t skip=0;
        if(tag==3){
            if(size<3)return false;uint8_t flags=p[2];skip=3;
            if(flags&128u)skip+=2;
            if(flags&64u){if(skip>=size)return false;skip+=1u+p[skip];}
            if(flags&32u)skip+=2;
        }else if(tag==4){if(size<13||p[0]!=0x40||((p[1]>>2)&63u)!=5)return false;skip=13;}
        else if(tag==5){
            if(a->asc_bytes||size<2||size>64)return false;
            for(uint32_t i=0;i<size;i++)a->asc[i]=p[i];a->asc_bytes=size;
        }
        if(skip&&(skip>size||!descriptors(a,p+skip,size-skip,depth+1)))return false;
        at+=size;
    }return true;
}
static bool asc_info(struct ln_alac *a)
{
    static const uint32_t rates[13]={96000,88200,64000,48000,44100,32000,24000,22050,16000,12000,11025,8000,7350};
    if(a->asc_bytes<2||(a->asc[0]>>3)!=2)return false;
    uint32_t index=((a->asc[0]&7u)<<1)|(a->asc[1]>>7);
    if(index>=13)return false;
    a->rate=rates[index];a->channels=(a->asc[1]>>3)&15u;
    return a->channels>=1&&a->channels<=2&&a->rate>=8000;
}
static int body(struct ln_alac *a)
{
    uint8_t *b=a->buffer;uint32_t n=a->body_bytes,t=a->atom_type;
    if(t==TAG('s','t','s','d')){
        if(n<52||be32(b)||be32(b+4)!=1||!once(a,1))return bad(a,LN_ALAC_FORMAT);
        uint32_t entry=be32(b+8);
        uint32_t type=be32(b+12);
        if(entry!=n-8||entry<44||be16(b+22)!=1||be16(b+24))return bad(a,LN_ALAC_UNSUPPORTED);
        if(type==TAG('a','l','a','c'))a->codec=18;
        else if(type==TAG('m','p','4','a')&&a->allow_aac)a->codec=17;
        else return bad(a,LN_ALAC_UNSUPPORTED);
        uint32_t at=44;
        while(at+8<=n){uint32_t size=be32(b+at);if(size<8||size>n-at)return bad(a,LN_ALAC_FORMAT);
            if(be32(b+at+4)==TAG('a','l','a','c')&&a->codec==18){
                if(size!=36||be32(b+at+8)||a->rate)return bad(a,LN_ALAC_FORMAT);
                uint8_t *c=b+at+12;
                a->core.setinfo_max_samples_per_frame=be32(c);a->core.setinfo_7a=c[4];a->core.setinfo_sample_size=c[5];
                a->core.setinfo_rice_historymult=c[6];a->core.setinfo_rice_initialhistory=c[7];a->core.setinfo_rice_kmodifier=c[8];a->core.setinfo_7f=c[9];
                a->rate=be32(c+20);a->channels=c[9];
                if(c[4]||c[5]!=16||!a->channels||a->channels>2||a->rate<8000||a->rate>96000||!be32(c)||be32(c)>4096||c[8]>14)return bad(a,LN_ALAC_UNSUPPORTED);
                if(be16(b+32)!=a->channels||be16(b+34)!=16)return bad(a,LN_ALAC_FORMAT);
            }else if(be32(b+at+4)==TAG('e','s','d','s')&&a->codec==17){
                if(size<12||be32(b+at+8)||!descriptors(a,b+at+12,size-12,0)||!asc_info(a))return bad(a,LN_ALAC_UNSUPPORTED);
                a->core.setinfo_max_samples_per_frame=1024;
            }at+=size;
        }
        if(at!=n||!a->rate)return bad(a,LN_ALAC_FORMAT);
    }else if(t==TAG('s','t','s','z')){
        if(n!=12||be32(b)||!once(a,2))return bad(a,LN_ALAC_FORMAT);
        a->default_size=be32(b+4);a->packets=be32(b+8);a->sizes_offset=a->cursor+12;
        if(!a->packets||a->packets>1000000||a->default_size>32768||a->atom_end-a->cursor!=12u+(a->default_size?0u:(uint64_t)a->packets*4u))return bad(a,LN_ALAC_UNSUPPORTED);
    }else if(t==TAG('s','t','c','o')||t==TAG('c','o','6','4')){
        if(n!=8||be32(b)||!once(a,4))return bad(a,LN_ALAC_FORMAT);
        a->chunks=be32(b+4);a->chunk_width=t==TAG('s','t','c','o')?4u:8u;a->chunks_offset=a->cursor+8;
        if(!a->chunks||a->chunks>1000000||a->atom_end-a->cursor!=8u+(uint64_t)a->chunks*a->chunk_width)return bad(a,LN_ALAC_UNSUPPORTED);
    }else if(t==TAG('s','t','s','c')){
        if(n<20||be32(b)||!once(a,8))return bad(a,LN_ALAC_FORMAT);
        a->chunk_count=be32(b+4);
        if(!a->chunk_count||a->chunk_count>256||n!=8+12*a->chunk_count)return bad(a,LN_ALAC_UNSUPPORTED);
        for(uint32_t i=0;i<a->chunk_count;i++){
            uint8_t *c=b+8+i*12;a->map[i].first=be32(c);a->map[i].count=be32(c+4);
            if(!a->map[i].first||!a->map[i].count||a->map[i].count>256||be32(c+8)!=1||(!i&&a->map[i].first!=1)||(i&&a->map[i].first<=a->map[i-1].first))return bad(a,LN_ALAC_UNSUPPORTED);
        }
    }else if(t==TAG('s','t','t','s')){
        if(n<16||be32(b)||!once(a,16))return bad(a,LN_ALAC_FORMAT);
        a->time_count=be32(b+4);
        if(!a->time_count||a->time_count>128||n!=8+8*a->time_count)return bad(a,LN_ALAC_UNSUPPORTED);
        for(uint32_t i=0;i<a->time_count;i++){
            a->times[i].count=be32(b+8+i*8);a->times[i].delta=be32(b+12+i*8);
            if(!a->times[i].count||!a->times[i].delta||a->times[i].delta>4096)return bad(a,LN_ALAC_UNSUPPORTED);
        }
    }else if(t==TAG('m','v','h','d')){
        if(n<20||be32(b)||a->movie_scale)return bad(a,LN_ALAC_UNSUPPORTED);
        a->movie_scale=be32(b+12);
        if(!a->movie_scale||a->movie_scale>1000000)return bad(a,LN_ALAC_UNSUPPORTED);
    }else if(t==TAG('m','d','h','d')){
        if(n<24||be32(b)||!once(a,32))return bad(a,LN_ALAC_UNSUPPORTED);
        /* sample timescale is compared to the ALAC rate after all atoms. */
        a->skip=be32(b+12);
    }else if(t==TAG('h','d','l','r')){
        if(n<12||be32(b)||be32(b+8)!=TAG('s','o','u','n')||!once(a,64))return bad(a,LN_ALAC_UNSUPPORTED);
    }else if(t==TAG('e','l','s','t')){
        if(n!=20||be32(b)||be32(b+4)!=1||(be32(b+12)&0x80000000u)||be32(b+16)!=0x10000||!once(a,256))return bad(a,LN_ALAC_UNSUPPORTED);
        a->lead_trim=be32(b+12);
        a->edit_duration=be32(b+8);
    }else if(t==TAG('d','r','e','f')){
        if(n!=20||be32(b)||be32(b+4)!=1||be32(b+8)!=12||be32(b+12)!=TAG('u','r','l',' ')||be32(b+16)!=1||!once(a,128))return bad(a,LN_ALAC_UNSUPPORTED);
    }
    a->cursor=a->atom_end;a->phase=0;return 0;
}
static int finish_open(struct ln_alac *a)
{
    if((a->seen&255u)!=255||a->tracks!=1||a->skip!=a->rate||!a->mdat_end)return bad(a,LN_ALAC_UNSUPPORTED);
    uint64_t packets=0,frames=0;
    for(uint32_t i=0;i<a->time_count;i++){
        if(a->times[i].delta>a->core.setinfo_max_samples_per_frame)return bad(a,LN_ALAC_FORMAT);
        packets+=a->times[i].count;frames+=(uint64_t)a->times[i].count*a->times[i].delta;
    }
    if(packets!=a->packets)return bad(a,LN_ALAC_FORMAT);
    packets=0;
    for(uint32_t i=0;i<a->chunk_count;i++){
        uint32_t end=i+1<a->chunk_count?a->map[i+1].first:a->chunks+1;
        if(a->map[i].first>a->chunks||end<=a->map[i].first)return bad(a,LN_ALAC_FORMAT);
        packets+=(uint64_t)(end-a->map[i].first)*a->map[i].count;
    }
    if(packets!=a->packets)return bad(a,LN_ALAC_FORMAT);
    if(a->lead_trim>=frames||(a->codec==18&&a->lead_trim))return bad(a,LN_ALAC_UNSUPPORTED);
    if(a->seen&256u){
        if(!a->movie_scale)return bad(a,LN_ALAC_FORMAT);
        uint64_t movie=(uint64_t)a->edit_duration*a->rate,media=(frames-a->lead_trim)*a->movie_scale;
        if((movie>media?movie-media:media-movie)>=a->rate)return bad(a,LN_ALAC_UNSUPPORTED);
    }
    a->total_frames=frames;a->skip=0;a->opened=true;return 1;
}
int ln_alac_open_step(struct ln_alac *a)
{
    if(!a||!a->read)return LN_ALAC_ARGUMENT;if(a->error)return a->error;if(a->opened)return 1;
    if(a->phase){int result=read_bytes(a,a->cursor,a->body_bytes);return result==1?body(a):result;}
    while(a->cursor==a->ends[a->depth]){if(!a->depth)return finish_open(a);a->depth--;}
    uint64_t remain=a->ends[a->depth]-a->cursor;
    if(a->cursor>a->ends[a->depth]||remain<8)return bad(a,LN_ALAC_FORMAT);
    int result=read_bytes(a,a->cursor,remain>=16?16:8);if(result!=1)return result;
    if(++a->atoms>4096)return bad(a,LN_ALAC_UNSUPPORTED);
    uint32_t head=8,t=be32(a->buffer+4);uint64_t size=be32(a->buffer);
    if(size==1){if(remain<16)return bad(a,LN_ALAC_FORMAT);size=be64(a->buffer+8);head=16;}
    else if(!size)size=remain;
    if(size<head||size>remain)return bad(a,LN_ALAC_FORMAT);
    a->atom_start=a->cursor;a->atom_end=a->cursor+size;a->atom_type=t;
    if(t==TAG('m','o','o','f')||t==TAG('s','e','n','c'))return bad(a,LN_ALAC_UNSUPPORTED);
    bool container=t==TAG('m','o','o','v')||t==TAG('t','r','a','k')||t==TAG('m','d','i','a')||t==TAG('m','i','n','f')||t==TAG('s','t','b','l')||t==TAG('e','d','t','s')||t==TAG('d','i','n','f');
    if(container){
        if(a->depth>=7)return bad(a,LN_ALAC_UNSUPPORTED);
        if(t==TAG('t','r','a','k')&&++a->tracks>1)return bad(a,LN_ALAC_UNSUPPORTED);
        a->depth++;a->ends[a->depth]=a->atom_end;a->parents[a->depth]=t;a->cursor+=head;return 0;
    }
    if(t==TAG('m','d','a','t')){if(a->depth||a->mdat_end)return bad(a,LN_ALAC_UNSUPPORTED);a->mdat_start=a->cursor+head;a->mdat_end=a->atom_end;}
    uint64_t bytes=size-head;uint32_t take=0;
    if(parent(a,TAG('s','t','b','l'))){
        if(t==TAG('s','t','s','d')||t==TAG('s','t','s','c')||t==TAG('s','t','t','s')){if(bytes>4096)return bad(a,LN_ALAC_UNSUPPORTED);take=(uint32_t)bytes;}
        else if(t==TAG('s','t','s','z'))take=12;
        else if(t==TAG('s','t','c','o')||t==TAG('c','o','6','4'))take=8;
    }else if(parent(a,TAG('m','d','i','a'))&&(t==TAG('m','d','h','d')||t==TAG('h','d','l','r'))){take=t==TAG('m','d','h','d')?24:12;}
    else if(parent(a,TAG('m','o','o','v'))&&t==TAG('m','v','h','d'))take=20;
    else if((parent(a,TAG('e','d','t','s'))&&t==TAG('e','l','s','t'))||(parent(a,TAG('d','i','n','f'))&&t==TAG('d','r','e','f'))){if(bytes>4096)return bad(a,LN_ALAC_UNSUPPORTED);take=(uint32_t)bytes;}
    if(take){if(take>bytes)return bad(a,LN_ALAC_FORMAT);a->cursor+=head;a->body_bytes=take;a->phase=1;return 0;}
    a->cursor=a->atom_end;return 0;
}
static void nothing(void){}
int ln_m4a_open_step(struct ln_alac *a){return ln_alac_open_step(a);}
static uint32_t packet_frames(struct ln_alac *a,uint32_t packet)
{
    for(uint32_t i=0;i<a->time_count;i++){if(packet<a->times[i].count)return a->times[i].delta;packet-=a->times[i].count;}return 0;
}
static bool locate(struct ln_alac *a)
{
    uint32_t first=0;
    for(uint32_t i=0;i<a->chunk_count;i++){
        uint32_t end=i+1<a->chunk_count?a->map[i+1].first:a->chunks+1;
        uint32_t count=(end-a->map[i].first)*a->map[i].count;
        if(a->packet-first<count){uint32_t rel=a->packet-first;
            a->chunk_index=a->map[i].first-1+divide_small(rel,a->map[i].count,&a->chunk_ordinal);
            a->chunk_first=a->packet-a->chunk_ordinal;a->chunk_packets=a->map[i].count;return true;}
        first+=count;
    }return false;
}
int ln_m4a_read_packet(struct ln_alac *a)
{
    if(!a)return LN_ALAC_ARGUMENT;
    if(a->error)return a->error;if(!a->opened){int result=ln_alac_open_step(a);return result==1?0:result;}
    if(a->packet==a->packets)return 2;
    if(!a->decode_phase){if(!locate(a))return bad(a,LN_ALAC_FORMAT);a->decode_phase=1;}
    if(a->decode_phase==1){
        int result=read_bytes(a,a->chunks_offset+(uint64_t)a->chunk_index*a->chunk_width,a->chunk_width);if(result!=1)return result;
        a->packet_offset=a->chunk_width==4?be32(a->buffer):be64(a->buffer);
        if(a->packet_offset<a->mdat_start||a->packet_offset>=a->mdat_end)return bad(a,LN_ALAC_FORMAT);
        a->decode_phase=2;return 0;
    }
    if(a->decode_phase==2){
        if(a->default_size){
            a->packet_size=a->default_size;uint64_t skip=(uint64_t)a->chunk_ordinal*a->packet_size;
            if(skip>a->mdat_end-a->packet_offset)return bad(a,LN_ALAC_FORMAT);a->packet_offset+=skip;
        }
        else{
            int result=read_bytes(a,a->sizes_offset+(uint64_t)a->chunk_first*4,(a->chunk_ordinal+1)*4);if(result!=1)return result;
            for(uint32_t i=0;i<=a->chunk_ordinal;i++){
                uint32_t size=be32(a->buffer+i*4);if(!size||size>32768)return bad(a,LN_ALAC_UNSUPPORTED);
                if(size>a->mdat_end-a->packet_offset)return bad(a,LN_ALAC_FORMAT);
                if(i==a->chunk_ordinal)a->packet_size=size;else a->packet_offset+=size;
            }
        }
        if(a->packet_offset<a->mdat_start||a->packet_offset>a->mdat_end||a->packet_size>a->mdat_end-a->packet_offset)return bad(a,LN_ALAC_FORMAT);
        if(a->codec==17&&a->packet_size>8191)return bad(a,LN_ALAC_UNSUPPORTED);
        a->decode_phase=3;return 0;
    }
    int result=read_bytes(a,a->packet_offset,a->packet_size);if(result!=1)return result;
    a->current_packet_frames=packet_frames(a,a->packet);a->packet++;a->decode_phase=0;return 1;
}
int ln_alac_decode(struct ln_alac *a,int16_t *out,uint32_t capacity,uint32_t *frames)
{
    if(!a||!out||!frames||!capacity)return LN_ALAC_ARGUMENT;*frames=0;
    if(a->error)return a->error;
    if(a->pcm_cursor<a->pcm_count){
        uint32_t count=a->pcm_count-a->pcm_cursor;if(count>capacity)count=capacity;
        for(uint32_t i=0;i<count;i++)for(uint32_t channel=0;channel<2;channel++){
            int32_t value=a->pcm[channel][a->pcm_cursor+i]>>SCALE16;
            if(value>32767)value=32767;if(value<-32768)value=-32768;out[i*2+channel]=(int16_t)value;
        }
        a->pcm_cursor+=count;a->frame+=count;*frames=count;return 1;
    }
    int result=ln_m4a_read_packet(a);if(result!=1)return result;
    if(a->codec!=18)return bad(a,LN_ALAC_UNSUPPORTED);
    int count=alac_decode_frame(&a->core,a->buffer,a->packet_size,a->pcm,nothing);
    if(count<=0||(uint32_t)count!=a->current_packet_frames||a->skip>(uint32_t)count)return bad(a,LN_ALAC_FORMAT);
    a->pcm_count=(uint32_t)count;a->pcm_cursor=a->skip;a->skip=0;return 0;
}
bool ln_alac_seek(struct ln_alac *a,uint64_t frame)
{
    if(!a||!a->opened||a->pending||a->error||frame>a->total_frames)return false;
    uint64_t remaining=frame;uint32_t packet=0;
    for(uint32_t i=0;i<a->time_count;i++){
        uint64_t span=(uint64_t)a->times[i].count*a->times[i].delta;
        if(remaining<span){uint32_t residue;packet+=divide_small((uint32_t)remaining,a->times[i].delta,&residue);remaining=residue;break;}
        remaining-=span;packet+=a->times[i].count;
    }
    a->packet=packet;a->skip=(uint32_t)remaining;a->frame=frame;a->pcm_count=a->pcm_cursor=0;a->decode_phase=0;a->read_total=0;return true;
}
bool ln_m4a_seek(struct ln_alac *a,uint64_t frame){return ln_alac_seek(a,frame);}
