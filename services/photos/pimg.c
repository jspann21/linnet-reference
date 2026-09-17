#include "boot/include/linnet_bytes.h"
#include "pimg.h"
#include "boot/include/linnet_boot.h"
static bool zero(const uint8_t*p,uint32_t n){while(n--)if(*p++)return false;return true;}
static bool section(uint32_t *at,uint32_t offset,uint32_t count,uint32_t width,uint32_t limit){
    if(offset!=*at||offset>limit||count>(limit-offset)/width)return false;*at+=count*width;return true;
}
uint32_t ln_pimg_crc_update(uint32_t crc,const uint8_t*p,uint32_t n){
    /* Raw accumulator: callers retain ownership of the initial/final XOR. */
    static const uint32_t nibble[16]={
        0x00000000u,0x1db71064u,0x3b6e20c8u,0x26d930acu,
        0x76dc4190u,0x6b6b51f4u,0x4db26158u,0x5005713cu,
        0xedb88320u,0xf00f9344u,0xd6d6a3e8u,0xcb61b38cu,
        0x9b64c2b0u,0x86d3d2d4u,0xa00ae278u,0xbdbdf21cu
    };
    while(n--){crc^=*p++;crc=(crc>>4)^nibble[crc&15u];crc=(crc>>4)^nibble[crc&15u];}return crc;
}
bool ln_pimg_header(const uint8_t*b,uint32_t size,struct ln_pimg_header*h){
    if(!b||!h||size<512||size>0x7fffffffu||b[0]!='P'||b[1]!='I'||b[2]!='M'||b[3]!='G'||
       ln_read_le16(b+4)!=0||ln_read_le16(b+6)!=512||ln_read_le32(b+8)||ln_read_le32(b+12)!=size||
       ln_read_le16(b+64)!=64||ln_read_le16(b+66)!=64||ln_read_le16(b+68)!=32||ln_read_le16(b+70)!=1||
       !zero(b+72,436)||ln_crc32(b,508)!=ln_read_le32(b+508))return false;
    *h=(struct ln_pimg_header){size,ln_read_le32(b+16),ln_read_le32(b+20),ln_read_le32(b+24),ln_read_le32(b+28),ln_read_le32(b+32),ln_read_le32(b+36),ln_read_le32(b+40),ln_read_le32(b+44),ln_read_le32(b+48),ln_read_le32(b+52),ln_read_le32(b+56),ln_read_le32(b+60),ln_read_le32(b+508)};
    if(!h->albums||h->albums>4096||h->photos>65535||h->levels<h->photos||h->levels>h->photos*6u||h->tiles>1000000u||!h->string_bytes||h->string_bytes>16777216u||h->data_at%512u)return false;
    uint32_t at=512;
    if(!section(&at,h->album_at,h->albums,32,size)||!section(&at,h->photo_at,h->photos,64,size)||
       !section(&at,h->level_at,h->levels,24,size)||!section(&at,h->tile_at,h->tiles,8,size)||
       !section(&at,h->string_at,h->string_bytes,1,size)||h->data_at<at||h->data_at-at>=512u)return false;
    at=h->data_at;
    return section(&at,h->data_at,h->photos,8192,size)&&section(&at,at,h->tiles,2048,size)&&at==size;
}
static bool string_range(const struct ln_pimg_header*h,uint32_t at,uint32_t bytes,uint32_t max){return bytes<=max&&at<h->string_bytes&&bytes<h->string_bytes-at;}
bool ln_pimg_album(const struct ln_pimg_header*h,const uint8_t*b,uint32_t index,struct ln_pimg_album*a){
    if(index>=h->albums||ln_crc32(b,28)!=ln_read_le32(b+28)||!zero(b+20,8))return false;
    *a=(struct ln_pimg_album){ln_read_le32(b),ln_read_le32(b+4),ln_read_le32(b+8),ln_read_le32(b+12),ln_read_le32(b+16)};
    return a->bytes&&string_range(h,a->title,a->bytes,191)&&a->first<=h->photos&&a->count<=h->photos-a->first&&(index?a->parent<index:a->parent==UINT32_MAX);
}
bool ln_pimg_photo(const struct ln_pimg_header*h,const uint8_t*b,uint32_t index,struct ln_pimg_photo*p){
    if(index>=h->photos||ln_crc32(b,60)!=ln_read_le32(b+60)||ln_read_le32(b+56))return false;
    *p=(struct ln_pimg_photo){ln_read_le32(b),ln_read_le32(b+4),ln_read_le32(b+8),ln_read_le32(b+12),ln_read_le32(b+16),ln_read_le32(b+20),ln_read_le32(b+24),ln_read_le32(b+28),ln_read_le32(b+32),ln_read_le32(b+36),ln_read_le32(b+40),ln_read_le32(b+44),ln_read_le32(b+48),ln_read_le32(b+52)};
    if(p->source_bytes?(!p->jpeg_bytes||p->jpeg_bytes>262144||!p->orientation||p->orientation>8||p->width>2048||p->height>2048||p->width*p->height>4000000u):(p->source||p->jpeg_bytes||p->jpeg_crc||p->orientation))return false;
    return p->album<h->albums&&p->bytes&&string_range(h,p->title,p->bytes,191)&&string_range(h,p->source,p->source_bytes,127)&&
        p->width&&p->height&&p->width<=16384&&p->height<=16384&&p->width*p->height<=32000000u&&p->levels&&p->levels<=6&&p->first<h->levels&&p->levels<=h->levels-p->first&&p->thumb==h->data_at+index*8192u;
}
bool ln_pimg_level(const struct ln_pimg_header*h,const uint8_t*b,uint32_t index,struct ln_pimg_level*l){
    if(index>=h->levels||ln_crc32(b,20)!=ln_read_le32(b+20))return false;
    *l=(struct ln_pimg_level){ln_read_le32(b),ln_read_le16(b+4),ln_read_le16(b+6),ln_read_le16(b+8),ln_read_le16(b+10),ln_read_le32(b+12),ln_read_le32(b+16)};
    return l->photo<h->photos&&l->width&&l->height&&l->width<=2048&&l->height<=2048&&
        l->columns==(l->width+31u)/32u&&l->rows==(l->height+31u)/32u&&l->count==l->columns*l->rows&&l->first<h->tiles&&l->count<=h->tiles-l->first;
}
bool ln_pimg_tile(const struct ln_pimg_header*h,const uint8_t*b,uint32_t index,uint32_t*offset,uint32_t*crc){
    if(index>=h->tiles)return false;*offset=ln_read_le32(b);*crc=ln_read_le32(b+4);
    return *offset==h->data_at+h->photos*8192u+index*2048u;
}
bool ln_pimg_text(const uint8_t*s,uint32_t n,bool path){
    if(s[n]||(!n&&path))return false;
    for(uint32_t i=0;i<n;){uint32_t c=s[i++],more,min;
        if(!c||c<32||c==127)return false;
        if(path){if(c>126||c=='\\'||c==':'||c=='*'||c=='?'||c=='"'||c=='<'||c=='>'||c=='|')return false;continue;}
        if(c<128)continue;
        if(c>=0xc2&&c<=0xdf){more=1;min=0x80;c&=31;}else if(c>=0xe0&&c<=0xef){more=2;min=0x800;c&=15;}else if(c>=0xf0&&c<=0xf4){more=3;min=0x10000;c&=7;}else return false;
        if(more>n-i)return false;while(more--){uint32_t x=s[i++];if((x&0xc0)!=0x80)return false;c=c<<6|(x&63);}
        if(c<min||c>0x10ffff||(c>=0xd800&&c<=0xdfff))return false;
    }
    if(path){if(s[0]!='/')return false;for(uint32_t i=0;i<n;i++)if(s[i]=='.'&&i+1<n&&s[i+1]=='.')return false;}
    return true;
}
