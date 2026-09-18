#include "boot/include/linnet_bytes.h"
#include "profile.h"
struct preset_rate {uint32_t rate,crossfeed;};
static const struct preset_rate presets[]={
{8000,27717},{11025,21559},{12000,20110},{16000,15751},{22050,11851},{24000,10974},{32000,8416},{44100,6221},{48000,5738},{88200,3188},{96000,2935}
};
/* Q1.30 sin(w)/(2Q), cos(w); custom 100/8k Hz Q=1,
 * followed by Bass 100 Hz and Voice 1800 Hz Q=.7. */
static const int32_t custom_poles[11][4][2]={
{{42122406,1070431836},{0,0},{60174866,1070431836},{757515915,167970228}},
{{30579898,1071998593},{0,0},{43685568,1071998593},{655858964,556619782}},
{{28097653,1072270298},{0,0},{40139504,1072270298},{620482417,631129609}},
{{21077453,1072914008},{0,0},{30110647,1072914008},{498099666,816479688}},
{{15296158,1073305928},{407556002,-698937712},{21851655,1073305928},{376359971,935571335}},
{{14053642,1073373879},{464943848,-536870912},{20076632,1073373879},{348191848,956710970}},
{{10540758,1073534850},{536870912,0},{15058226,1073534850},{265457400,1007375276}},
{{7648856,1073632844},{487775583,448577112},{10926937,1073632844},{194542525,1038624951}},
{{7027423,1073649834},{464943848,536870912},{10039176,1073649834},{179042893,1044074252}},
{{3824525,1073714579},{289669100,904040240},{5463607,1073714579},{98076469,1064926418}},
{{3513787,1073718826},{268435456,929887697},{5019695,1073718826},{90146300,1066299136}}
};
static __attribute__((minsize)) int32_t ratio(int64_t numerator,uint32_t denominator){
    bool negative=numerator<0;uint64_t value=(uint64_t)(negative?-numerator:numerator)+denominator/2u;
    uint64_t divisor=(uint64_t)denominator<<31;uint32_t result=0;
    for(uint32_t bit=0x80000000u;bit;bit>>=1,divisor>>=1)if(value>=divisor){value-=divisor;result|=bit;}
    return negative?-(int32_t)result:(int32_t)result;
}
static __attribute__((minsize)) struct ln_dsp_biquad custom_band(uint32_t rate_index,uint32_t band,int32_t gain){
    static const uint32_t amplitudes[]={46396,49145,52057,55142,58409,61870,65536,69419,73533,77890,82505,87394,92572};
    int32_t alpha=custom_poles[rate_index][band][0],cosine=custom_poles[rate_index][band][1];
    uint32_t amplitude=amplitudes[gain+6];
    int32_t cut=ratio((int64_t)alpha*65536,amplitude);
    int32_t boost=(int32_t)(((int64_t)alpha*amplitude+32768)>>16);
    uint32_t a0=1073741824u+(uint32_t)cut;
    int32_t b0=ratio((1073741824LL+boost)*1073741824LL,a0);
    int32_t b1=ratio(-2LL*cosine*1073741824LL,a0);
    int32_t a2=ratio((1073741824LL-cut)*1073741824LL,a0);
    int32_t b2=(int32_t)(1073741824LL+a2-b0);
    return (struct ln_dsp_biquad){b0,b1,b2,b1,a2};
}
void ln_music_profile_default(struct ln_music_profile *p){if(p)*p=(struct ln_music_profile){0};}
__attribute__((minsize)) bool ln_music_profile_valid(const struct ln_music_profile *p){
    if(!p)return false;
    for(uint32_t i=0;i<2;i++)if(p->eq_db[i]<-6||p->eq_db[i]>6)return false;
    return p->replaygain<=2&&p->max_volume_db_tenths>=-730&&p->max_volume_db_tenths<=0&&p->max_volume_db_tenths%10==0&&p->preset<=LN_MUSIC_EQ_CUSTOM&&p->mode<=LINNET_DSP_KARAOKE&&
        p->balance>=-1000&&p->balance<=1000&&p->preamp_db_q16>=-24*65536&&p->preamp_db_q16<=0;
}
__attribute__((minsize)) bool ln_music_profile_configure(const struct ln_music_profile *p,uint32_t rate,
                               int32_t replaygain_db_q16,struct ln_dsp_config *out){
    if(!out||!ln_music_profile_valid(p))return false;
    const struct preset_rate *entry=0;
    for(uint32_t i=0;i<sizeof(presets)/sizeof(presets[0]);i++)if(presets[i].rate==rate){entry=&presets[i];break;}
    if(!entry)return false;
    struct ln_dsp dsp;ln_dsp_init(&dsp);struct ln_dsp_config c=dsp.config;
    int32_t headroom=p->preset&&p->preset!=LN_MUSIC_EQ_CUSTOM?3:0;
    if(p->preset==LN_MUSIC_EQ_CUSTOM){
        static const uint32_t frequencies[]={100,8000};
        for(uint32_t i=0;i<2;i++)if(p->eq_db[i]&&frequencies[i]<rate/2){
            c.bands[c.band_count++]=custom_band((uint32_t)(entry-presets),i,p->eq_db[i]);
            if(p->eq_db[i]>0)headroom+=p->eq_db[i];
        }
    }
    c.gain_q16=ln_dsp_gain_from_db(p->preamp_db_q16-headroom*65536);
    uint32_t replaygain=p->replaygain?ln_dsp_gain_from_db(replaygain_db_q16):LINNET_DSP_UNITY;
    c.gain_q16=(uint32_t)(((uint64_t)c.gain_q16*replaygain+32768u)>>16);
    if(!c.gain_q16)c.gain_q16=1;
    c.mode=p->mode;c.balance=p->balance;
    if(p->preset&&p->preset!=LN_MUSIC_EQ_CUSTOM){c.band_count=1;c.bands[0]=custom_band((uint32_t)(entry-presets),p->preset==LN_MUSIC_EQ_BASS?2u:3u,3);}
    if(p->crossfeed){c.crossfeed_amount_q16=16384;c.crossfeed_coefficient_q16=entry->crossfeed;}
    if(!ln_dsp_configure(&dsp,&c))return false;*out=c;return true;
}
static uint32_t crc(const uint8_t *p){uint32_t x=UINT32_MAX;
    for(uint32_t i=0;i<28;i++){x^=p[i];for(uint32_t bit=0;bit<8;bit++)x=(x>>1)^((0u-(x&1u))&0xedb88320u);}return ~x;
}
__attribute__((minsize)) bool ln_music_profile_encode(const struct ln_music_profile *p,uint8_t out[LN_MUSIC_PROFILE_BYTES]){
    if(!out||!ln_music_profile_valid(p))return false;
    uint32_t flags=(p->replaygain==1?1u:p->replaygain==2?4u:0u)|(p->crossfeed?2u:0u);
    for(uint32_t i=0;i<2;i++)flags|=(uint32_t)(p->eq_db[i]+6)<<(3+i*4);
    flags|=(uint32_t)(-p->max_volume_db_tenths/10)<<23;
    ln_write_le32(out,0x464f5250u);ln_write_le32(out+4,0x00200001u);ln_write_le32(out+8,flags);
    ln_write_le32(out+12,p->preset);ln_write_le32(out+16,p->mode);ln_write_le32(out+20,(uint32_t)p->balance);ln_write_le32(out+24,(uint32_t)p->preamp_db_q16);ln_write_le32(out+28,crc(out));return true;
}
static int32_t signed32(uint32_t x){return x<=INT32_MAX?(int32_t)x:-1-(int32_t)(~x);}
__attribute__((minsize)) bool ln_music_profile_decode(struct ln_music_profile *p,const uint8_t *data,uint32_t bytes){
    if(!p||!data||bytes!=32||ln_read_le32(data)!=0x464f5250u||
       (ln_read_le32(data+4)!=0x00200000u&&ln_read_le32(data+4)!=0x00200001u)||ln_read_le32(data+28)!=crc(data))return false;
    uint32_t flags=ln_read_le32(data+8);bool legacy=ln_read_le32(data+4)==0x00200000u;
    if(legacy?(flags&~3u):((flags&0xc0000000u)||(flags&5u)==5u))return false;
    struct ln_music_profile candidate={.preset=ln_read_le32(data+12),.mode=ln_read_le32(data+16),
        .balance=signed32(ln_read_le32(data+20)),.preamp_db_q16=signed32(ln_read_le32(data+24)),
        .replaygain=(flags&4u)?2u:flags&1u,.crossfeed=(flags&2u)!=0};
    if(!legacy){
        for(uint32_t i=0;i<2;i++)candidate.eq_db[i]=(int8_t)((flags>>(3+i*4))&15u)-6;
        candidate.max_volume_db_tenths=-(int32_t)((flags>>23)&127u)*10;
    }
    if(!ln_music_profile_valid(&candidate))return false;*p=candidate;return true;
}
