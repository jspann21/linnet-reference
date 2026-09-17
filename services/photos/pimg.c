#include "boot/include/linnet_bytes.h"
#include "pimg.h"
#include "boot/include/linnet_boot.h"
static bool zero(const uint8_t*p,uint32_t n){while(n--)if(*p++)return false;return true;}
static bool section(uint32_t *at,uint32_t offset,uint32_t count,uint32_t width,uint32_t limit){
    if(offset!=*at||offset>limit||count>(limit-offset)/width)return false;*at+=count*width;return true;
}
uint32_t ln_pimg_crc_update(uint32_t crc,const uint8_t*p,uint32_t n){
    /* Raw accumulator: callers retain ownership of the initial/final XOR. */
    static const uint32_t table[256]={
        0x00000000u,0x77073096u,0xee0e612cu,0x990951bau,0x076dc419u,0x706af48fu,0xe963a535u,0x9e6495a3u,
        0x0edb8832u,0x79dcb8a4u,0xe0d5e91eu,0x97d2d988u,0x09b64c2bu,0x7eb17cbdu,0xe7b82d07u,0x90bf1d91u,
        0x1db71064u,0x6ab020f2u,0xf3b97148u,0x84be41deu,0x1adad47du,0x6ddde4ebu,0xf4d4b551u,0x83d385c7u,
        0x136c9856u,0x646ba8c0u,0xfd62f97au,0x8a65c9ecu,0x14015c4fu,0x63066cd9u,0xfa0f3d63u,0x8d080df5u,
        0x3b6e20c8u,0x4c69105eu,0xd56041e4u,0xa2677172u,0x3c03e4d1u,0x4b04d447u,0xd20d85fdu,0xa50ab56bu,
        0x35b5a8fau,0x42b2986cu,0xdbbbc9d6u,0xacbcf940u,0x32d86ce3u,0x45df5c75u,0xdcd60dcfu,0xabd13d59u,
        0x26d930acu,0x51de003au,0xc8d75180u,0xbfd06116u,0x21b4f4b5u,0x56b3c423u,0xcfba9599u,0xb8bda50fu,
        0x2802b89eu,0x5f058808u,0xc60cd9b2u,0xb10be924u,0x2f6f7c87u,0x58684c11u,0xc1611dabu,0xb6662d3du,
        0x76dc4190u,0x01db7106u,0x98d220bcu,0xefd5102au,0x71b18589u,0x06b6b51fu,0x9fbfe4a5u,0xe8b8d433u,
        0x7807c9a2u,0x0f00f934u,0x9609a88eu,0xe10e9818u,0x7f6a0dbbu,0x086d3d2du,0x91646c97u,0xe6635c01u,
        0x6b6b51f4u,0x1c6c6162u,0x856530d8u,0xf262004eu,0x6c0695edu,0x1b01a57bu,0x8208f4c1u,0xf50fc457u,
        0x65b0d9c6u,0x12b7e950u,0x8bbeb8eau,0xfcb9887cu,0x62dd1ddfu,0x15da2d49u,0x8cd37cf3u,0xfbd44c65u,
        0x4db26158u,0x3ab551ceu,0xa3bc0074u,0xd4bb30e2u,0x4adfa541u,0x3dd895d7u,0xa4d1c46du,0xd3d6f4fbu,
        0x4369e96au,0x346ed9fcu,0xad678846u,0xda60b8d0u,0x44042d73u,0x33031de5u,0xaa0a4c5fu,0xdd0d7cc9u,
        0x5005713cu,0x270241aau,0xbe0b1010u,0xc90c2086u,0x5768b525u,0x206f85b3u,0xb966d409u,0xce61e49fu,
        0x5edef90eu,0x29d9c998u,0xb0d09822u,0xc7d7a8b4u,0x59b33d17u,0x2eb40d81u,0xb7bd5c3bu,0xc0ba6cadu,
        0xedb88320u,0x9abfb3b6u,0x03b6e20cu,0x74b1d29au,0xead54739u,0x9dd277afu,0x04db2615u,0x73dc1683u,
        0xe3630b12u,0x94643b84u,0x0d6d6a3eu,0x7a6a5aa8u,0xe40ecf0bu,0x9309ff9du,0x0a00ae27u,0x7d079eb1u,
        0xf00f9344u,0x8708a3d2u,0x1e01f268u,0x6906c2feu,0xf762575du,0x806567cbu,0x196c3671u,0x6e6b06e7u,
        0xfed41b76u,0x89d32be0u,0x10da7a5au,0x67dd4accu,0xf9b9df6fu,0x8ebeeff9u,0x17b7be43u,0x60b08ed5u,
        0xd6d6a3e8u,0xa1d1937eu,0x38d8c2c4u,0x4fdff252u,0xd1bb67f1u,0xa6bc5767u,0x3fb506ddu,0x48b2364bu,
        0xd80d2bdau,0xaf0a1b4cu,0x36034af6u,0x41047a60u,0xdf60efc3u,0xa867df55u,0x316e8eefu,0x4669be79u,
        0xcb61b38cu,0xbc66831au,0x256fd2a0u,0x5268e236u,0xcc0c7795u,0xbb0b4703u,0x220216b9u,0x5505262fu,
        0xc5ba3bbeu,0xb2bd0b28u,0x2bb45a92u,0x5cb36a04u,0xc2d7ffa7u,0xb5d0cf31u,0x2cd99e8bu,0x5bdeae1du,
        0x9b64c2b0u,0xec63f226u,0x756aa39cu,0x026d930au,0x9c0906a9u,0xeb0e363fu,0x72076785u,0x05005713u,
        0x95bf4a82u,0xe2b87a14u,0x7bb12baeu,0x0cb61b38u,0x92d28e9bu,0xe5d5be0du,0x7cdcefb7u,0x0bdbdf21u,
        0x86d3d2d4u,0xf1d4e242u,0x68ddb3f8u,0x1fda836eu,0x81be16cdu,0xf6b9265bu,0x6fb077e1u,0x18b74777u,
        0x88085ae6u,0xff0f6a70u,0x66063bcau,0x11010b5cu,0x8f659effu,0xf862ae69u,0x616bffd3u,0x166ccf45u,
        0xa00ae278u,0xd70dd2eeu,0x4e048354u,0x3903b3c2u,0xa7672661u,0xd06016f7u,0x4969474du,0x3e6e77dbu,
        0xaed16a4au,0xd9d65adcu,0x40df0b66u,0x37d83bf0u,0xa9bcae53u,0xdebb9ec5u,0x47b2cf7fu,0x30b5ffe9u,
        0xbdbdf21cu,0xcabac28au,0x53b39330u,0x24b4a3a6u,0xbad03605u,0xcdd70693u,0x54de5729u,0x23d967bfu,
        0xb3667a2eu,0xc4614ab8u,0x5d681b02u,0x2a6f2b94u,0xb40bbe37u,0xc30c8ea1u,0x5a05df1bu,0x2d02ef8du,
    };
    while(n--)crc=(crc>>8)^table[(crc^*p++)&255u];return crc;
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
