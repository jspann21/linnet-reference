#include "package.h"
#include "boot/include/linnet_bytes.h"
#include "boot/include/linnet_boot.h"
static bool text(char *out,const uint8_t *in,uint32_t n){
    bool ended=false;
    for(uint32_t i=0;i<n;++i){uint8_t ch=in[i];
        if(!ch)ended=true;
        else if(ended||ch<32u||ch>126u)return false;
        out[i]=(char)ch;
    }
    return ended;
}
bool ln_game_identity(const char *id){
    uint32_t dots=0;bool segment=false;
    for(uint32_t i=0;i<LN_GAME_ID_BYTES;++i){uint8_t ch=(uint8_t)id[i];
        if(!ch)return segment&&dots!=0;
        if(ch=='.'){if(!segment)return false;++dots;segment=false;}
        else if((ch>='a'&&ch<='z')||(ch>='0'&&ch<='9')||ch=='-')segment=true;
        else return false;
    }
    return false;
}
bool ln_game_legacy_identity(const char *id,uint32_t legacy){
    static const char *const names[]={"linnet.comet-run","linnet.pulse-path","linnet.solitaire",
        "linnet.sudoku","linnet.brick","linnet.music-quiz","linnet.vortex","linnet.minesweeper",
        "linnet.falling-blocks","linnet.reversi","linnet.snake","linnet.word-search","linnet.scrub",
        "linnet.dial-heist","linnet.mixtape","linnet.signal","linnet.clockwork-city","linnet.pocket-pinball"};
    if(legacy!=UINT32_MAX&&legacy>=18u)return false;
    for(uint32_t i=0;i<18u;++i){const char *a=id,*b=names[i];while(*a&&*a==*b){++a;++b;}
        if(!*a&&!*b)return legacy==i;}
    return legacy==UINT32_MAX;
}
bool ln_game_header_decode(const uint8_t p[256],uint32_t target,uint32_t load,
                           struct ln_game_header *out){
    if(!p||!out||ln_read_le32(p)!=0x4d474e4cu||ln_read_le32(p+4)!=1u||
       ln_read_le32(p+8)!=256u||ln_read_le32(p+12)!=target||
       ln_read_le32(p+16)!=LN_GAME_ABI||ln_read_le32(p+20)!=LN_GAME_LAYOUT||
       ln_read_le32(p+24)!=load||ln_crc32(p,252u)!=ln_read_le32(p+252))return false;
    struct ln_game_header h={0};
    h.target=target;h.load=load;h.payload=ln_read_le32(p+28);h.bss=ln_read_le32(p+32);
    h.entry=ln_read_le32(p+36);h.capabilities=ln_read_le32(p+40);
    h.legacy=ln_read_le32(p+44);h.crc=ln_read_le32(p+48);h.stack=ln_read_le32(p+52);
    h.text=ln_read_le32(p+56);h.schema=ln_read_le32(p+60);h.version=ln_read_le32(p+248);
    for(uint32_t i=0;i<32u;++i)h.sha256[i]=p[216u+i];
    if(h.payload<32u||(h.payload&31u)||(h.bss&31u)||h.payload>LN_GAME_SLOT_BYTES||h.bss>LN_GAME_SLOT_BYTES-h.payload||
       h.text<4u||(h.text&3u)||h.text>h.payload||h.entry>h.text-4u||(h.entry&3u)||(h.capabilities&~LN_GAME_CAP_ALL)||
       (h.legacy!=UINT32_MAX&&h.legacy>=18u)||!h.stack||h.stack>8192u||
       !h.version||!h.schema||
       !text(h.id,p+64,64)||!ln_game_identity(h.id)||!ln_game_legacy_identity(h.id,h.legacy)||
       !text(h.title,p+128,40)||!h.title[0]||!text(h.description,p+168,48))return false;
    *out=h;return true;
}
