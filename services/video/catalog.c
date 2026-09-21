#include "services/video/catalog.h"
#include "services/video/video.h"
#include "services/storage/storage.h"
#include "boot/include/linnet_bytes.h"
/* Video catalog rows are paged into two small caches. Drawing only reads retained
 * memory and requests missing pages; catalog_step owns asynchronous storage. */
#define CATALOG_ROWS 4u
#define CATALOG_HEADER_SIZE 12u
#define CATALOG_ROW_SIZE 416u
static struct {
    uint8_t header[CATALOG_HEADER_SIZE],pages[2][CATALOG_ROWS*CATALOG_ROW_SIZE];
    struct ln_fat32_file file;
    uint32_t phase,count,revision,wanted,slot,first[2],rows[2],read_size;
    bool pending,want_page;
    char selected[256];
} catalog;
#define CATALOG_GENERATION 0x73000001u

void ln_video_library_load(void){if(!catalog.phase){catalog.phase=1;++catalog.revision;}}
uint32_t ln_video_library_count(void){return catalog.count?catalog.count:1u;}
uint32_t ln_video_library_revision(void){return catalog.revision;}
static const uint8_t *catalog_row(uint32_t row){
    for(uint32_t slot=0;slot<2u;++slot)
        if(row>=catalog.first[slot]&&row-catalog.first[slot]<catalog.rows[slot])
            return catalog.pages[slot]+(row-catalog.first[slot])*CATALOG_ROW_SIZE;
    catalog.wanted=(row/CATALOG_ROWS)*CATALOG_ROWS;catalog.want_page=true;return 0;
}
const char *ln_video_library_label(uint32_t row){
    if(catalog.phase<4)return "Loading videos...";
    if(!catalog.count)return catalog.phase==5?"Video library unavailable":"Add videos with Linnet Sync";
    if(row>=catalog.count)return "";
    const uint8_t*entry=catalog_row(row);
    return entry?(const char*)entry+288u:"Loading videos...";
}
const char *ln_video_library_path(uint32_t row){
    if((catalog.phase!=4&&catalog.phase!=6)||row>=catalog.count)return 0;
    const uint8_t*entry=catalog_row(row);if(!entry)return 0;
    const char*path=(const char*)entry+32u;uint32_t i=0;
    while(path[i]&&i<255u){catalog.selected[i]=path[i];++i;}
    catalog.selected[i]=0;return catalog.selected;
}
void ln_video_catalog_step(bool busy){
    if(!catalog.phase||catalog.phase==5||busy)return;
    int result;
    if(catalog.pending){
        uint32_t transferred=0;
        result=ln_storage_media_poll_deferred(CATALOG_GENERATION,&catalog.file,&transferred);
        if(!result)return;catalog.pending=false;
        if(result<0){
            catalog.phase=result==LN_FAT32_NOT_FOUND?4:5;++catalog.revision;return;
        }
        if(catalog.phase==1){
            if(catalog.file.size<CATALOG_HEADER_SIZE||catalog.file.size>CATALOG_HEADER_SIZE+256u*CATALOG_ROW_SIZE){catalog.phase=5;++catalog.revision;return;}
            catalog.phase=2;return;
        }
        if(catalog.phase==2){
            const uint8_t*b=catalog.header;uint32_t count=ln_read_le32(b+4);
            bool valid=transferred==CATALOG_HEADER_SIZE&&ln_read_le32(b)==0x5849564cu&&count<=256u&&ln_read_le32(b+8)==CATALOG_ROW_SIZE&&catalog.file.size==CATALOG_HEADER_SIZE+count*CATALOG_ROW_SIZE;
            catalog.count=valid?count:0;catalog.phase=valid?4:5;
            catalog.want_page=valid&&count;catalog.wanted=0;++catalog.revision;return;
        }
        bool valid=transferred==catalog.read_size;
        uint32_t rows=catalog.read_size/CATALOG_ROW_SIZE;
        for(uint32_t row=0;valid&&row<rows;++row){
            const uint8_t*entry=catalog.pages[catalog.slot]+row*CATALOG_ROW_SIZE;const uint8_t*name=entry+32;
            bool terminated=false;if(name[0]!='/')valid=false;for(uint32_t j=0;j<256u;++j)if(!name[j]){terminated=true;break;}if(!terminated||!entry[288]||entry[415])valid=false;
        }
        if(valid){catalog.rows[catalog.slot]=rows;catalog.phase=4;catalog.slot^=1u;}
        else{catalog.count=0;catalog.phase=5;catalog.rows[0]=catalog.rows[1]=0;}
        ++catalog.revision;return;
    }
    if(catalog.phase==4){
        if(!catalog.want_page)return;
        uint32_t first=catalog.wanted;catalog.want_page=false;
        if(first>=catalog.count)return;
        for(uint32_t slot=0;slot<2u;++slot)if(catalog.rows[slot]&&catalog.first[slot]==first)return;
        catalog.first[catalog.slot]=first;catalog.rows[catalog.slot]=0;
        uint32_t rows=catalog.count-first;if(rows>CATALOG_ROWS)rows=CATALOG_ROWS;
        catalog.read_size=rows*CATALOG_ROW_SIZE;catalog.phase=6;
    }
    if(catalog.phase==2)result=ln_storage_media_read(&catalog.file,0,catalog.header,CATALOG_HEADER_SIZE,CATALOG_GENERATION);
    else if(catalog.phase==6)result=ln_storage_media_read(&catalog.file,CATALOG_HEADER_SIZE+catalog.first[catalog.slot]*CATALOG_ROW_SIZE,catalog.pages[catalog.slot],catalog.read_size,CATALOG_GENERATION);
    else result=ln_storage_media_open("/.LINNET/VIDEOS/INDEX.VID",CATALOG_GENERATION);
    if(result>0)catalog.pending=true;
    else if(result<0){catalog.count=0;catalog.phase=5;++catalog.revision;}
}
bool ln_video_catalog_pending(void){return catalog.pending;}
