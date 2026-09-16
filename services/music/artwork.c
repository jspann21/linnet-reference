#include "services/music/artwork.h"
#include "services/storage/storage.h"
#include "services/music/database.h"
#include "boot/include/linnet_boot.h"
static uint16_t pixels[2][4096];
static struct ln_fat32_file file;
static char requested[256],path[256];
static char front_path[256];
static uint32_t front_crc;
static uint32_t requested_crc,crc,token,working,revision,generation=0x20000000u;
static uint32_t phase,offset,front;
static bool pending,visible;
static bool front_valid;
#if defined(LINNET_TARGET_IPOD4G_Q21)
/* Reuse the previous cover in the existing second pixel buffer. */
static char cached_path[2][256];
static uint32_t cached_crc[2];
static bool cached_valid[2];
#endif
static bool same_path(const char *a,const char *b){
    for(uint32_t i=0;i<256;++i){if(a[i]!=b[i])return false;if(!a[i])return true;}return false;
}
#if defined(LINNET_TARGET_IPOD4G_Q21)
static void monochrome_cover(uint16_t *image){
    static const uint8_t threshold[16]={0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5};
    static const uint16_t gray[4]={0x0000,0x52aa,0xad55,0xffff};
    /* Convert once after CRC validation, on the native 64x64 pixel grid.
     * Fixed spatial dithering preserves midtones without animation/flicker. */
    for(uint32_t y=0;y<64u;y++)for(uint32_t x=0;x<64u;x++){
        uint16_t c=image[y*64u+x];
        if(c==gray[0]||c==gray[1]||c==gray[2]||c==gray[3])continue;
        uint32_t light=(((c>>11)*77u*255u/31u)+(((c>>5)&63u)*150u*255u/63u)+((c&31u)*29u*255u/31u))>>8;
        uint32_t value=light*3u,level=value/255u,remainder=value-level*255u;
        if(level<3u&&remainder*16u>threshold[(y&3u)*4u+(x&3u)]*255u+127u)++level;
        image[y*64u+x]=gray[level];
    }
}
#endif
const uint16_t *ln_music_art_pixels(void){return visible?pixels[front]:0;}
uint32_t ln_music_art_revision(void){return revision;}
void ln_music_art_request(const char *name,uint32_t checksum){
    uint32_t n=0;if(name)while(n<255&&name[n]){requested[n]=name[n];++n;}requested[n]=0;
    requested_crc=checksum;++token;
    visible=front_valid&&checksum==front_crc&&same_path(requested,front_path);++revision;
}
static void finish(void){phase=0;pending=false;working=token;}
void ln_music_art_step(bool allow_read){
    if(working!=token){
        if(pending){ln_storage_media_cancel(generation);if(!ln_storage_media_poll(generation,0,0))return;pending=false;}
        working=token;offset=0;phase=1;crc=requested_crc;
        if(visible){finish();return;}
#if defined(LINNET_TARGET_IPOD4G_Q21)
        /* Drain the prior read above before changing buffer ownership. */
        for(uint32_t slot=0;slot<2u;slot++){
            if(cached_valid[slot]&&cached_crc[slot]==crc&&same_path(requested,cached_path[slot])){
                front=slot;front_crc=crc;front_valid=visible=true;
                for(uint32_t i=0;i<256u;i++){front_path[i]=requested[i];if(!requested[i])break;}
                ++revision;finish();return;
            }
        }
#endif
        for(uint32_t i=0;i<256;++i){path[i]=requested[i];if(!path[i])break;}
        if(!path[0]||!ln_music_db_safe_path(path)){finish();return;}
        if(++generation>=0x30000000u)generation=0x20000000u;
    }
    if(!phase)return;
    if(!pending){
        if(!allow_read)return;
#if defined(LINNET_TARGET_IPOD4G_Q21)
        /* Partial, canceled, or failed reads must never remain cache hits. */
        if(phase==2)cached_valid[front^1u]=false;
#endif
        int result=phase==1?ln_storage_media_open(path,generation):
            ln_storage_media_read(&file,offset,(uint8_t*)pixels[front^1u]+offset,4096,generation);
        if(result<0){finish();return;}if(!result)return;pending=true;return;
    }
    uint32_t transferred=0;int result=ln_storage_media_poll(generation,phase==1?&file:0,&transferred);
    if(!result)return;pending=false;if(result<0){finish();return;}
    if(phase==1){if(file.size!=8192){finish();return;}phase=2;return;}
    if(transferred!=4096){finish();return;}offset+=4096;
    if(offset==8192){
        if(ln_crc32((const uint8_t*)pixels[front^1u],8192)==crc){
#if defined(LINNET_TARGET_IPOD4G_Q21)
            monochrome_cover(pixels[front^1u]);
#endif
            front^=1u;front_crc=crc;front_valid=visible=true;
            for(uint32_t i=0;i<256;++i){front_path[i]=path[i];if(!path[i])break;}
#if defined(LINNET_TARGET_IPOD4G_Q21)
            cached_crc[front]=crc;
            for(uint32_t i=0;i<256u;i++){cached_path[front][i]=path[i];if(!path[i])break;}
            cached_valid[front]=true;
#endif
            ++revision;}
        finish();
    }
}
