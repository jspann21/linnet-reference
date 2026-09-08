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
static bool same_path(const char *a,const char *b){
    for(uint32_t i=0;i<256;++i){if(a[i]!=b[i])return false;if(!a[i])return true;}return false;
}
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
        for(uint32_t i=0;i<256;++i){path[i]=requested[i];if(!path[i])break;}
        if(!path[0]||!ln_music_db_safe_path(path)){finish();return;}
        if(++generation>=0x30000000u)generation=0x20000000u;
    }
    if(!phase)return;
    if(!pending){
        if(!allow_read)return;
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
            front^=1u;front_crc=crc;front_valid=visible=true;
            for(uint32_t i=0;i<256;++i){front_path[i]=path[i];if(!path[i])break;}
            ++revision;}
        finish();
    }
}
