#include "video.h"
#include "services/storage/storage.h"
#include "hal/pp5020/audio.h"
#include "hal/pp5020/platform.h"
#define PIXELS (220u*176u)
#define FRAME_BYTES (PIXELS*2u)
#define IPVF_PAYLOAD (FRAME_BYTES+4096u)
#define PVID_RECORD 90112u
#define RECORD 98304u
#define IPVF_LZ_SCRATCH ((uint8_t *)(uintptr_t)0x01000000u)
/* Reserved STAGE: LZ scratch, stereo PCM, decoded video, then raw records.
 * The HAL continues to own its existing DMA ring. */
#define PCM_BASE ((uint32_t *)(uintptr_t)0x01020000u)
#define PCM_FRAMES 262144u
#define VIDEO_BASE ((uint16_t *)(uintptr_t)0x01120000u)
#define FRAME_SLOTS 83u
#define VIDEO_PREROLL 80u
#define RAW_BASE ((uint8_t *)(uintptr_t)0x01720000u)
#define RAW_CAPACITY 0x000e0000u
#define RAW_ENTRIES 1024u
#define NONE 0xffffffffu
#include "crc_shift_table.h"
_Static_assert(RECORD<(1u<<17),"video CRC shift length bound");
_Static_assert((PCM_FRAMES&(PCM_FRAMES-1u))==0u&&PCM_FRAMES*4u==0x00100000u,"video PCM staging bounds");
_Static_assert((FRAME_SLOTS-3u)*FRAME_BYTES<=0x00600000u,"decoded video staging bounds");
_Static_assert(VIDEO_PREROLL<FRAME_SLOTS,"decoded video preroll bounds");
_Static_assert(FRAME_SLOTS<=96u,"decoded slot ownership bitmap bounds");
enum phase {IDLE,OPEN,HEADER,VERIFY,INDEX,READ,CRC,DECODE,FRAME_CRC,PCM,WAIT,SEEK};
static struct {
    uint16_t frame[2][PIXELS];
    union {uint16_t pixels[PIXELS];uint8_t bytes[IPVF_PAYLOAD];} third;
    union {uint32_t align;uint8_t bytes[RECORD];} record;
    uint8_t index_page[512];
    struct ln_fat32_file file;struct ln_ui_asset asset;
    char path[256],title[128];
    uint32_t phase,error,epoch,working,generation,requested,revision;
    uint32_t version,width,height,fps,count,data_at,max_record,key_interval,index_crc;
    uint32_t fps_num,fps_den,rate,media_end,index_at,index_count,first_sectors,preroll;
    uint32_t time_frame[2],time_sample[2],time_clock,time_clock_frame,time_valid;
    uint32_t verify_at,verify_crc,verify_frame,verify_end,verify_key,verify_max;
    uint32_t next,target,origin,offset,bytes,sample,samples,key,record_crc;
    uint32_t type,video_bytes,payload_crc,frame_crc,at,crc,record_edges_crc,decode_at,decode_pixel,tile_count,tile_last;
    uint32_t audio_bytes,next_sectors,decoded_bytes,source_type,seek_index,seek_frame,seek_offset,seek_sectors;
    uint32_t prefetched_frames,audio_offset,audio_sectors;
    uint32_t video_next,video_offset,video_bytes_saved;
    bool audio_yield;
    uint32_t raw_head,raw_tail,raw_used,raw_first,raw_count;
    const uint8_t *raw_view;
    uint8_t *raw_write;
    uint32_t pcm_head,pcm_tail;
    struct {uint32_t frame,offset,bytes;} raw[RAW_ENTRIES];
    uint32_t rect_x,rect_y,rect_w,rect_h,rect_row,rect_data_at;int32_t motion_dx,motion_dy;
    int32_t ima_left,ima_right;uint8_t ima_left_index,ima_right_index;
    uint32_t front,previous,building,queue[FRAME_SLOTS],qhead,qcount,slot_frame[FRAME_SLOTS],submitted;
    uint32_t reads,read_bytes,prepared,presented,late,max_late,max_prepare,prepare_start,max_queue;
    uint32_t audio_gaps,audio_silence,audio_fault,identity,resume_frame;
    uint32_t index_page_at,previous_crc,io_started,max_io,read_time,max_read_time;
    uint32_t cpu[4],max_cpu[4],max_step,min_audio;
    uint32_t lz_state,lz_token,lz_remaining,lz_offset,lz_literal,lz_span;
    uint32_t lz_input_offset,lz_input_bytes,lz_output_bytes,lz_output_slot;
    bool lz_matched;
#if !defined(LINNET_PROFILE_RELEASE)
    uint32_t measurement,measurement_opened,measurement_started;
    uint32_t phase_us[14],phase_calls[14];
    uint32_t type_us[7],type_calls[7],lz_us;
    uint32_t worst_frame,worst_queue,late_one,late_two,last_present_us,max_gap_us,gap_frame,min_ready,start_ready;
    bool measurement_ran;
#endif
    bool active,pending,stepping,stopping,ready,started,paused,finish,seeking,offered,completed,ipvf,temporal,prefetching;
} v;
/* LVI1 rows are paged into two small caches. Drawing only reads retained
 * memory and requests missing pages; catalog_step owns asynchronous storage. */
#define CATALOG_ROWS 4u
#define CATALOG_ROW_MAX 416u
static struct {
    uint8_t header[16],pages[2][CATALOG_ROWS*CATALOG_ROW_MAX];
    struct ln_fat32_file file;
    uint32_t phase,count,revision,wanted,slot,first[2],rows[2],read_size,row_size,version;
    bool pending,legacy,want_page;
    char selected[256];
} catalog;
#define CATALOG_GENERATION 0x73000001u
static void catalog_step(void);
void ln_video_library_load(void){if(!catalog.phase){catalog.phase=1;++catalog.revision;}}
uint32_t ln_video_library_count(void){return catalog.count?catalog.count:1u;}
uint32_t ln_video_library_revision(void){return catalog.revision;}
static const uint8_t *catalog_row(uint32_t row){
    for(uint32_t slot=0;slot<2u;++slot)
        if(row>=catalog.first[slot]&&row-catalog.first[slot]<catalog.rows[slot])
            return catalog.pages[slot]+(row-catalog.first[slot])*catalog.row_size;
    catalog.wanted=(row/CATALOG_ROWS)*CATALOG_ROWS;catalog.want_page=true;return 0;
}
const char *ln_video_library_label(uint32_t row){
    if(catalog.phase<4)return "Loading videos...";
    if(!catalog.count)return catalog.phase==5?"Video library unavailable":"Add videos with Linnet Sync";
    if(row>=catalog.count)return "";
    if(catalog.legacy)return "Prepared video";
    const uint8_t*entry=catalog_row(row);
    return entry?(const char*)entry+(catalog.version==2u?288u:48u):"Loading videos...";
}
const char *ln_video_library_path(uint32_t row){
    if((catalog.phase!=4&&catalog.phase!=6)||row>=catalog.count)return 0;
    if(catalog.legacy)return "/LINNET/VIDEOS/CURRENT.PVD";
    const uint8_t*entry=catalog_row(row);if(!entry)return 0;
    if(catalog.version==2u){const char*path=(const char*)entry+32u;uint32_t i=0;while(path[i]&&i<255u){catalog.selected[i]=path[i];++i;}catalog.selected[i]=0;return catalog.selected;}
    const char*prefix="/LINNET/VIDEOS/";uint32_t i=0;
    while(prefix[i]){catalog.selected[i]=prefix[i];++i;}
    const char*name=(const char*)entry+32u;
    for(uint32_t j=0;j<13u;++j)catalog.selected[i+j]=name[j];
    return catalog.selected;
}
static uint32_t saved_resume[2];
#if !defined(LINNET_PROFILE_RELEASE)
static uint32_t armed_measurement;
void ln_video_metadata(uint32_t page,uint8_t out[128]){
    for(uint32_t i=0;i<128u;++i)out[i]=0;
    if(page<2u){for(uint32_t i=0;i<128u;++i)out[i]=(uint8_t)v.path[page*128u+i];}
    else if(page==2u){for(uint32_t i=0;i<128u;++i)out[i]=(uint8_t)v.title[i];}
    else if(page==6u){uint32_t words[15];for(uint32_t i=0;i<7u;++i){words[i]=v.type_us[i];words[i+7u]=v.type_calls[i];}words[14]=v.lz_us;
        for(uint32_t i=0;i<15u;++i)for(uint32_t j=0;j<4u;++j)out[i*4u+j]=(uint8_t)(words[i]>>(j*8u));}
    else if(page==7u){uint32_t words[11]={0x31504956u,v.worst_frame,v.max_late,v.worst_queue,v.late_one,v.late_two,v.max_gap_us,v.gap_frame,v.min_ready,v.start_ready,FRAME_SLOTS};
        for(uint32_t i=0;i<11u;++i)for(uint32_t j=0;j<4u;++j)out[i*4u+j]=(uint8_t)(words[i]>>(j*8u));}
    else if(page>=4u){const uint32_t*words=page==4u?v.phase_us:v.phase_calls;
        for(uint32_t i=0;i<14u;++i)for(uint32_t j=0;j<4u;++j)out[i*4u+j]=(uint8_t)(words[i]>>(j*8u));}
    else {uint32_t words[8]={0x314d4956u,v.identity,v.count,v.fps_num,v.fps_den,v.rate,v.file.size,v.ipvf};
        for(uint32_t i=0;i<8u;++i)for(uint32_t j=0;j<4u;++j)out[i*4u+j]=(uint8_t)(words[i]>>(j*8u));}
}
bool ln_video_measurement_arm(uint32_t mode){
    if(mode>2u||v.active||v.pending)return false;
    armed_measurement=mode;return true;
}
#endif
static const uint8_t *record_source(void){return v.raw_write?v.raw_write:v.raw_view?v.raw_view:v.record.bytes;}
static uint32_t r32(const uint8_t*b){return b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;}
static void catalog_step(void){
    if(!catalog.phase||catalog.phase==5||v.active||v.pending)return;
    int result;
    if(catalog.pending){
        uint32_t transferred=0;
        result=ln_storage_media_poll_deferred(CATALOG_GENERATION,&catalog.file,&transferred);
        if(!result)return;catalog.pending=false;
        if(result<0){
            if(catalog.phase==1&&result==LN_FAT32_NOT_FOUND){catalog.phase=3;return;}
            catalog.phase=result==LN_FAT32_NOT_FOUND?4:5;++catalog.revision;return;
        }
        if(catalog.phase==3){catalog.count=1;catalog.legacy=true;catalog.phase=4;++catalog.revision;return;}
        if(catalog.phase==1){
            if(catalog.file.size<16||catalog.file.size>16u+256u*CATALOG_ROW_MAX){catalog.phase=5;++catalog.revision;return;}
            catalog.phase=2;return;
        }
        if(catalog.phase==2){
            const uint8_t*b=catalog.header;uint32_t count=r32(b+8),version=r32(b+4),row_size=r32(b+12);
            bool valid=transferred==16u&&r32(b)==0x3149564cu&&(version==1u||version==2u)&&count<=256u&&row_size==(version==1u?176u:416u)&&catalog.file.size==16u+count*row_size;
            catalog.version=version;catalog.row_size=row_size;
            catalog.count=valid?count:0;catalog.phase=valid?4:5;
            catalog.want_page=valid&&count;catalog.wanted=0;++catalog.revision;return;
        }
        bool valid=transferred==catalog.read_size;
        uint32_t rows=catalog.read_size/catalog.row_size;
        for(uint32_t row=0;valid&&row<rows;++row){
            const uint8_t*entry=catalog.pages[catalog.slot]+row*catalog.row_size;const uint8_t*name=entry+32;
            if(catalog.version==1u){for(uint32_t j=0;j<8u;++j){uint8_t nibble=(entry[j/2u]>>(j%2u?0:4))&15u;if(name[j]!=(uint8_t)(nibble<10?'0'+nibble:'A'+nibble-10))valid=false;}
                if(name[8]!='.'||name[9]!='P'||name[10]!='V'||name[11]!='D'||name[12]||!entry[48]||entry[175])valid=false;}
            else {bool terminated=false;if(name[0]!='/')valid=false;for(uint32_t j=0;j<256u;++j)if(!name[j]){terminated=true;break;}if(!terminated||!entry[288]||entry[415])valid=false;}
        }
        if(valid){catalog.rows[catalog.slot]=rows;catalog.phase=4;catalog.slot^=1u;}
        else{catalog.count=0;catalog.phase=5;catalog.rows[0]=catalog.rows[1]=0;}
        ++catalog.revision;return;
    }
    if(catalog.phase==4){
        if(catalog.legacy||!catalog.want_page)return;
        uint32_t first=catalog.wanted;catalog.want_page=false;
        if(first>=catalog.count)return;
        for(uint32_t slot=0;slot<2u;++slot)if(catalog.rows[slot]&&catalog.first[slot]==first)return;
        catalog.first[catalog.slot]=first;catalog.rows[catalog.slot]=0;
        uint32_t rows=catalog.count-first;if(rows>CATALOG_ROWS)rows=CATALOG_ROWS;
        catalog.read_size=rows*catalog.row_size;catalog.phase=6;
    }
    if(catalog.phase==2)result=ln_storage_media_read(&catalog.file,0,catalog.header,16u,CATALOG_GENERATION);
    else if(catalog.phase==6)result=ln_storage_media_read(&catalog.file,16u+catalog.first[catalog.slot]*catalog.row_size,catalog.pages[catalog.slot],catalog.read_size,CATALOG_GENERATION);
    else result=ln_storage_media_open(catalog.phase==3?"/LINNET/VIDEOS/CURRENT.PVD":"/LINNET/VIDEOS/INDEX.VID",CATALOG_GENERATION);
    if(result>0)catalog.pending=true;
    else if(result<0){catalog.count=0;catalog.phase=5;++catalog.revision;}
}
static uint32_t r16(const uint8_t*b){return b[0]|(uint32_t)b[1]<<8;}
static uint64_t r64(const uint8_t*b){return r32(b)|(uint64_t)r32(b+4)<<32;}
static void clear(void*p,uint32_t n){uint8_t*b=p;while(n--)*b++=0;}
static void copy(void*d,const void*s,uint32_t n){
#if defined(__arm__)
    extern void ln_memory_copy(void *,const void *,uint32_t);ln_memory_copy(d,s,n);
#else
    uint8_t*a=d;const uint8_t*b=s;
    if(!(((uintptr_t)a|(uintptr_t)b)&3u)){while(n>=4){__builtin_memcpy(a,b,4);a+=4;b+=4;n-=4;}}
    while(n--)*a++=*b++;
#endif
}
static uint16_t *frame_slot(uint32_t slot){return slot<2u?v.frame[slot]:slot==2u?v.third.pixels:slot<FRAME_SLOTS?VIDEO_BASE+(slot-3u)*PIXELS:0;}
static bool zero(const uint8_t*p,uint32_t n){while(n--)if(*p++)return false;return true;}
/* The two CRC tables share the existing audio IRAM reservation. */
static const uint32_t crc_slice4_table[4][256]
#if defined(__arm__)
__attribute__((section(".audio_icode.video_crc_table"),aligned(4)))
#endif
= {
    {
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
    },
    {
        0x00000000u,0x191b3141u,0x32366282u,0x2b2d53c3u,0x646cc504u,0x7d77f445u,0x565aa786u,0x4f4196c7u,
        0xc8d98a08u,0xd1c2bb49u,0xfaefe88au,0xe3f4d9cbu,0xacb54f0cu,0xb5ae7e4du,0x9e832d8eu,0x87981ccfu,
        0x4ac21251u,0x53d92310u,0x78f470d3u,0x61ef4192u,0x2eaed755u,0x37b5e614u,0x1c98b5d7u,0x05838496u,
        0x821b9859u,0x9b00a918u,0xb02dfadbu,0xa936cb9au,0xe6775d5du,0xff6c6c1cu,0xd4413fdfu,0xcd5a0e9eu,
        0x958424a2u,0x8c9f15e3u,0xa7b24620u,0xbea97761u,0xf1e8e1a6u,0xe8f3d0e7u,0xc3de8324u,0xdac5b265u,
        0x5d5daeaau,0x44469febu,0x6f6bcc28u,0x7670fd69u,0x39316baeu,0x202a5aefu,0x0b07092cu,0x121c386du,
        0xdf4636f3u,0xc65d07b2u,0xed705471u,0xf46b6530u,0xbb2af3f7u,0xa231c2b6u,0x891c9175u,0x9007a034u,
        0x179fbcfbu,0x0e848dbau,0x25a9de79u,0x3cb2ef38u,0x73f379ffu,0x6ae848beu,0x41c51b7du,0x58de2a3cu,
        0xf0794f05u,0xe9627e44u,0xc24f2d87u,0xdb541cc6u,0x94158a01u,0x8d0ebb40u,0xa623e883u,0xbf38d9c2u,
        0x38a0c50du,0x21bbf44cu,0x0a96a78fu,0x138d96ceu,0x5ccc0009u,0x45d73148u,0x6efa628bu,0x77e153cau,
        0xbabb5d54u,0xa3a06c15u,0x888d3fd6u,0x91960e97u,0xded79850u,0xc7cca911u,0xece1fad2u,0xf5facb93u,
        0x7262d75cu,0x6b79e61du,0x4054b5deu,0x594f849fu,0x160e1258u,0x0f152319u,0x243870dau,0x3d23419bu,
        0x65fd6ba7u,0x7ce65ae6u,0x57cb0925u,0x4ed03864u,0x0191aea3u,0x188a9fe2u,0x33a7cc21u,0x2abcfd60u,
        0xad24e1afu,0xb43fd0eeu,0x9f12832du,0x8609b26cu,0xc94824abu,0xd05315eau,0xfb7e4629u,0xe2657768u,
        0x2f3f79f6u,0x362448b7u,0x1d091b74u,0x04122a35u,0x4b53bcf2u,0x52488db3u,0x7965de70u,0x607eef31u,
        0xe7e6f3feu,0xfefdc2bfu,0xd5d0917cu,0xcccba03du,0x838a36fau,0x9a9107bbu,0xb1bc5478u,0xa8a76539u,
        0x3b83984bu,0x2298a90au,0x09b5fac9u,0x10aecb88u,0x5fef5d4fu,0x46f46c0eu,0x6dd93fcdu,0x74c20e8cu,
        0xf35a1243u,0xea412302u,0xc16c70c1u,0xd8774180u,0x9736d747u,0x8e2de606u,0xa500b5c5u,0xbc1b8484u,
        0x71418a1au,0x685abb5bu,0x4377e898u,0x5a6cd9d9u,0x152d4f1eu,0x0c367e5fu,0x271b2d9cu,0x3e001cddu,
        0xb9980012u,0xa0833153u,0x8bae6290u,0x92b553d1u,0xddf4c516u,0xc4eff457u,0xefc2a794u,0xf6d996d5u,
        0xae07bce9u,0xb71c8da8u,0x9c31de6bu,0x852aef2au,0xca6b79edu,0xd37048acu,0xf85d1b6fu,0xe1462a2eu,
        0x66de36e1u,0x7fc507a0u,0x54e85463u,0x4df36522u,0x02b2f3e5u,0x1ba9c2a4u,0x30849167u,0x299fa026u,
        0xe4c5aeb8u,0xfdde9ff9u,0xd6f3cc3au,0xcfe8fd7bu,0x80a96bbcu,0x99b25afdu,0xb29f093eu,0xab84387fu,
        0x2c1c24b0u,0x350715f1u,0x1e2a4632u,0x07317773u,0x4870e1b4u,0x516bd0f5u,0x7a468336u,0x635db277u,
        0xcbfad74eu,0xd2e1e60fu,0xf9ccb5ccu,0xe0d7848du,0xaf96124au,0xb68d230bu,0x9da070c8u,0x84bb4189u,
        0x03235d46u,0x1a386c07u,0x31153fc4u,0x280e0e85u,0x674f9842u,0x7e54a903u,0x5579fac0u,0x4c62cb81u,
        0x8138c51fu,0x9823f45eu,0xb30ea79du,0xaa1596dcu,0xe554001bu,0xfc4f315au,0xd7626299u,0xce7953d8u,
        0x49e14f17u,0x50fa7e56u,0x7bd72d95u,0x62cc1cd4u,0x2d8d8a13u,0x3496bb52u,0x1fbbe891u,0x06a0d9d0u,
        0x5e7ef3ecu,0x4765c2adu,0x6c48916eu,0x7553a02fu,0x3a1236e8u,0x230907a9u,0x0824546au,0x113f652bu,
        0x96a779e4u,0x8fbc48a5u,0xa4911b66u,0xbd8a2a27u,0xf2cbbce0u,0xebd08da1u,0xc0fdde62u,0xd9e6ef23u,
        0x14bce1bdu,0x0da7d0fcu,0x268a833fu,0x3f91b27eu,0x70d024b9u,0x69cb15f8u,0x42e6463bu,0x5bfd777au,
        0xdc656bb5u,0xc57e5af4u,0xee530937u,0xf7483876u,0xb809aeb1u,0xa1129ff0u,0x8a3fcc33u,0x9324fd72u,
    },
    {
        0x00000000u,0x01c26a37u,0x0384d46eu,0x0246be59u,0x0709a8dcu,0x06cbc2ebu,0x048d7cb2u,0x054f1685u,
        0x0e1351b8u,0x0fd13b8fu,0x0d9785d6u,0x0c55efe1u,0x091af964u,0x08d89353u,0x0a9e2d0au,0x0b5c473du,
        0x1c26a370u,0x1de4c947u,0x1fa2771eu,0x1e601d29u,0x1b2f0bacu,0x1aed619bu,0x18abdfc2u,0x1969b5f5u,
        0x1235f2c8u,0x13f798ffu,0x11b126a6u,0x10734c91u,0x153c5a14u,0x14fe3023u,0x16b88e7au,0x177ae44du,
        0x384d46e0u,0x398f2cd7u,0x3bc9928eu,0x3a0bf8b9u,0x3f44ee3cu,0x3e86840bu,0x3cc03a52u,0x3d025065u,
        0x365e1758u,0x379c7d6fu,0x35dac336u,0x3418a901u,0x3157bf84u,0x3095d5b3u,0x32d36beau,0x331101ddu,
        0x246be590u,0x25a98fa7u,0x27ef31feu,0x262d5bc9u,0x23624d4cu,0x22a0277bu,0x20e69922u,0x2124f315u,
        0x2a78b428u,0x2bbade1fu,0x29fc6046u,0x283e0a71u,0x2d711cf4u,0x2cb376c3u,0x2ef5c89au,0x2f37a2adu,
        0x709a8dc0u,0x7158e7f7u,0x731e59aeu,0x72dc3399u,0x7793251cu,0x76514f2bu,0x7417f172u,0x75d59b45u,
        0x7e89dc78u,0x7f4bb64fu,0x7d0d0816u,0x7ccf6221u,0x798074a4u,0x78421e93u,0x7a04a0cau,0x7bc6cafdu,
        0x6cbc2eb0u,0x6d7e4487u,0x6f38fadeu,0x6efa90e9u,0x6bb5866cu,0x6a77ec5bu,0x68315202u,0x69f33835u,
        0x62af7f08u,0x636d153fu,0x612bab66u,0x60e9c151u,0x65a6d7d4u,0x6464bde3u,0x662203bau,0x67e0698du,
        0x48d7cb20u,0x4915a117u,0x4b531f4eu,0x4a917579u,0x4fde63fcu,0x4e1c09cbu,0x4c5ab792u,0x4d98dda5u,
        0x46c49a98u,0x4706f0afu,0x45404ef6u,0x448224c1u,0x41cd3244u,0x400f5873u,0x4249e62au,0x438b8c1du,
        0x54f16850u,0x55330267u,0x5775bc3eu,0x56b7d609u,0x53f8c08cu,0x523aaabbu,0x507c14e2u,0x51be7ed5u,
        0x5ae239e8u,0x5b2053dfu,0x5966ed86u,0x58a487b1u,0x5deb9134u,0x5c29fb03u,0x5e6f455au,0x5fad2f6du,
        0xe1351b80u,0xe0f771b7u,0xe2b1cfeeu,0xe373a5d9u,0xe63cb35cu,0xe7fed96bu,0xe5b86732u,0xe47a0d05u,
        0xef264a38u,0xeee4200fu,0xeca29e56u,0xed60f461u,0xe82fe2e4u,0xe9ed88d3u,0xebab368au,0xea695cbdu,
        0xfd13b8f0u,0xfcd1d2c7u,0xfe976c9eu,0xff5506a9u,0xfa1a102cu,0xfbd87a1bu,0xf99ec442u,0xf85cae75u,
        0xf300e948u,0xf2c2837fu,0xf0843d26u,0xf1465711u,0xf4094194u,0xf5cb2ba3u,0xf78d95fau,0xf64fffcdu,
        0xd9785d60u,0xd8ba3757u,0xdafc890eu,0xdb3ee339u,0xde71f5bcu,0xdfb39f8bu,0xddf521d2u,0xdc374be5u,
        0xd76b0cd8u,0xd6a966efu,0xd4efd8b6u,0xd52db281u,0xd062a404u,0xd1a0ce33u,0xd3e6706au,0xd2241a5du,
        0xc55efe10u,0xc49c9427u,0xc6da2a7eu,0xc7184049u,0xc25756ccu,0xc3953cfbu,0xc1d382a2u,0xc011e895u,
        0xcb4dafa8u,0xca8fc59fu,0xc8c97bc6u,0xc90b11f1u,0xcc440774u,0xcd866d43u,0xcfc0d31au,0xce02b92du,
        0x91af9640u,0x906dfc77u,0x922b422eu,0x93e92819u,0x96a63e9cu,0x976454abu,0x9522eaf2u,0x94e080c5u,
        0x9fbcc7f8u,0x9e7eadcfu,0x9c381396u,0x9dfa79a1u,0x98b56f24u,0x99770513u,0x9b31bb4au,0x9af3d17du,
        0x8d893530u,0x8c4b5f07u,0x8e0de15eu,0x8fcf8b69u,0x8a809decu,0x8b42f7dbu,0x89044982u,0x88c623b5u,
        0x839a6488u,0x82580ebfu,0x801eb0e6u,0x81dcdad1u,0x8493cc54u,0x8551a663u,0x8717183au,0x86d5720du,
        0xa9e2d0a0u,0xa820ba97u,0xaa6604ceu,0xaba46ef9u,0xaeeb787cu,0xaf29124bu,0xad6fac12u,0xacadc625u,
        0xa7f18118u,0xa633eb2fu,0xa4755576u,0xa5b73f41u,0xa0f829c4u,0xa13a43f3u,0xa37cfdaau,0xa2be979du,
        0xb5c473d0u,0xb40619e7u,0xb640a7beu,0xb782cd89u,0xb2cddb0cu,0xb30fb13bu,0xb1490f62u,0xb08b6555u,
        0xbbd72268u,0xba15485fu,0xb853f606u,0xb9919c31u,0xbcde8ab4u,0xbd1ce083u,0xbf5a5edau,0xbe9834edu,
    },
    {
        0x00000000u,0xb8bc6765u,0xaa09c88bu,0x12b5afeeu,0x8f629757u,0x37def032u,0x256b5fdcu,0x9dd738b9u,
        0xc5b428efu,0x7d084f8au,0x6fbde064u,0xd7018701u,0x4ad6bfb8u,0xf26ad8ddu,0xe0df7733u,0x58631056u,
        0x5019579fu,0xe8a530fau,0xfa109f14u,0x42acf871u,0xdf7bc0c8u,0x67c7a7adu,0x75720843u,0xcdce6f26u,
        0x95ad7f70u,0x2d111815u,0x3fa4b7fbu,0x8718d09eu,0x1acfe827u,0xa2738f42u,0xb0c620acu,0x087a47c9u,
        0xa032af3eu,0x188ec85bu,0x0a3b67b5u,0xb28700d0u,0x2f503869u,0x97ec5f0cu,0x8559f0e2u,0x3de59787u,
        0x658687d1u,0xdd3ae0b4u,0xcf8f4f5au,0x7733283fu,0xeae41086u,0x525877e3u,0x40edd80du,0xf851bf68u,
        0xf02bf8a1u,0x48979fc4u,0x5a22302au,0xe29e574fu,0x7f496ff6u,0xc7f50893u,0xd540a77du,0x6dfcc018u,
        0x359fd04eu,0x8d23b72bu,0x9f9618c5u,0x272a7fa0u,0xbafd4719u,0x0241207cu,0x10f48f92u,0xa848e8f7u,
        0x9b14583du,0x23a83f58u,0x311d90b6u,0x89a1f7d3u,0x1476cf6au,0xaccaa80fu,0xbe7f07e1u,0x06c36084u,
        0x5ea070d2u,0xe61c17b7u,0xf4a9b859u,0x4c15df3cu,0xd1c2e785u,0x697e80e0u,0x7bcb2f0eu,0xc377486bu,
        0xcb0d0fa2u,0x73b168c7u,0x6104c729u,0xd9b8a04cu,0x446f98f5u,0xfcd3ff90u,0xee66507eu,0x56da371bu,
        0x0eb9274du,0xb6054028u,0xa4b0efc6u,0x1c0c88a3u,0x81dbb01au,0x3967d77fu,0x2bd27891u,0x936e1ff4u,
        0x3b26f703u,0x839a9066u,0x912f3f88u,0x299358edu,0xb4446054u,0x0cf80731u,0x1e4da8dfu,0xa6f1cfbau,
        0xfe92dfecu,0x462eb889u,0x549b1767u,0xec277002u,0x71f048bbu,0xc94c2fdeu,0xdbf98030u,0x6345e755u,
        0x6b3fa09cu,0xd383c7f9u,0xc1366817u,0x798a0f72u,0xe45d37cbu,0x5ce150aeu,0x4e54ff40u,0xf6e89825u,
        0xae8b8873u,0x1637ef16u,0x048240f8u,0xbc3e279du,0x21e91f24u,0x99557841u,0x8be0d7afu,0x335cb0cau,
        0xed59b63bu,0x55e5d15eu,0x47507eb0u,0xffec19d5u,0x623b216cu,0xda874609u,0xc832e9e7u,0x708e8e82u,
        0x28ed9ed4u,0x9051f9b1u,0x82e4565fu,0x3a58313au,0xa78f0983u,0x1f336ee6u,0x0d86c108u,0xb53aa66du,
        0xbd40e1a4u,0x05fc86c1u,0x1749292fu,0xaff54e4au,0x322276f3u,0x8a9e1196u,0x982bbe78u,0x2097d91du,
        0x78f4c94bu,0xc048ae2eu,0xd2fd01c0u,0x6a4166a5u,0xf7965e1cu,0x4f2a3979u,0x5d9f9697u,0xe523f1f2u,
        0x4d6b1905u,0xf5d77e60u,0xe762d18eu,0x5fdeb6ebu,0xc2098e52u,0x7ab5e937u,0x680046d9u,0xd0bc21bcu,
        0x88df31eau,0x3063568fu,0x22d6f961u,0x9a6a9e04u,0x07bda6bdu,0xbf01c1d8u,0xadb46e36u,0x15080953u,
        0x1d724e9au,0xa5ce29ffu,0xb77b8611u,0x0fc7e174u,0x9210d9cdu,0x2aacbea8u,0x38191146u,0x80a57623u,
        0xd8c66675u,0x607a0110u,0x72cfaefeu,0xca73c99bu,0x57a4f122u,0xef189647u,0xfdad39a9u,0x45115eccu,
        0x764dee06u,0xcef18963u,0xdc44268du,0x64f841e8u,0xf92f7951u,0x41931e34u,0x5326b1dau,0xeb9ad6bfu,
        0xb3f9c6e9u,0x0b45a18cu,0x19f00e62u,0xa14c6907u,0x3c9b51beu,0x842736dbu,0x96929935u,0x2e2efe50u,
        0x2654b999u,0x9ee8defcu,0x8c5d7112u,0x34e11677u,0xa9362eceu,0x118a49abu,0x033fe645u,0xbb838120u,
        0xe3e09176u,0x5b5cf613u,0x49e959fdu,0xf1553e98u,0x6c820621u,0xd43e6144u,0xc68bceaau,0x7e37a9cfu,
        0xd67f4138u,0x6ec3265du,0x7c7689b3u,0xc4caeed6u,0x591dd66fu,0xe1a1b10au,0xf3141ee4u,0x4ba87981u,
        0x13cb69d7u,0xab770eb2u,0xb9c2a15cu,0x017ec639u,0x9ca9fe80u,0x241599e5u,0x36a0360bu,0x8e1c516eu,
        0x866616a7u,0x3eda71c2u,0x2c6fde2cu,0x94d3b949u,0x090481f0u,0xb1b8e695u,0xa30d497bu,0x1bb12e1eu,
        0x43d23e48u,0xfb6e592du,0xe9dbf6c3u,0x516791a6u,0xccb0a91fu,0x740cce7au,0x66b96194u,0xde0506f1u,
    },
};
_Static_assert(sizeof(crc_slice4_table)==4096u,"video CRC table budget");
static uint32_t crc_update(uint32_t crc,const uint8_t *bytes,uint32_t count){
    while(count&&((uintptr_t)bytes&3u)){
        crc=(crc>>8)^crc_slice4_table[0][(crc^*bytes++)&255u];--count;
    }
    while(count>=4u){
        uint32_t word;
        __builtin_memcpy(&word,__builtin_assume_aligned(bytes,4),4);
        crc^=word;
        crc=crc_slice4_table[3][crc&255u]^crc_slice4_table[2][(crc>>8)&255u]^
            crc_slice4_table[1][(crc>>16)&255u]^crc_slice4_table[0][crc>>24];
        bytes+=4;count-=4;
    }
    while(count--)crc=(crc>>8)^crc_slice4_table[0][(crc^*bytes++)&255u];
    return crc;
}

static uint32_t checksum(const uint8_t*b,uint32_t n){return crc_update(~0u,b,n)^~0u;}
/* IPVF uses Rockbox's MSB-first CRC-32 state without a final XOR. */
#include "rockbox_crc_table.h"
static uint32_t rockbox_crc(uint32_t crc,const uint8_t*b,uint32_t n){return rockbox_crc_slice4(crc,b,n);}
static uint64_t divide64(uint64_t numerator,uint32_t denominator){
    uint64_t quotient=0;uint32_t remainder=0;if(!denominator)return 0;
    for(uint32_t bit=64;bit;--bit){uint32_t carry=remainder>>31;remainder=(remainder<<1)|(uint32_t)((numerator>>(bit-1u))&1u);if(carry||remainder>=denominator){remainder-=denominator;quotient|=(uint64_t)1u<<(bit-1u);}}return quotient;
}
static uint32_t frame_sample(uint32_t frame){
    uint32_t slot=frame&1u,bit=1u<<slot;
    if((v.time_valid&bit)&&v.time_frame[slot]==frame)return v.time_sample[slot];
    uint32_t sample=(uint32_t)divide64((uint64_t)frame*v.rate*v.fps_den+v.fps_num/2u,v.fps_num);
    v.time_frame[slot]=frame;v.time_sample[slot]=sample;v.time_valid|=bit;
    return sample;
}
static uint32_t sample_frame(uint32_t sample){
    /* Audio advances in DMA blocks while decode/PCM steps run many times.
     * Reuse exact timing conversions until their input changes. The cache
     * is cleared with the stream, so seeks retain the same time base. */
    if((v.time_valid&4u)&&v.time_clock==sample)return v.time_clock_frame;
    v.time_clock=sample;v.time_clock_frame=(uint32_t)divide64((uint64_t)sample*v.fps_num,v.rate*v.fps_den);
    v.time_valid|=4u;return v.time_clock_frame;
}
#include "ima_lookup.h"
static inline __attribute__((always_inline)) int16_t ima_nibble(uint32_t code,int32_t*predictor,uint32_t*index){
 uint32_t entry=ima_lookup[(*index<<3)|(code&7u)];
 int32_t difference=(int32_t)(entry>>8);
 int32_t sample=*predictor+(code&8u?-difference:difference);
 if(sample>32767)sample=32767;if(sample< -32768)sample=-32768;
 *predictor=sample;*index=entry&255u;return (int16_t)sample;
}
/* CRC(A || B) = shift(CRC(A), sizeof B) XOR CRC(B), for finalized
 * IEEE CRC32 values. All callers validate lengths against RECORD first.
 * Host-generated powers bound this to 17 matrices of at most 32 bits. */
static uint32_t crc_shift(uint32_t crc,uint32_t bytes){
    for(uint32_t power=0;bytes;bytes>>=1,++power){
        if(bytes&1u){
            uint32_t shifted=0,bit=0;
            while(crc){if(crc&1u)shifted^=video_crc_shift[power][bit];crc>>=1;++bit;}
            crc=shifted;
        }
    }
    return crc;
}
static uint32_t submit_pcm(const uint8_t *bytes,uint32_t frames){
    if(!((uintptr_t)bytes&1u)){
        if(frames>1024u)frames=1024u;
        return ln_audio_submit((const int16_t*)bytes,frames);
    }
    /* LZ4 payloads have arbitrary byte lengths. ARM7 halfword loads require
     * aligned PCM, so stage a small slice using explicit byte reads. The HAL
     * copies synchronously; partial/zero admission leaves record bytes intact
     * for retry. This uses bounded stack storage and adds no resident BSS. */
    int16_t pcm[128] __attribute__((aligned(4)));
    if(frames>64u)frames=64u;
    for(uint32_t i=0;i<frames*2u;i++)pcm[i]=(int16_t)r16(bytes+2u*i);
    return ln_audio_submit(pcm,frames);
}
static void fail(uint32_t e){v.error=e;v.stopping=true;++v.epoch;++v.revision;}
static uint32_t generation(void){if(++v.generation>=0x78000000u)v.generation=0x71000001u;return v.generation;}
static int io(uint32_t at,void*buf,uint32_t n,bool open){
    if(!v.pending){int r=open?ln_storage_media_open(v.path,generation()):ln_storage_media_read(&v.file,at,buf,n,generation());if(r<=0)return r;v.pending=true;v.requested=n;v.io_started=ln_time_us();return 0;}
    uint32_t got=0,started=ln_time_us();int r=0;
    /* FAT advances one small state/sector per poll, including cache hits.
     * Drain a bounded burst locally rather than paying a complete executive
     * round for every memory-only transition. Read polls use the video-owned
     * storage service; open polls retain the ordinary callback path. */
    for(uint32_t polls=0;polls<(open?64u:256u);polls++){
        r=open?ln_storage_media_poll(v.generation,&v.file,&got):
            ln_storage_media_poll_video(v.generation,0,&got);
        if(r||v.working!=v.epoch||ln_time_us()-started>=(open?250u:4000u))break;
    }
    if(!r)return 0;v.pending=false;
    if(v.working!=v.epoch)return 0;if(r!=1||(!open&&got!=v.requested))return -1;
    uint32_t elapsed=ln_time_us()-v.io_started;if(elapsed>v.max_io)v.max_io=elapsed;
    if(!open){++v.reads;v.read_bytes+=got;if(v.phase==READ)v.read_time+=elapsed;}return 1;
}
static int read_index(uint32_t frame){
    uint32_t offset=512+frame*32,page=offset&~511u;
    if(v.index_page_at!=page){v.index_page_at=NONE;int r=io(page,v.index_page,512,false);if(r!=1)return r;v.index_page_at=page;}
    copy(v.record.bytes,v.index_page+(offset&511u),32);return 1;
}
static bool pvid_header(void){
    const uint8_t*b=v.record.bytes;
    v.version=r16(b+4);
    if(r32(b)!=0x44495650u||(v.version!=1&&v.version!=2)||r16(b+6)!=512||r32(b+8)||r32(b+12)!=v.file.size||v.file.size>0x7fffffffu||r32(b+36)!=512||!zero(b+56,452)||checksum(b,508)!=r32(b+508))return false;
    v.width=r32(b+16);v.height=r32(b+20);v.fps=r32(b+24);v.count=r32(b+32);v.data_at=r32(b+40);v.max_record=r32(b+44);v.index_crc=r32(b+48);v.key_interval=r32(b+52);
    v.identity=r32(b+508);v.fps_num=v.fps;v.fps_den=1;v.rate=48000;
    if(!v.width||v.width>220||!v.height||v.height>176||(v.fps!=24&&v.fps!=25&&v.fps!=30&&v.fps!=60)||r32(b+28)!=48000||!v.count||v.count>1000000u||!v.key_interval||v.key_interval>v.fps*10u||v.max_record<512||v.max_record>PVID_RECORD||(v.max_record&511u))return false;
    return v.data_at==((512u+v.count*32u+511u)&~511u)&&v.data_at<v.file.size&&v.count<=UINT32_MAX/(48000u/v.fps);
}
static uint32_t staged_pcm(void){return v.pcm_head-v.pcm_tail;}
static void pump_ipvf_pcm(void){
    if(!v.ipvf||!v.ready||v.finish)return;
    uint32_t frames=staged_pcm(),offset=v.pcm_tail&(PCM_FRAMES-1u);
    if(frames>1024u)frames=1024u;
    if(frames>PCM_FRAMES-offset)frames=PCM_FRAMES-offset;
    if(frames)v.pcm_tail+=ln_audio_submit((const int16_t*)(PCM_BASE+offset),frames);
    /* All decoded samples must enter the HAL before it receives EOF. */
    if(v.prefetched_frames==v.count&&!staged_pcm()){
        ln_audio_finish();v.finish=true;
    }
}
static uint32_t submit_ipvf_pcm(void){
    uint32_t capacity=PCM_FRAMES-staged_pcm();if(!capacity)return 0;uint32_t frames=v.samples-v.at;if(frames>64u)frames=64u;if(frames>capacity)frames=capacity;
    const uint8_t*source=record_source()+16u+v.video_bytes;bool silence=!v.audio_bytes,mono=v.audio_bytes==4u+v.samples/2u;
    if(v.at==0u&&!silence){if((mono&&(source[3]||source[2]>88u))||(!mono&&(source[3]||source[7]||source[2]>88u||source[6]>88u)))return NONE;
        uint32_t left=r16(source);v.ima_left=left<0x8000u?(int32_t)left:(int32_t)left-0x10000;v.ima_left_index=source[2];
        if(mono){v.ima_right=v.ima_left;v.ima_right_index=v.ima_left_index;}else{uint32_t right=r16(source+4);v.ima_right=right<0x8000u?(int32_t)right:(int32_t)right-0x10000;v.ima_right_index=source[6];}}
    uint32_t head=v.pcm_head,i=0;
    if(silence){for(;i<frames;++i)PCM_BASE[(head+i)&(PCM_FRAMES-1u)]=0;}
    else{
        /* Keep the ADPCM state in registers throughout this bounded chunk. */
        int32_t left=v.ima_left,right=v.ima_right;
        uint32_t left_index=v.ima_left_index,right_index=v.ima_right_index;
        if(v.at==0u&&frames){PCM_BASE[head&(PCM_FRAMES-1u)]=(uint16_t)left|((uint32_t)(uint16_t)right<<16);i=1u;}
        if(mono){
            uint32_t nibble=v.at+i-1u;
            for(;i<frames;++i,++nibble){
                uint32_t code=(source[4u+(nibble>>1)]>>((nibble&1u)*4u))&15u;
                uint32_t sample=(uint16_t)ima_nibble(code,&left,&left_index);
                PCM_BASE[(head+i)&(PCM_FRAMES-1u)]=sample|(sample<<16);
            }
        }else{
            const uint8_t *packed=source+8u+v.at+i-1u;
            for(;i<frames;++i){
                uint32_t codes=*packed++;
                uint32_t l=(uint16_t)ima_nibble(codes&15u,&left,&left_index);
                uint32_t r=(uint16_t)ima_nibble(codes>>4,&right,&right_index);
                PCM_BASE[(head+i)&(PCM_FRAMES-1u)]=l|(r<<16);
            }
        }
        v.ima_left=left;v.ima_left_index=(uint8_t)left_index;
        v.ima_right=right;v.ima_right_index=(uint8_t)right_index;
    }
    v.pcm_head+=frames;return frames;
}
static int read_ipvf_index(uint32_t index){
    uint32_t offset=v.index_at+index*16u,page=offset&~511u;
    if(v.index_page_at!=page){v.index_page_at=NONE;uint32_t n=v.file.size-page;if(n>512u)n=512u;int r=io(page,v.index_page,n,false);if(r!=1)return r;v.index_page_at=page;}
    copy(v.record.bytes,v.index_page+(offset&511u),16);return 1;
}
static bool ipvf_index_record(const uint8_t*b){
    uint64_t offset=r64(b+4);uint32_t frame=r32(b),sectors=r16(b+12),flags=r16(b+14);
    return frame<v.count&&offset>=512u&&offset<v.media_end&&!(offset&511u)&&offset<=0x7fffffffu&&
        sectors&&sectors<=192u&&offset+(uint64_t)sectors*512u<=v.media_end&&!(flags&~1u);
}
static bool ipvf_header(void){
    const uint8_t*b=v.record.bytes;uint32_t flags=r32(b+20),metadata=r16(b+66),metadata_at=r32(b+68);
    uint64_t media_end=r64(b+44),index_at=r64(b+52),index_bytes=(uint64_t)r32(b+60)*16u;
    if(r32(b)!=0x46565049u||r16(b+4)!=80u||r16(b+6)!=220u||r16(b+8)!=176u||
       !r16(b+10)||!r16(b+12)||r16(b+10)<4u*r16(b+12)||r16(b+10)>240u*r16(b+12)||
       !r32(b+16)||(flags!=11u&&flags!=27u)||r32(b+24)!=512u||!r16(b+14)||r16(b+14)>192u||
       r16(b+28)!=2u||r16(b+30)!=2u||r16(b+32)!=16u||r32(b+34)!=44100u||r16(b+42)||
       media_end<=512u||media_end>0x7fffffffu||index_at!=media_end||index_at>v.file.size||
       !r32(b+60)||r32(b+60)>r32(b+16)||r16(b+64)!=16u||metadata_at!=80u||metadata>432u||
       index_bytes!=v.file.size-index_at)return false;
    uint64_t total=divide64((uint64_t)r32(b+16)*44100u*r16(b+12)+r16(b+10)/2u,r16(b+10));
    if(!total||total>0xffffffffu||r32(b+38)!=(uint32_t)total)return false;
    uint32_t tags=0,at=80,end=80u+metadata;while(at<end){if(end-at<2u)return false;uint32_t tag=b[at],n=b[at+1];
        if(tag<1u||tag>3u||!n||(tags&(1u<<tag))||n>end-at-2u)return false;tags|=1u<<tag;
        if(tag==1u){uint32_t take=n<127u?n:127u;copy(v.title,b+at+2u,take);v.title[take]=0;}at+=2u+n;}
    if(!zero(b+end,512u-end))return false;
    v.ipvf=true;v.temporal=(flags&16u)!=0;v.width=220;v.height=176;v.fps_num=r16(b+10);v.fps_den=r16(b+12);v.fps=v.fps_num/v.fps_den;
    v.preroll=(7u*v.fps_num+2u*v.fps_den-1u)/(2u*v.fps_den);
    if(v.preroll>VIDEO_PREROLL)v.preroll=VIDEO_PREROLL;if(v.preroll<2u)v.preroll=2u;
    v.rate=44100;v.count=r32(b+16);v.data_at=512;v.media_end=(uint32_t)media_end;v.index_at=(uint32_t)index_at;
    v.index_count=r32(b+60);v.index_crc=r32(b+72);v.identity=r32(b+76);v.first_sectors=r16(b+14);v.max_record=RECORD;
    return true;
}
static bool index_record(const uint8_t*b,uint32_t frame){
    uint32_t offset=r32(b),bytes=r32(b+4),key=r32(b+20);
    if(r32(b+8)!=frame||r32(b+12)!=frame*(48000u/v.fps)||r32(b+16)!=48000u/v.fps||key>frame||frame-key>=v.key_interval||r32(b+28)||offset<v.data_at||(offset&511u)||bytes<512||bytes>v.max_record||(bytes&511u)||offset>v.file.size||bytes>v.file.size-offset)return false;
    return (frame%v.key_interval)!=0||key==frame;
}
static void load_index(const uint8_t*b){v.offset=r32(b);v.bytes=r32(b+4);v.sample=r32(b+12);v.samples=r32(b+16);v.key=r32(b+20);v.record_crc=r32(b+24);}
static uint32_t free_slot(void){
    /* Build ownership once instead of rescanning the whole queue per slot. */
    uint32_t used[3]={0,0,0};
    if(v.front!=NONE)used[v.front>>5]|=1u<<(v.front&31u);
    if(v.previous!=NONE)used[v.previous>>5]|=1u<<(v.previous&31u);
    for(uint32_t q=0,at=v.qhead;q<v.qcount;++q){uint32_t s=v.queue[at];used[s>>5]|=1u<<(s&31u);if(++at==FRAME_SLOTS)at=0;}
    for(uint32_t s=0;s<(v.ipvf?FRAME_SLOTS:3u);++s)if(!(used[s>>5]&(1u<<(s&31u))))return s;
    return NONE;
}
static void present(struct ln_audio_status*a){
    uint32_t clock=v.origin+a->consumed;
    if(v.qcount&&!v.offered){uint32_t s=v.queue[v.qhead],sample=frame_sample(v.slot_frame[s]);
        if((!v.started&&v.front==NONE)||(v.started&&sample<=clock)){
            v.front=s;v.asset=(struct ln_ui_asset){v.width,v.height,frame_slot(s)};v.qhead=(v.qhead+1)%FRAME_SLOTS;--v.qcount;
#if !defined(LINNET_PROFILE_RELEASE)
            if(v.measurement==2u){
                ++v.presented;
                if(v.started&&clock>sample){uint32_t late=clock-sample;++v.late;if(late>v.max_late)v.max_late=late;}
                return;
            }
#endif
            v.offered=true;++v.revision;
        }
    }
}
static bool record_header(void){
    const uint8_t*b=v.record.bytes;v.type=r32(b+8);v.video_bytes=r32(b+12);v.frame_crc=r32(b+24);v.payload_crc=r32(b+28);
    if(r32(b)!=0x314d5246u||r32(b+4)!=v.next||r32(b+16)!=v.sample||r32(b+20)!=v.samples||v.type>(v.version==2?4u:3u)||v.video_bytes>v.bytes-32||v.samples*4u>v.bytes-32-v.video_bytes)return false;
    uint32_t used=32+v.video_bytes+v.samples*4u;if(((used+511u)&~511u)!=v.bytes||!zero(b+used,v.bytes-used))return false;
    bool key=v.type==0||v.type==3||v.type==4;
    if(key!=(v.key==v.next)||(!key&&v.previous==NONE))return false;
    if(v.type==0&&v.video_bytes!=v.width*v.height*2u)return false;
    if(v.type==1&&v.video_bytes)return false;
    if(v.type==2&&(v.video_bytes<4||!r32(b+32)))return false;
    if(v.type==3&&(!v.video_bytes||(v.video_bytes&3u)))return false;
    if(v.type==4&&(!v.video_bytes||v.video_bytes>=v.width*v.height*2u))return false;
    return true;
}
#define VIDEO_LZ_CODE __attribute__((noinline))
VIDEO_LZ_CODE void ln_video_lz_copy_long(uint8_t*write,uint32_t offset,uint32_t remaining){
        /* ARM7 cannot load unaligned words. Align only the destination,
         * then use aligned loads or explicit byte assembly for the source.
         * Each four-byte load completes before its store: offsets >=4 may
         * overlap across successive words, exactly as LZ forward copying. */
        typedef uint32_t match_word __attribute__((may_alias));
        const uint8_t*match=write-offset;
        while(((uintptr_t)write&3u)&&remaining){*write++=*match++;--remaining;}
        if(offset<=2u||offset==4u){
            uint32_t pattern;
            if(offset==4u)pattern=*(const match_word*)match;
            else {pattern=match[0];
                if(offset==2u)pattern|=(uint32_t)match[1]<<8;else pattern|=pattern<<8;
                pattern|=pattern<<16;}
            while(remaining>=16u){match_word*words=(match_word*)write;
                words[0]=pattern;words[1]=pattern;words[2]=pattern;words[3]=pattern;
                write+=16u;match+=16u;remaining-=16u;}
            while(remaining>=4u){*(match_word*)write=pattern;write+=4u;match+=4u;remaining-=4u;}
        }else if(remaining>=64u&&(offset==3u||!((uintptr_t)match&3u))){
            /* Preserve the ARM bulk copier for long aligned spans, growing
             * completed output only through disjoint source/destination runs. */
            uint32_t copied=offset<remaining?offset:remaining;copy(write,match,copied);
            while(copied<remaining){uint32_t n=copied;if(n>remaining-copied)n=remaining-copied;
                copy(write+copied,write,n);copied+=n;}
            write+=remaining;match+=remaining;remaining=0;
        }else if(offset>=4u){
            if(!((uintptr_t)match&3u)){
                while(remaining>=4u){*(match_word*)write=*(const match_word*)match;
                    write+=4u;match+=4u;remaining-=4u;}
            }else if(!((uintptr_t)match&1u)){
                typedef uint16_t match_half __attribute__((may_alias));
                while(remaining>=4u){const match_half *halves=(const match_half*)match;
                    uint32_t word=(uint32_t)halves[0]|((uint32_t)halves[1]<<16);
                    *(match_word*)write=word;write+=4u;match+=4u;remaining-=4u;}
            }else{
                while(remaining>=4u){uint32_t word=r32(match);*(match_word*)write=word;
                    write+=4u;match+=4u;remaining-=4u;}
            }
        }
        while(remaining){*write++=*match++;--remaining;}
}
/* Independent raw LZ4 blocks retain exact output and terminal bounds. Each
 * bounded block is completed in one pass; the caller owns its output slot. */
#if defined(__arm__)
extern int ln_video_lz_decode_block(const uint8_t*,uint32_t,uint8_t*,uint32_t);
#else
static VIDEO_LZ_CODE int ln_video_lz_decode_block(const uint8_t *in,uint32_t input_size,uint8_t *out,uint32_t size){
    const uint8_t *source=in,*input_end=in+input_size;
    uint8_t *destination=out,*output_end=out+size;bool matched=false;
    if(!input_size)return -1;
    for(;;){
        if(source>=input_end)return -1;
        uint32_t token=*source++,literal=token>>4;
        /* Common short sequences fit entirely inside the already bounded
         * block. Validate their combined input/output spans once. */
        if(literal<=2u&&(token&15u)<=4u&&(uint32_t)(input_end-source)>=literal+2u&&
           (uint32_t)(output_end-destination)>=literal+12u){
            uint32_t offset=r16(source+literal),length=4u+(token&15u);
            if(!offset||offset>(uint32_t)(destination-out)+literal)return -1;
            if(literal){destination[0]=source[0];if(literal==2u)destination[1]=source[1];}
            source+=literal+2u;destination+=literal;
            uint8_t*write=destination;const uint8_t*match=write-offset;
            write[0]=match[0];write[1]=match[1];write[2]=match[2];write[3]=match[3];
            if(length>4u)write[4]=match[4];
            if(length>5u)write[5]=match[5];
            if(length>6u)write[6]=match[6];
            if(length>7u)write[7]=match[7];
            destination+=length;matched=true;continue;
        }
        if(literal==15u){uint32_t extension;do{if(source>=input_end)return -1;extension=*source++;if(extension>size||literal>size-extension)return -1;literal+=extension;}while(extension==255u);}
        if(literal>(uint32_t)(input_end-source)||literal>(uint32_t)(output_end-destination))return -1;
        if(literal){
            /* Avoid the bulk copier's register save/restore for tiny tokens. */
            if(literal<=8u){for(uint32_t i=0;i<literal;++i)destination[i]=source[i];}
            else copy(destination,source,literal);
            source+=literal;destination+=literal;
        }
        if(source==input_end)return destination==output_end&&literal&&
            (literal>=5u||(!matched&&size<5u))?1:-1;
        if(input_end-source<2)return -1;
        uint32_t offset=r16(source);source+=2u;if(!offset||offset>(uint32_t)(destination-out))return -1;
        uint32_t length=token&15u;
        if(length==15u){uint32_t extension;do{if(source>=input_end)return -1;extension=*source++;if(extension>size||length>size-extension)return -1;length+=extension;}while(extension==255u);}
        if(size<4u||length>size-4u)return -1;length+=4u;
        if(length>(uint32_t)(output_end-destination)||(uint32_t)(output_end-destination)<12u)return -1;matched=true;
        /* Dense RGB565 footage produces mostly four-to-eight-byte matches.
         * Copy these directly, in forward order even for offsets 1..3,
         * without entering the alignment and bulk-copy machinery. */
        if(length<=8u){
            uint8_t*write=destination;const uint8_t*match=write-offset;
            write[0]=match[0];write[1]=match[1];write[2]=match[2];write[3]=match[3];
            if(length>4u)write[4]=match[4];
            if(length>5u)write[5]=match[5];
            if(length>6u)write[6]=match[6];
            if(length>7u)write[7]=match[7];
            destination+=length;continue;
        }
        ln_video_lz_copy_long(destination,offset,length);
        destination+=length;
    }
}
#endif
static int decode_lz4(void){
    uint8_t *out=v.lz_output_slot==NONE?IPVF_LZ_SCRATCH:
        v.lz_output_slot==2u?v.third.bytes:(uint8_t*)frame_slot(v.lz_output_slot);
    return ln_video_lz_decode_block(record_source()+v.lz_input_offset,v.lz_input_bytes,out,v.lz_output_bytes);
}
/* One bounded decode slice. Delta dependency always copies the immediately
 * previous prepared frame, even if its presentation deadline was missed. */
static int decode(void){
    if(v.type==4)return decode_lz4();
    uint8_t*b=v.record.bytes+32;uint16_t*out=frame_slot(v.building);uint32_t pixels=v.width*v.height;
    if(v.decode_pixel<pixels&&(v.type==0||v.type==1||v.type==2)){
        uint32_t n=pixels-v.decode_pixel;if(n>2048)n=2048;
        const uint16_t*in=v.type==0?(const uint16_t*)b:frame_slot(v.previous);copy(out+v.decode_pixel,in+v.decode_pixel,n*2);v.decode_pixel+=n;return 0;
    }
    if(v.type==0||v.type==1)return 1;
    if(v.type==3){uint32_t budget=2048;
        while(v.decode_at<v.video_bytes&&budget){uint32_t run=r16(b+v.decode_at),pixel=r16(b+v.decode_at+2);if(!run||run>pixels-v.decode_pixel)return -1;
            uint32_t n=run<budget?run:budget;for(uint32_t i=0;i<n;i++)out[v.decode_pixel++]=(uint16_t)pixel;budget-=n;
            if(n==run)v.decode_at+=4;else {run-=n;b[v.decode_at]=(uint8_t)run;b[v.decode_at+1]=(uint8_t)(run>>8);}
        }return v.decode_at==v.video_bytes?(v.decode_pixel==pixels?1:-1):0;
    }
    if(!v.decode_at){v.tile_count=r32(b);v.decode_at=4;v.tile_last=NONE;}
    uint32_t columns=(v.width+15)/16,rows=(v.height+15)/16;
    if(!v.tile_count)return v.decode_at==v.video_bytes?1:-1;
    if(v.decode_at+4>v.video_bytes)return -1;
    uint32_t tile=r16(b+v.decode_at);if(r16(b+v.decode_at+2)||tile>=columns*rows||(v.tile_last!=NONE&&tile<=v.tile_last))return -1;
    uint32_t x=(tile%columns)*16,y=(tile/columns)*16,w=v.width-x,h=v.height-y;if(w>16)w=16;if(h>16)h=16;
    if(w*h*2>v.video_bytes-v.decode_at-4)return -1;v.decode_at+=4;
    for(uint32_t row=0;row<h;row++){copy(out+(y+row)*v.width+x,b+v.decode_at,w*2);v.decode_at+=w*2;}
    v.tile_last=tile;--v.tile_count;return 0;
}
static bool raw_room(uint32_t bytes){return bytes<=RAW_CAPACITY-v.raw_used&&v.raw_count<RAW_ENTRIES;}
static void raw_store(void){
    uint32_t n=RAW_CAPACITY-v.raw_tail;if(n>v.bytes)n=v.bytes;
    if(!v.raw_write){copy(RAW_BASE+v.raw_tail,v.record.bytes,n);
        copy(RAW_BASE,v.record.bytes+n,v.bytes-n);}
    uint32_t slot=(v.raw_first+v.raw_count)%RAW_ENTRIES;
    v.raw[slot].frame=v.next;v.raw[slot].offset=v.offset;v.raw[slot].bytes=v.bytes;
    v.raw_tail=(v.raw_tail+v.bytes)%RAW_CAPACITY;v.raw_used+=v.bytes;++v.raw_count;
}
static bool raw_load(void){
    if(!v.raw_count)return false;
    uint32_t slot=v.raw_first;
    if(v.raw[slot].frame!=v.next||v.raw[slot].offset!=v.offset||v.raw[slot].bytes!=v.bytes)return false;
    uint32_t n=RAW_CAPACITY-v.raw_head;if(n>v.bytes)n=v.bytes;
    if(n==v.bytes)v.raw_view=RAW_BASE+v.raw_head;
    else{
        copy(v.record.bytes,RAW_BASE+v.raw_head,n);
        copy(v.record.bytes+n,RAW_BASE,v.bytes-n);
        v.raw_view=v.record.bytes;
    }
    /* Retain the descriptor and ring bytes until all video phases finish. */
    return true;
}
static void raw_release(void){
    if(!v.raw_view)return;
    uint32_t bytes=v.raw[v.raw_first].bytes;
    v.raw_view=0;
    v.raw_head=(v.raw_head+bytes)%RAW_CAPACITY;v.raw_used-=bytes;
    v.raw_first=(v.raw_first+1u)%RAW_ENTRIES;--v.raw_count;
}
static void audio_cursor_reset(void){
    v.raw_view=0;v.raw_write=0;
    v.prefetching=false;v.audio_yield=false;v.prefetched_frames=v.next;v.audio_offset=v.offset;v.audio_sectors=v.bytes/512u;
    v.raw_head=v.raw_tail=v.raw_used=v.raw_first=v.raw_count=0;
    v.pcm_head=v.pcm_tail=0;
}
static void audio_cursor_restore(void){
    v.raw_view=0;v.raw_write=0;
    v.next=v.video_next;v.offset=v.video_offset;v.bytes=v.video_bytes_saved;
    v.prefetching=false;v.audio_yield=true;v.building=NONE;v.phase=INDEX;
}
static bool ipvf_record_header(void){
    const uint8_t*b=record_source();uint64_t used;v.source_type=b[0];v.tile_count=b[1];v.next_sectors=r16(b+2);
    v.video_bytes=r32(b+4);v.decoded_bytes=r32(b+8);v.audio_bytes=r32(b+12);
    v.sample=frame_sample(v.next);v.samples=frame_sample(v.next+1u)-v.sample;
    if(!v.samples||v.video_bytes>RECORD||v.decoded_bytes>IPVF_PAYLOAD)return false;
    uint32_t mono=4u+v.samples/2u,stereo=8u+v.samples-1u;
    if(v.audio_bytes&&v.audio_bytes!=mono&&v.audio_bytes!=stereo)return false;
    used=16u+(uint64_t)v.video_bytes+v.audio_bytes;if(used>v.bytes||((used+511u)&~511u)!=v.bytes||!zero(b+(uint32_t)used,v.bytes-(uint32_t)used))return false;
    if((v.next+1u<v.count&&(!v.next_sectors||v.next_sectors>192u))||(v.next+1u==v.count&&v.next_sectors))return false;
    if(v.offset>v.media_end||v.bytes>v.media_end-v.offset||(v.next+1u==v.count&&v.offset+v.bytes!=v.media_end))return false;
    bool compressed=v.source_type==3u||v.source_type==4u||v.source_type==5u||v.source_type==6u;
    bool temporal=v.source_type==5u||v.source_type==6u;v.type=v.source_type==0u||v.source_type==3u||temporal?0u:v.source_type==1u||v.source_type==4u?1u:2u;
    if(v.source_type>6u||(v.next==0u&&v.type!=0u)||(v.seeking&&v.next==v.seek_frame&&v.source_type!=0u&&v.source_type!=3u)||(v.type==0u&&v.tile_count)||
       (v.type==1u&&(!v.tile_count||!v.decoded_bytes))||(v.type==2u&&(v.tile_count||v.video_bytes||v.decoded_bytes))||
       (v.type==0u&&v.decoded_bytes!=FRAME_BYTES)||
       (compressed&&(!v.video_bytes||v.video_bytes>=v.decoded_bytes))||(!compressed&&v.video_bytes!=v.decoded_bytes)||
       (temporal&&(!v.temporal||v.next==0u||v.video_bytes<(v.source_type==6u?7u:5u))))return false;
    v.lz_input_offset=16u;v.lz_input_bytes=v.video_bytes;v.lz_output_bytes=v.decoded_bytes;v.lz_output_slot=NONE;v.motion_dx=v.motion_dy=0;
    if(temporal){const uint8_t*p=b+16;if(v.source_type==6u){v.motion_dx=(int8_t)p[0];v.motion_dy=(int8_t)p[1];
            if(v.motion_dx<=-220||v.motion_dx>=220||v.motion_dy<=-176||v.motion_dy>=176)return false;v.lz_input_offset+=2u;v.lz_input_bytes-=2u;p+=2;}
        uint32_t expected=r32(p);v.lz_input_offset+=4u;v.lz_input_bytes-=4u;/* The FIFO retains immutable bytes already checked by the audio scan. */
        if(v.prefetching&&rockbox_crc(~0u,b+v.lz_input_offset,v.lz_input_bytes)!=expected)return false;}
    v.decode_at=v.decode_pixel=v.rect_row=0;v.rect_data_at=NONE;v.at=compressed?0u:1u;
    v.lz_state=v.lz_token=v.lz_remaining=v.lz_offset=v.lz_literal=v.lz_span=0;v.lz_matched=false;
    return true;
}
#if defined(__arm__)
extern void ln_video_copy_rgb565(uint16_t*,const uint8_t*,uint32_t);
#endif
static int decode_ipvf(void){
    bool compressed=v.source_type>=3u;if(compressed&&!v.at){
#if !defined(LINNET_PROFILE_RELEASE)
        uint32_t started=ln_time_us();
#endif
        int result=decode_lz4();
#if !defined(LINNET_PROFILE_RELEASE)
        v.lz_us+=ln_time_us()-started;
#endif
        if(result<=0)return result;v.at=1;v.decode_at=v.decode_pixel=0;}
    const uint8_t*payload=compressed?IPVF_LZ_SCRATCH:record_source()+16;uint16_t*out=frame_slot(v.building),*previous=frame_slot(v.previous);
    /* Rockbox completes one retained record in one decoder pass. IPVF's
     * strict 77,440-byte frame bound already limits this work; yielding for
     * every 2,048 pixels and every rectangle row inflated small updates into
     * dozens of runtime turns and prevented the audio cursor from advancing. */
    if(v.type==0u){
        /* Full frames and the LZ scratch start on four-byte boundaries. Swap
         * both big-endian RGB565 pixels in each ARM word without unaligned
         * loads; may_alias also permits accessing the uint16_t render slots. */
        typedef uint32_t pixel_pair __attribute__((may_alias));
        const pixel_pair*source=(const pixel_pair*)payload;
        pixel_pair*target=(pixel_pair*)out;
        if(v.source_type==5u){
            const pixel_pair*prediction=(const pixel_pair*)previous;
            for(uint32_t pair=0;pair<PIXELS/2u;++pair){uint32_t word=source[pair];
                target[pair]=prediction[pair]^((word&0x00ff00ffu)<<8)^((word&0xff00ff00u)>>8);}
        }else{
#if defined(__arm__)
            ln_video_copy_rgb565(out,payload,PIXELS);
#else
            for(uint32_t pair=0;pair<PIXELS/2u;++pair){uint32_t word=source[pair];
                target[pair]=((word&0x00ff00ffu)<<8)|((word&0xff00ff00u)>>8);}
#endif
            if(v.source_type==6u){
                /* Residual-only borders predict zero. Intersect translated
                 * source bounds once, then XOR only valid row spans. */
                uint32_t first_x=v.motion_dx>0?(uint32_t)v.motion_dx:0u;
                uint32_t last_x=v.motion_dx<0?(uint32_t)(220+v.motion_dx):220u;
                uint32_t first_y=v.motion_dy>0?(uint32_t)v.motion_dy:0u;
                uint32_t last_y=v.motion_dy<0?(uint32_t)(176+v.motion_dy):176u;
                for(uint32_t row=first_y;row<last_y;++row){
                    uint16_t*span=out+row*220u+first_x;
                    const uint16_t*prediction=previous+(uint32_t)((int32_t)row-v.motion_dy)*220u+
                        (uint32_t)((int32_t)first_x-v.motion_dx);
                    uint32_t width=last_x-first_x;
                    if(!(v.motion_dx&1)){
                        pixel_pair*destination=(pixel_pair*)span;
                        const pixel_pair*predicted=(const pixel_pair*)prediction;
                        for(uint32_t pair=0;pair<width/2u;++pair)destination[pair]^=predicted[pair];
                    }else for(uint32_t column=0;column<width;++column)span[column]^=prediction[column];
                }
            }
        }
        v.decode_pixel=PIXELS;return 1;
    }
    if(!v.decode_pixel){
        /* For one validated full-width rectangle, initialize only rows that
         * its conversion will leave untouched. The normal parser still runs. */
        bool full_width=v.type==1u&&v.tile_count==1u&&v.decoded_bytes>=8u&&
            !payload[0]&&payload[2]==220u&&payload[3]&&payload[1]+payload[3]<=176u&&
            v.decoded_bytes==8u+440u*payload[3]&&r32(payload+4u)==440u*payload[3];
        if(full_width){
            uint32_t top=payload[1],bottom=top+payload[3];
            if(top)copy(out,previous,top*440u);
            if(bottom<176u)copy(out+bottom*220u,previous+bottom*220u,(176u-bottom)*440u);
        }else copy(out,previous,FRAME_BYTES);
        v.decode_pixel=PIXELS;
    }
    if(v.type==2u)return 1;
#if !defined(__arm__)
    typedef uint16_t rect_pixel __attribute__((may_alias));
    typedef uint32_t rect_pair __attribute__((may_alias));
#endif
    while(v.tile_count){if(v.decode_at+8u>v.decoded_bytes)return -1;uint32_t x=payload[v.decode_at],y=payload[v.decode_at+1],w=payload[v.decode_at+2],h=payload[v.decode_at+3],bytes=r32(payload+v.decode_at+4);
        if(!w||!h||x+w>220u||y+h>176u||bytes!=w*h*2u||bytes>v.decoded_bytes-v.decode_at-8u)return -1;
        const uint8_t*source=payload+v.decode_at+8u;
#if defined(__arm__)
        if(w==220u)ln_video_copy_rgb565(out+y*220u,source,w*h);
        else for(uint32_t row=0;row<h;++row)
            ln_video_copy_rgb565(out+(y+row)*220u+x,source+row*w*2u,w);
#else
        for(uint32_t row=0;row<h;++row){
            uint16_t*target=out+(y+row)*220u+x;
            const rect_pixel*input=(const rect_pixel*)(source+row*w*2u);uint32_t remaining=w;
            /* Rectangle headers and pixels preserve halfword alignment.
             * Peel one destination pixel, then store aligned pixel pairs. */
            if((uintptr_t)target&2u){uint32_t pixel=*input++;*target++=(uint16_t)((pixel>>8)|(pixel<<8));--remaining;}
            rect_pair*pairs=(rect_pair*)target;
            if(!((uintptr_t)input&3u)){
                const rect_pair*words=(const rect_pair*)input;
                while(remaining>=2u){uint32_t word=*words++;
                    *pairs++=((word&0x00ff00ffu)<<8)|((word&0xff00ff00u)>>8);remaining-=2u;}
                input=(const rect_pixel*)words;
            }else{
                while(remaining>=2u){uint32_t word=(uint32_t)input[0]|((uint32_t)input[1]<<16);
                    *pairs++=((word&0x00ff00ffu)<<8)|((word&0xff00ff00u)>>8);input+=2u;remaining-=2u;}
            }
            if(remaining){uint32_t pixel=*input;*(uint16_t*)pairs=(uint16_t)((pixel>>8)|(pixel<<8));}
        }
#endif
        v.decode_at+=8u+bytes;--v.tile_count;
    }
    return v.decode_at==v.decoded_bytes?1:-1;
}
void ln_video_init(void){clear(&v,sizeof v);v.generation=0x71000000u;v.front=v.previous=v.building=v.index_page_at=NONE;v.min_audio=NONE;v.preroll=2u;}
bool ln_video_open(const char*path){
    if(v.active||v.pending||catalog.pending||!path||path[0]!='/')return false;uint32_t n=0;while(path[n]&&n<255)n++;if(!n||n==255)return false;
    uint32_t gen=v.generation,revision=v.revision;ln_video_init();v.generation=gen;v.revision=revision+1;copy(v.path,path,n+1);
#if !defined(LINNET_PROFILE_RELEASE)
    v.measurement=armed_measurement;armed_measurement=0;
    v.measurement_ran=v.measurement!=0;v.measurement_opened=ln_time_us();
#endif
    const char*name=path;for(uint32_t i=0;i<n;i++)if(path[i]=='/')name=path+i+1;
    uint32_t i=0;while(name[i]&&i<127){v.title[i]=name[i];i++;}v.title[i]=0;
    v.active=true;v.phase=OPEN;v.epoch=v.working=1;return true;
}
void ln_video_stop(void){if(v.active&&!v.stopping){v.stopping=true;++v.epoch;}}
bool ln_video_active(void){return v.active;}
bool ln_video_pending(void){return v.pending||catalog.pending;}
bool ln_video_paused(void){return v.paused;}
void ln_video_pause(bool pause){if(!v.active||v.stopping)return;v.paused=pause;if(v.started){if(pause)ln_audio_pause();else if(!ln_audio_start())fail(13);}++v.revision;}
bool ln_video_seek(int32_t seconds){
#if !defined(LINNET_PROFILE_RELEASE)
    if(v.measurement)return false;
#endif
    if(!v.ready||v.stopping)return false;struct ln_audio_status a;ln_audio_snapshot(&a);int64_t frame=(int64_t)sample_frame(v.origin+a.consumed)+(int64_t)(seconds*(int32_t)v.fps_num/(int32_t)v.fps_den);
    if(frame<0)frame=0;if(frame>=v.count)frame=v.count-1;v.target=(uint32_t)frame;v.seeking=true;++v.epoch;return true;
}
static void step(void){
    if(!v.active)return;
#if !defined(LINNET_PROFILE_RELEASE)
    /* The one-shot starts at frame zero and stops after eight seconds of
     * playback, or eight seconds of preparation if audio never starts. */
    if(v.measurement&&ln_time_us()-(v.started?v.measurement_started:v.measurement_opened)>=8000000u)
        ln_video_stop();
#endif
    if(v.working!=v.epoch){
        if(v.pending){ln_storage_media_cancel(v.generation);if(!ln_storage_media_poll_video(v.generation,0,0))return;v.pending=false;}
        v.working=v.epoch;
        if(!ln_audio_stop()){v.error=13;v.stopping=true;--v.working;return;}
        v.pcm_head=v.pcm_tail=0;v.raw_view=0;v.raw_write=0;
        if(v.stopping){v.active=false;v.phase=IDLE;++v.revision;
#if !defined(LINNET_PROFILE_RELEASE)
            v.measurement=0;
#endif
            return;}
        v.front=v.previous=v.building=NONE;v.qhead=v.qcount=v.submitted=0;v.started=v.finish=v.offered=false;v.prefetching=false;v.prefetched_frames=0;v.seek_index=0;v.seek_frame=0;v.seek_offset=512;v.seek_sectors=v.first_sectors;v.index_page_at=NONE;v.phase=SEEK;++v.revision;
    }
    pump_ipvf_pcm();
    struct ln_audio_status a;ln_audio_snapshot(&a);
    if(v.started){v.resume_frame=sample_frame(v.origin+a.consumed);if(v.resume_frame>=v.count)v.resume_frame=v.count-1;v.audio_gaps=a.underruns;v.audio_silence=a.silence_frames;v.audio_fault=a.fault;if(a.queued<v.min_audio)v.min_audio=a.queued;if(a.fault){fail(13);return;}}
    present(&a);
    /* Hand a due frame to the renderer before starting another read/decode. */
    if(v.offered)return;
    if(v.ready&&!v.started&&!v.paused&&v.front!=NONE&&a.queued&&((v.qcount+1u)>=v.preroll||(!v.prefetching&&v.next==v.count))){
        if(!ln_audio_start()){fail(13);return;}v.started=true;++v.revision;
#if !defined(LINNET_PROFILE_RELEASE)
        v.measurement_started=ln_time_us();
        v.start_ready=v.qcount+1u;v.min_ready=v.qcount;v.last_present_us=0;
#endif
    }
    int r;uint8_t*b=v.record.bytes;
    switch(v.phase){
    case OPEN:r=io(0,0,0,true);if(r<0)fail(1);else if(r==1)v.phase=HEADER;return;
    case HEADER:r=io(0,b,512,false);if(r<0){fail(2);return;}if(!r)return;
        if(r32(b)==0x46565049u){if(!ipvf_header()){fail(3);return;}v.verify_at=v.index_at;v.verify_end=0;v.verify_frame=0;}
        else {if(!pvid_header()){fail(3);return;}v.verify_at=512;v.verify_end=v.data_at;v.verify_key=0;}
        v.verify_crc=~0u;v.phase=VERIFY;return;
    case VERIFY:{uint32_t end=v.ipvf?v.file.size:v.data_at,n=end-v.verify_at;if(n>4096)n=4096;r=io(v.verify_at,b,n,false);if(r<0){fail(4);return;}if(!r)return;
        if(v.ipvf)v.verify_crc=rockbox_crc(v.verify_crc,b,n);else v.verify_crc=crc_update(v.verify_crc,b,n);
        for(uint32_t at=0;at<n;at+=v.ipvf?16u:32u){if(v.ipvf){if(!ipvf_index_record(b+at)){fail(5);return;}uint32_t frame=r32(b+at);uint64_t offset=r64(b+at+4);
                if((!v.verify_frame&&(frame||offset!=512u))||(v.verify_frame&&(frame<=v.verify_key||offset<=v.verify_end))){fail(5);return;}v.verify_key=frame;v.verify_end=(uint32_t)offset;++v.verify_frame;
            }else if(v.verify_frame<v.count){if(!index_record(b+at,v.verify_frame)||r32(b+at)!=v.verify_end){fail(5);return;}
                uint32_t key=r32(b+at+20),bytes=r32(b+at+4);if(key!=v.verify_frame&&key!=v.verify_key){fail(5);return;}v.verify_key=key;v.verify_end+=bytes;if(bytes>v.verify_max)v.verify_max=bytes;++v.verify_frame;
            }else if(!zero(b+at,32)){fail(5);return;}}
        v.verify_at+=n;if(v.verify_at==end){if((v.ipvf?(v.verify_crc!=v.index_crc||v.verify_frame!=v.index_count):((v.verify_crc^~0u)!=v.index_crc||v.verify_end!=v.file.size||v.verify_max!=v.max_record))){fail(6);return;}
            v.ready=true;
            bool resume=saved_resume[0]==v.identity&&saved_resume[1]<v.count;
#if !defined(LINNET_PROFILE_RELEASE)
            if(v.measurement)resume=false;
#endif
            if(resume){v.target=saved_resume[1];v.seeking=true;v.seek_index=0;v.phase=SEEK;}
            else {if(!ln_audio_init(v.rate)){fail(13);return;}v.next=0;v.offset=512;v.bytes=v.ipvf?v.first_sectors*512u:0;v.origin=0;
                audio_cursor_reset();v.phase=INDEX;}}return;}
    case SEEK:
        if(v.ipvf){if(v.seek_index<v.index_count){r=read_ipvf_index(v.seek_index);if(r<0){fail(7);return;}if(!r)return;if(!ipvf_index_record(b)){fail(7);return;}
                uint32_t frame=r32(b);if(frame<=v.target){v.seek_frame=frame;v.seek_offset=(uint32_t)r64(b+4);v.seek_sectors=r16(b+12);++v.seek_index;return;}}
            v.next=v.seek_frame;v.offset=v.seek_offset;v.bytes=v.seek_sectors*512u;v.resume_frame=v.target;v.origin=frame_sample(v.target);if(!ln_audio_init(v.rate)){fail(13);return;}audio_cursor_reset();v.phase=INDEX;return;}
        r=read_index(v.target);if(r<0){fail(7);return;}if(!r)return;if(!index_record(b,v.target)){fail(7);return;}
        v.next=r32(b+20);v.resume_frame=v.target;v.origin=frame_sample(v.target);if(!ln_audio_init(v.rate)){fail(13);return;}v.phase=INDEX;return;
    case INDEX:
        /* Retire the previous video record before the audio producer runs. */
        raw_release();v.raw_write=0;
        /* Audio owns a forward record cursor independently of render slots.
         * Retaining every scanned record keeps storage reads strictly forward.
         * Count both software staging and the HAL toward the four-second
         * decoded cushion. Keep refilling below four seconds so audio stays
         * ahead of the decoded video queue during expensive scenes. */
        if(v.ipvf&&!v.prefetching&&!v.audio_yield&&v.prefetched_frames<v.count&&
           (!v.submitted||a.queued+staged_pcm()<4u*v.rate||v.next>=v.prefetched_frames)&&
           raw_room(v.audio_sectors*512u)){
            v.video_next=v.next;v.video_offset=v.offset;v.video_bytes_saved=v.bytes;
            v.next=v.prefetched_frames;v.offset=v.audio_offset;v.bytes=v.audio_sectors*512u;v.prefetching=true;
        }
        v.audio_yield=false;
        if(v.next>=v.count){if(!v.finish&&(!v.ipvf||!staged_pcm())){ln_audio_finish();v.finish=true;}v.phase=WAIT;return;}
        if(!v.prefetching){v.building=free_slot();if(v.building==NONE)return;}
        if(!v.ipvf){r=read_index(v.next);if(r<0){fail(7);return;}if(!r)return;if(!index_record(b,v.next)){fail(7);return;}load_index(b);}v.at=0;v.read_time=0;clear(v.cpu,sizeof v.cpu);v.prepare_start=ln_time_us();v.phase=READ;return;
    case READ:{if(v.ipvf&&v.prefetching){
            if(!v.pending&&!v.at&&raw_room(v.bytes)&&v.bytes<=RAW_CAPACITY-v.raw_tail)v.raw_write=RAW_BASE+v.raw_tail;
            if(v.raw_write)b=v.raw_write;
        }if(v.ipvf&&!v.prefetching){
            if(!raw_load()){fail(8);return;}v.at=0;v.phase=CRC;return;
        }uint32_t n=v.bytes-v.at;r=io(v.offset+v.at,b+v.at,n,false);if(r<0){fail(8);return;}if(!r)return;v.at+=n;if(v.at==v.bytes){if(v.read_time>v.max_read_time)v.max_read_time=v.read_time;v.at=0;v.crc=~0u;v.phase=CRC;}return;}
    case CRC:{
        if(v.ipvf){if(!ipvf_record_header()){fail(9);return;}if(v.prefetching){if(!raw_room(v.bytes)){fail(8);return;}raw_store();v.at=0;v.phase=PCM;}else v.phase=DECODE;return;}
        if(!record_header()){fail(9);return;}
        uint32_t used=32u+v.video_bytes+v.samples*4u;
        /* Validate bounds and zero padding before using any declared lengths.
         * Compute the actual header and padding contribution once. The payload
         * scan below completes the exact whole-record CRC before any decode. */
        v.record_edges_crc=crc_shift(checksum(b,32u),v.bytes-32u)^checksum(b+used,v.bytes-used);
        v.at=0;v.crc=~0u;v.decode_at=v.decode_pixel=0;
        v.lz_state=v.lz_token=v.lz_remaining=v.lz_offset=v.lz_literal=v.lz_span=0;v.lz_matched=false;
        v.lz_input_offset=32u;v.lz_input_bytes=v.video_bytes;v.lz_output_bytes=v.width*v.height*2u;v.lz_output_slot=v.building;
        v.phase=DECODE;return;}
    case DECODE:
        if(v.ipvf){r=decode_ipvf();if(r<0){fail(11);return;}if(r==1){v.at=0;v.phase=FRAME_CRC;}return;}
        if(v.at<v.video_bytes+v.samples*4u){
            uint32_t payload=v.video_bytes+v.samples*4u,n=payload-v.at;if(n>4096)n=4096;
            v.crc=crc_update(v.crc,b+32+v.at,n);v.at+=n;
            if(v.at==payload){
                uint32_t observed=v.crc^~0u;
                if((v.record_edges_crc^crc_shift(observed,v.bytes-32u-payload))!=v.record_crc){fail(9);return;}
                if(observed!=v.payload_crc)fail(10);
            }
            return;
        }
        r=decode();if(r<0){fail(11);return;}if(r==1){v.at=0;v.crc=~0u;v.phase=FRAME_CRC;}return;
    case FRAME_CRC:{
        if(v.ipvf){}
        else if(v.type==1){if(v.frame_crc!=v.previous_crc){fail(12);return;}}
        else {uint32_t n=v.width*v.height*2-v.at;if(n>4096)n=4096;v.crc=crc_update(v.crc,(uint8_t*)frame_slot(v.building)+v.at,n);v.at+=n;if(v.at!=v.width*v.height*2)return;if((v.crc^~0u)!=v.frame_crc){fail(12);return;}}
        v.previous_crc=v.frame_crc;v.previous=v.building;++v.prepared;
        uint32_t elapsed=ln_time_us()-v.prepare_start;if(elapsed>v.max_prepare)v.max_prepare=elapsed;
        if(v.seeking&&v.next<v.target){if(v.ipvf){v.offset+=v.bytes;v.bytes=v.next_sectors*512u;}++v.next;v.phase=INDEX;return;}
        v.seeking=false;v.at=0;v.phase=PCM;return;}
    case PCM:{
        uint32_t sent;
        if(v.ipvf&&((!v.prefetching&&v.next<v.prefetched_frames)||(v.prefetching&&v.seeking&&v.next<v.target)))sent=v.samples-v.at;
        else sent=v.ipvf?submit_ipvf_pcm():submit_pcm(b+32+v.video_bytes+4u*v.at,v.samples-v.at);
        if(sent==NONE){fail(13);return;}v.at+=sent;if((v.prefetching&&(!v.seeking||v.next>=v.target))||!v.ipvf)v.submitted+=sent;if(v.at!=v.samples)return;
        if(v.prefetching){v.offset+=v.bytes;v.bytes=v.next_sectors*512u;++v.next;v.prefetched_frames=v.next;
            v.audio_offset=v.offset;v.audio_sectors=v.next_sectors;
            struct ln_audio_status queued;ln_audio_snapshot(&queued);
            /* Once audio runs, return to video after each retained record. */
            if(v.next<v.count&&queued.queued+staged_pcm()<4u*v.rate&&raw_room(v.bytes)&&!v.started){v.phase=INDEX;return;}
            audio_cursor_restore();return;}
        v.slot_frame[v.building]=v.next;v.queue[(v.qhead+v.qcount)%FRAME_SLOTS]=v.building;++v.qcount;if(v.qcount>v.max_queue)v.max_queue=v.qcount;
        if(v.ipvf){v.offset+=v.bytes;v.bytes=v.next_sectors*512u;}++v.next;v.phase=INDEX;return;}
    case WAIT:if(v.started&&!v.paused&&!a.queued&&!staged_pcm()&&!v.qcount&&!v.offered){if(!ln_audio_stop()){fail(13);return;}v.resume_frame=0;v.completed=true;v.active=false;v.phase=IDLE;++v.revision;
#if !defined(LINNET_PROFILE_RELEASE)
        v.measurement=0;
#endif
        }return;
    default:return;
    }
}
void ln_video_step(void){
    catalog_step();
    if(v.stepping)return;v.stepping=true;uint32_t batch_started=ln_time_us();
    for(uint32_t slices=0;slices<64u;slices++){
        uint32_t started=ln_time_us(),phase=v.phase,at=v.at,next=v.next,revision=v.revision,epoch=v.epoch;
        uint32_t decode_at=v.decode_at,decode_pixel=v.decode_pixel,tile_count=v.tile_count;
        uint32_t stage=phase==CRC?0:phase==DECODE?(v.at<v.video_bytes+v.samples*4u?1:2):phase==FRAME_CRC?3:NONE;
        step();uint32_t elapsed=ln_time_us()-started;
#if !defined(LINNET_PROFILE_RELEASE)
        if(phase<=SEEK){v.phase_us[phase]+=elapsed;++v.phase_calls[phase];}
        if(phase==DECODE&&v.ipvf&&v.source_type<7u){v.type_us[v.source_type]+=elapsed;++v.type_calls[v.source_type];}
#endif
        if(stage!=NONE){v.cpu[stage]+=elapsed;if(v.cpu[stage]>v.max_cpu[stage])v.max_cpu[stage]=v.cpu[stage];}
        if(!v.active||v.pending||v.offered||ln_time_us()-batch_started>=4000u)break;
        /* Copy/RLE/delta slices advance decoder cursors without changing at.
         * They are finite progress and may use the remaining batch budget. */
        if(phase==v.phase&&at==v.at&&next==v.next&&revision==v.revision&&epoch==v.epoch&&
           decode_at==v.decode_at&&decode_pixel==v.decode_pixel&&tile_count==v.tile_count)break;
    }
    uint32_t elapsed=ln_time_us()-batch_started;if(elapsed>v.max_step)v.max_step=elapsed;
    v.stepping=false;
}
uint32_t ln_video_progress(void){if(v.completed)return 1000;if(!v.count||!v.fps)return 0;return v.resume_frame*1000u/v.count;}
const char*ln_video_title(void){return v.title;}
const char*ln_video_status(void){return v.error?"Video unavailable":v.stopping?"Stopping video":!v.active?"Finished":v.seeking?"Seeking":v.paused?"Paused":v.started?"Playing":"Loading video";}
const struct ln_ui_asset*ln_video_asset(void){
#if !defined(LINNET_PROFILE_RELEASE)
    if(v.measurement_ran&&v.measurement!=1u)return 0;
#endif
    return v.front==NONE?0:&v.asset;
}
uint32_t ln_video_revision(void){return v.revision;}
void ln_video_presented(void){
    if(!v.offered||v.front==NONE)return;v.offered=false;++v.presented;
    if(v.started){struct ln_audio_status a;ln_audio_snapshot(&a);uint32_t clock=v.origin+a.consumed,sample=frame_sample(v.slot_frame[v.front]);
        if(clock>sample){uint32_t late=clock-sample;++v.late;
#if !defined(LINNET_PROFILE_RELEASE)
            uint32_t duration=frame_sample(v.slot_frame[v.front]+1u)-sample;
            if(late>duration)++v.late_one;if(late>2u*duration)++v.late_two;
            if(late>v.max_late){v.worst_frame=v.slot_frame[v.front];v.worst_queue=v.qcount;}
#endif
            if(late>v.max_late)v.max_late=late;}
#if !defined(LINNET_PROFILE_RELEASE)
        uint32_t now=ln_time_us();if(v.last_present_us){uint32_t gap=now-v.last_present_us;if(gap>v.max_gap_us){v.max_gap_us=gap;v.gap_frame=v.slot_frame[v.front];}}
        v.last_present_us=now;if(v.next<v.count&&v.qcount<v.min_ready)v.min_ready=v.qcount;
#endif
    }
}
void ln_video_resume_get(uint32_t out[2]){
#if !defined(LINNET_PROFILE_RELEASE)
    if(v.measurement_ran){out[0]=saved_resume[0];out[1]=saved_resume[1];return;}
#endif
    if(v.ready){out[0]=v.identity;out[1]=v.resume_frame;}else{out[0]=saved_resume[0];out[1]=saved_resume[1];}}
void ln_video_resume_set(const uint32_t in[2]){saved_resume[0]=in[0];saved_resume[1]=in[1];}
static bool paused_quiescent(void){
    return v.active&&v.paused&&!v.pending&&!v.stopping&&!v.seeking&&v.working==v.epoch&&
        v.phase==INDEX&&v.next<v.count&&v.front!=NONE&&!v.offered&&free_slot()==NONE;
}
uint32_t ln_video_deadline(uint32_t now){
    if(!v.active)return now+200000u;
    /* A settled pause with all decoded slots owned has no read/decode work to
     * advance. Input IRQs, executive deadlines and the watchdog cap still
     * bound the sleep; transition, cancel and seek states remain runnable. */
    if(paused_quiescent())return now+200000u;
    if(v.pending||v.phase==WAIT||(v.phase==INDEX&&free_slot()==NONE))return now+1000u;
    return now;
}
/* submitted is decoded audio admitted to software staging for IPVF;
 * the audio HAL diagnostics retain the count actually admitted to DMA. */
void ln_video_diagnostics(uint32_t out[32]){uint32_t a[32]={0x36544956u,2,v.phase,v.error,v.active,v.pending,v.paused,v.next,v.count,v.front==NONE?NONE:v.slot_frame[v.front],v.reads,v.read_bytes,v.prepared,v.presented,v.late,v.max_late,v.max_prepare,v.qcount,v.max_queue,v.audio_gaps,v.audio_silence,v.audio_fault,v.submitted,v.revision,v.max_io,v.max_read_time,v.max_cpu[0],v.max_cpu[1],v.max_cpu[2],v.max_cpu[3],v.max_step,v.min_audio};for(uint32_t i=0;i<32;i++)out[i]=a[i];}
