#include "services/music/artwork.h"
#include "services/storage/storage.h"
#include "services/music/database.h"
#include "boot/include/linnet_boot.h"
#include "hal/api/platform.h"
static uint16_t pixels[2][4096];
static struct ln_fat32_file file;
static char requested[256],path[256];
static uint32_t requested_crc,crc,token,working,revision,generation=0x20000000u;
static uint32_t phase,front;
static bool pending,visible,preload,prefetch_tried;
/* Keep the previous or prefetched cover in the existing second buffer. */
static char cached_path[2][256];
static uint32_t cached_crc[2];
static bool cached_valid[2];
static bool same_path(const char *a,const char *b){
    for(uint32_t i=0;i<256;++i){if(a[i]!=b[i])return false;if(!a[i])return true;}return false;
}
static void copy_path(char *dest,const char *source){
    uint32_t n=0;while(n<255u&&source[n]){dest[n]=source[n];++n;}dest[n]=0;
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
    prefetch_tried=false;
    if(!preload&&(!requested[0]||visible||phase||working!=token)&&
       requested_crc==checksum&&same_path(name?name:"",requested))return;
    bool promote=preload&&checksum==crc&&same_path(name?name:"",path);
    copy_path(requested,name?name:"");
    requested_crc=checksum;++token;
    if(promote){working=token;preload=false;}
    visible=cached_valid[front]&&checksum==cached_crc[front]&&same_path(requested,cached_path[front]);++revision;
}
static void finish(void){
    phase=0;pending=false;preload=false;working=token;
}
void ln_music_art_prefetch(const char *name,uint32_t checksum){
    if(prefetch_tried||phase||pending||working!=token||!name||!name[0])return;
    prefetch_tried=true;
    if(!ln_music_db_safe_path(name))return;
    for(uint32_t slot=0;slot<2u;slot++)
        if(cached_valid[slot]&&cached_crc[slot]==checksum&&same_path(name,cached_path[slot]))return;
    copy_path(path,name);
    crc=checksum;phase=1;preload=true;
    if(++generation>=0x30000000u)generation=0x20000000u;
}
void ln_music_art_step(bool allow_read){
    if(working!=token){
        if(pending){ln_storage_media_cancel(generation);if(!ln_storage_media_poll(generation,0,0))return;pending=false;}
        working=token;phase=1;crc=requested_crc;preload=false;
        if(visible){finish();return;}
        /* Drain the prior read above before changing buffer ownership. */
        for(uint32_t slot=0;slot<2u;slot++){
            if(cached_valid[slot]&&cached_crc[slot]==crc&&same_path(requested,cached_path[slot])){
                front=slot;visible=true;
                ++revision;finish();return;
            }
        }
        copy_path(path,requested);
        if(!path[0]||!ln_music_db_safe_path(path)){finish();return;}
        if(++generation>=0x30000000u)generation=0x20000000u;
    }
    if(!phase)return;
    if(!pending){
        if(!allow_read)return;
        int result=phase==1?ln_storage_media_open(path,generation):
            ln_storage_media_read(&file,0,pixels[front^1u],sizeof pixels[0],generation);
        if(result<0){finish();return;}if(!result)return;
        /* Invalidate only once a read owns the buffer, not while admission waits. */
        if(phase==2)cached_valid[front^1u]=false;
        pending=true;return;
    }
    /* Advance cached FAT transitions without paying an executive turn per
     * sector. Yield to audio and hardware waits within a bounded CPU budget. */
    uint32_t transferred=0,began=ln_time_us();int result;
    for(uint32_t step=0;;step++){
        result=ln_storage_media_poll_deferred(generation,phase==1?&file:0,&transferred);
        if(result||step==3u)break;
        uint32_t now=ln_time_us(),deadline;
        if(now-began>=500u||(ln_storage_idle_wait(now,&deadline)&&(int32_t)(deadline-now)>0))break;
    }
    if(!result)return;pending=false;if(result<0){finish();return;}
    if(phase==1){if(file.size!=8192){finish();return;}phase=2;return;}
    if(transferred!=sizeof pixels[0]){finish();return;}
    {
        if(ln_crc32((const uint8_t*)pixels[front^1u],8192)==crc){
#if defined(LINNET_TARGET_IPOD4G_Q21)
            monochrome_cover(pixels[front^1u]);
#endif
            uint32_t slot=front^1u;
            cached_crc[slot]=crc;
            copy_path(cached_path[slot],path);
            cached_valid[slot]=true;
            if(!preload){
                front=slot;visible=true;
                ++revision;
            }
        }
        finish();
    }
}
