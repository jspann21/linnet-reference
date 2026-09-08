#include "profile.h"
/* Generated with tools.content.dsp.peaking_eq (RBJ normalized Q2.30),
 * frequencies100/1800Hz, Q0.7, gain+3dB. Crossfeed pole is
 * round((1-exp(-2*pi*700/rate))*65536). No runtime floating point. */
struct preset_rate {uint32_t rate,crossfeed;struct ln_dsp_biquad bass,voice;};
static const struct preset_rate presets[]={
    {8000,27717,{1093688393,-2044459936,957093419,-2044459936,977039988},{1238739058,-210806371,108830804,-210806371,273828039}},
    {11025,21559,{1088403489,-2073032193,987999766,-2073032193,1002661431},{1224113450,-735327131,194361999,-735327131,344733625}},
    {12000,20110,{1087249658,-2079143773,994747420,-2079143773,1008255254},{1218656012,-849310513,226277336,-849310513,371191524}},
    {16000,15751,{1083952521,-2096364274,1014029220,-2096364274,1024239917},{1198097669,-1174523885,346503423,-1174523885,470859268}},
    {22050,11851,{1081198998,-2110473829,1030131947,-2110473829,1037589121},{1174626248,-1444987587,483765314,-1444987587,584649738}},
    {24000,10974,{1080602629,-2113497674,1033619536,-2113497674,1040480342},{1168694230,-1503261876,518456016,-1503261876,613408422}},
    {32000,8416,{1078907685,-2122030208,1043531644,-2122030208,1048697505},{1150017477,-1667818944,627678479,-1667818944,703954133}},
    {44100,6221,{1077502441,-2129035904,1051749572,-2129035904,1055510189},{1132336428,-1802471229,731078026,-1802471229,789672630}},
    {48000,5738,{1077199294,-2130539139,1053522390,-2130539139,1056979859},{1128242451,-1831227547,755019782,-1831227547,809520409}},
    {88200,3188,{1075630196,-2138274480,1062698543,-2138274480,1064586915},{1105355252,-1977847851,888865122,-1977847851,920478549}},
    {96000,2935,{1075477369,-2139023834,1063592280,-2139023834,1065327826},{1102967737,-1991891890,902827408,-1991891890,932053321}},
};
void ln_music_profile_default(struct ln_music_profile *p){if(p)*p=(struct ln_music_profile){0};}
bool ln_music_profile_valid(const struct ln_music_profile *p){
    return p&&p->preset<=LN_MUSIC_EQ_VOICE&&p->mode<=LINNET_DSP_KARAOKE&&
        p->balance>=-1000&&p->balance<=1000&&p->preamp_db_q16>=-24*65536&&p->preamp_db_q16<=0;
}
bool ln_music_profile_configure(const struct ln_music_profile *p,uint32_t rate,
                               int32_t track_replaygain,struct ln_dsp_config *out){
    if(!out||!ln_music_profile_valid(p))return false;
    const struct preset_rate *entry=0;
    for(uint32_t i=0;i<sizeof(presets)/sizeof(presets[0]);i++)if(presets[i].rate==rate){entry=&presets[i];break;}
    if(!entry)return false;
    struct ln_dsp dsp;ln_dsp_init(&dsp);struct ln_dsp_config c=dsp.config;
    c.gain_q16=ln_dsp_gain_from_db(p->preamp_db_q16-(p->preset?3*65536:0));
    c.replaygain_q16=p->replaygain?ln_dsp_gain_from_db(track_replaygain):LINNET_DSP_UNITY;
    c.mode=p->mode;c.balance=p->balance;
    if(p->preset){c.band_count=1;c.bands[0]=p->preset==LN_MUSIC_EQ_BASS?entry->bass:entry->voice;}
    if(p->crossfeed){c.crossfeed_amount_q16=16384;c.crossfeed_coefficient_q16=entry->crossfeed;}
    if(!ln_dsp_configure(&dsp,&c))return false;*out=c;return true;
}
static void put(uint8_t *p,uint32_t x){for(uint32_t i=0;i<4;i++)p[i]=(uint8_t)(x>>(i*8));}
static uint32_t get(const uint8_t *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static uint32_t crc(const uint8_t *p){uint32_t x=UINT32_MAX;
    for(uint32_t i=0;i<28;i++){x^=p[i];for(uint32_t bit=0;bit<8;bit++)x=(x>>1)^((0u-(x&1u))&0xedb88320u);}return ~x;
}
bool ln_music_profile_encode(const struct ln_music_profile *p,uint8_t out[LN_MUSIC_PROFILE_BYTES]){
    if(!out||!ln_music_profile_valid(p))return false;
    put(out,0x3150534du);put(out+4,0x00200001u);put(out+8,(p->replaygain?1u:0u)|(p->crossfeed?2u:0u));
    put(out+12,p->preset);put(out+16,p->mode);put(out+20,(uint32_t)p->balance);put(out+24,(uint32_t)p->preamp_db_q16);put(out+28,crc(out));return true;
}
static int32_t signed32(uint32_t x){return x<=INT32_MAX?(int32_t)x:-1-(int32_t)(~x);}
bool ln_music_profile_decode(struct ln_music_profile *p,const uint8_t *data,uint32_t bytes){
    if(!p||!data||bytes!=32||get(data)!=0x3150534du||get(data+4)!=0x00200001u||
       (get(data+8)&~3u)||get(data+28)!=crc(data))return false;
    uint32_t flags=get(data+8);struct ln_music_profile candidate={get(data+12),get(data+16),signed32(get(data+20)),signed32(get(data+24)),(flags&1u)!=0,(flags&2u)!=0};
    if(!ln_music_profile_valid(&candidate))return false;*p=candidate;return true;
}
