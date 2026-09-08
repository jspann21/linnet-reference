#include "video.h"
#include "services/storage/storage.h"
#include "hal/pp5020/audio.h"
#include "hal/pp5020/platform.h"
#define PIXELS (220u*176u)
#define RECORD 90112u
#define NONE 0xffffffffu
#include "crc_shift_table.h"
_Static_assert(RECORD<(1u<<17),"video CRC shift length bound");
enum phase {IDLE,OPEN,HEADER,VERIFY,INDEX,READ,CRC,DECODE,FRAME_CRC,PCM,WAIT,SEEK};
static struct {
    uint16_t frame[3][PIXELS];
    union {uint32_t align;uint8_t bytes[RECORD];} record;
    uint8_t index_page[512];
    struct ln_fat32_file file;struct ln_ui_asset asset;
    char path[256],title[128];
    uint32_t phase,error,epoch,working,generation,requested,revision;
    uint32_t version,width,height,fps,count,data_at,max_record,key_interval,index_crc;
    uint32_t verify_at,verify_crc,verify_frame,verify_end,verify_key,verify_max;
    uint32_t next,target,origin,offset,bytes,sample,samples,key,record_crc;
    uint32_t type,video_bytes,payload_crc,frame_crc,at,crc,record_edges_crc,decode_at,decode_pixel,tile_count,tile_last;
    uint32_t front,previous,building,queue[3],qhead,qcount,slot_frame[3],submitted;
    uint32_t reads,read_bytes,prepared,presented,late,max_late,max_prepare,prepare_start,max_queue;
    uint32_t audio_gaps,audio_silence,audio_fault,identity,resume_frame;
    uint32_t index_page_at,previous_crc,io_started,max_io,read_time,max_read_time;
    uint32_t cpu[4],max_cpu[4],max_step,min_audio;
    uint32_t lz_state,lz_token,lz_remaining,lz_offset,lz_literal,lz_span;
    bool lz_matched;
#if !defined(LINNET_PROFILE_RELEASE)
    uint32_t measurement,measurement_opened,measurement_started;
    bool measurement_ran;
#endif
    bool active,pending,stepping,stopping,ready,started,paused,finish,seeking,offered,completed;
} v;
static uint32_t saved_resume[2];
#if !defined(LINNET_PROFILE_RELEASE)
static uint32_t armed_measurement;
bool ln_video_measurement_arm(uint32_t mode){
    if(mode>2u||v.active||v.pending)return false;
    armed_measurement=mode;return true;
}
#endif
static uint32_t r32(const uint8_t*b){return b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;}
static uint32_t r16(const uint8_t*b){return b[0]|(uint32_t)b[1]<<8;}
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
static bool zero(const uint8_t*p,uint32_t n){while(n--)if(*p++)return false;return true;}
/* Host research candidate. Replaces the existing 1KiB byte table with4KiB.
 * Same reflected IEEE CRC state; little-endian PP5020. No production edits. */
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
    for(uint32_t polls=0;polls<64u;polls++){
        r=open?ln_storage_media_poll(v.generation,&v.file,&got):
            ln_storage_media_poll_video(v.generation,0,&got);
        if(r||v.working!=v.epoch||ln_time_us()-started>=250u)break;
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
static bool header(void){
    const uint8_t*b=v.record.bytes;
    v.version=r16(b+4);
    if(r32(b)!=0x44495650u||(v.version!=1&&v.version!=2)||r16(b+6)!=512||r32(b+8)||r32(b+12)!=v.file.size||v.file.size>0x7fffffffu||r32(b+36)!=512||!zero(b+56,452)||checksum(b,508)!=r32(b+508))return false;
    v.width=r32(b+16);v.height=r32(b+20);v.fps=r32(b+24);v.count=r32(b+32);v.data_at=r32(b+40);v.max_record=r32(b+44);v.index_crc=r32(b+48);v.key_interval=r32(b+52);
    v.identity=r32(b+508);
    if(!v.width||v.width>220||!v.height||v.height>176||(v.fps!=24&&v.fps!=25&&v.fps!=30&&v.fps!=60)||r32(b+28)!=48000||!v.count||v.count>1000000u||!v.key_interval||v.key_interval>v.fps*10u||v.max_record<512||v.max_record>RECORD||(v.max_record&511u))return false;
    return v.data_at==((512u+v.count*32u+511u)&~511u)&&v.data_at<v.file.size&&v.count<=UINT32_MAX/(48000u/v.fps);
}
static bool index_record(const uint8_t*b,uint32_t frame){
    uint32_t offset=r32(b),bytes=r32(b+4),key=r32(b+20);
    if(r32(b+8)!=frame||r32(b+12)!=frame*(48000u/v.fps)||r32(b+16)!=48000u/v.fps||key>frame||frame-key>=v.key_interval||r32(b+28)||offset<v.data_at||(offset&511u)||bytes<512||bytes>v.max_record||(bytes&511u)||offset>v.file.size||bytes>v.file.size-offset)return false;
    return (frame%v.key_interval)!=0||key==frame;
}
static void load_index(const uint8_t*b){v.offset=r32(b);v.bytes=r32(b+4);v.sample=r32(b+12);v.samples=r32(b+16);v.key=r32(b+20);v.record_crc=r32(b+24);}
static uint32_t free_slot(void){for(uint32_t s=0;s<3;s++){bool used=s==v.front||s==v.previous;for(uint32_t q=0;q<v.qcount;q++)if(v.queue[(v.qhead+q)%3]==s)used=true;if(!used)return s;}return NONE;}
static void present(struct ln_audio_status*a){
    uint32_t clock=v.origin+a->consumed;
    if(v.qcount&&!v.offered){uint32_t s=v.queue[v.qhead],sample=v.slot_frame[s]*(48000u/v.fps);
        if((!v.started&&v.front==NONE)||(v.started&&sample<=clock)){
            v.front=s;v.asset=(struct ln_ui_asset){v.width,v.height,v.frame[s]};v.qhead=(v.qhead+1)%3;--v.qcount;
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
/* Independent raw LZ4 blocks, with IPVF's exact output/terminal bounds.
 * Both length scanning and copying yield after a finite byte budget. No
 * dictionary or scratch frame is needed; only the unoffered building slot is
 * written. decode_pixel counts bytes for this record type. */
static int decode_lz4(void){
    const uint8_t *in=v.record.bytes+32;uint8_t *out=(uint8_t*)v.frame[v.building];
    uint32_t size=v.width*v.height*2u,budget=2048;
    while(budget){
        switch(v.lz_state){
        case 0:
            if(v.decode_at==v.video_bytes)return -1;
            v.lz_token=in[v.decode_at++];--budget;v.lz_remaining=v.lz_token>>4;
            v.lz_state=v.lz_remaining==15?1:2;v.lz_literal=v.lz_remaining;break;
        case 1:case 4:{
            if(v.decode_at==v.video_bytes)return -1;
            uint32_t extension=in[v.decode_at++];--budget;
            if(v.lz_remaining>size||extension>size-v.lz_remaining)return -1;
            v.lz_remaining+=extension;
            if(extension!=255){if(v.lz_state==1){v.lz_literal=v.lz_remaining;v.lz_state=2;}
                else {if(v.lz_remaining>size-4u)return -1;v.lz_remaining+=4;v.lz_state=5;}}
            break;}
        case 2:{
            if(v.lz_remaining>v.video_bytes-v.decode_at||v.lz_remaining>size-v.decode_pixel)return -1;
            if(v.lz_remaining){uint32_t n=v.lz_remaining;if(n>budget)n=budget;
                copy(out+v.decode_pixel,in+v.decode_at,n);v.decode_at+=n;v.decode_pixel+=n;v.lz_remaining-=n;budget-=n;
                if(v.lz_remaining)break;}
            if(v.decode_at==v.video_bytes)return v.decode_pixel==size&&v.lz_literal&&
                (v.lz_literal>=5u||(!v.lz_matched&&size<5u))?1:-1;
            v.lz_state=3;break;}
        case 3:
            if(v.video_bytes-v.decode_at<2u)return -1;
            if(budget<2u)return 0;
            v.lz_offset=r16(in+v.decode_at);v.decode_at+=2;budget-=2;
            if(!v.lz_offset||v.lz_offset>v.decode_pixel||size<12u||v.decode_pixel>size-12u)return -1;
            v.lz_matched=true;v.lz_span=v.lz_offset;v.lz_remaining=v.lz_token&15u;
            if(v.lz_remaining==15u)v.lz_state=4;
            else {v.lz_remaining+=4;v.lz_state=5;}break;
        case 5:{
            if(v.lz_remaining>size-v.decode_pixel)return -1;
            /* The span is an offset multiple backed by materialized bytes.
             * Double only after a complete disjoint period copy; a partial
             * budget retains the valid span. This avoids software division. */
            uint32_t span=v.lz_span;
            uint32_t n=v.lz_remaining;if(n>budget)n=budget;if(n>span)n=span;
            copy(out+v.decode_pixel,out+v.decode_pixel-span,n);
            v.decode_pixel+=n;if(n==span)v.lz_span=span*2u;v.lz_remaining-=n;budget-=n;
            if(!v.lz_remaining)v.lz_state=0;break;}
        default:return -1;
        }
    }return 0;
}
/* One bounded decode slice. Delta dependency always copies the immediately
 * previous prepared frame, even if its presentation deadline was missed. */
static int decode(void){
    if(v.type==4)return decode_lz4();
    uint8_t*b=v.record.bytes+32;uint16_t*out=v.frame[v.building];uint32_t pixels=v.width*v.height;
    if(v.decode_pixel<pixels&&(v.type==0||v.type==1||v.type==2)){
        uint32_t n=pixels-v.decode_pixel;if(n>2048)n=2048;
        const uint16_t*in=v.type==0?(const uint16_t*)b:v.frame[v.previous];copy(out+v.decode_pixel,in+v.decode_pixel,n*2);v.decode_pixel+=n;return 0;
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
void ln_video_init(void){clear(&v,sizeof v);v.generation=0x71000000u;v.front=v.previous=v.building=v.index_page_at=NONE;v.min_audio=NONE;}
bool ln_video_open(const char*path){
    if(v.active||v.pending||!path||path[0]!='/')return false;uint32_t n=0;while(path[n]&&n<255)n++;if(!n||n==255)return false;
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
bool ln_video_pending(void){return v.pending;}
bool ln_video_paused(void){return v.paused;}
void ln_video_pause(bool pause){if(!v.active||v.stopping)return;v.paused=pause;if(v.started){if(pause)ln_audio_pause();else if(!ln_audio_start())fail(13);}++v.revision;}
bool ln_video_seek(int32_t seconds){
#if !defined(LINNET_PROFILE_RELEASE)
    if(v.measurement)return false;
#endif
    if(!v.ready||v.stopping)return false;struct ln_audio_status a;ln_audio_snapshot(&a);int64_t frame=(int64_t)((v.origin+a.consumed)/(48000u/v.fps))+(int64_t)seconds*v.fps;
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
        if(v.stopping){v.active=false;v.phase=IDLE;++v.revision;
#if !defined(LINNET_PROFILE_RELEASE)
            v.measurement=0;
#endif
            return;}
        v.front=v.previous=v.building=NONE;v.qhead=v.qcount=v.submitted=0;v.started=v.finish=v.offered=false;v.phase=SEEK;++v.revision;
    }
    struct ln_audio_status a;ln_audio_snapshot(&a);
    if(v.started){v.resume_frame=(v.origin+a.consumed)/(48000u/v.fps);if(v.resume_frame>=v.count)v.resume_frame=v.count-1;v.audio_gaps=a.underruns;v.audio_silence=a.silence_frames;v.audio_fault=a.fault;if(a.queued<v.min_audio)v.min_audio=a.queued;if(a.fault){fail(13);return;}}
    present(&a);
    if(v.ready&&!v.started&&!v.paused&&!v.offered&&v.front!=NONE&&v.submitted&&((v.qcount+1u)>=2||v.next==v.count)){
        if(!ln_audio_start()){fail(13);return;}v.started=true;++v.revision;
#if !defined(LINNET_PROFILE_RELEASE)
        v.measurement_started=ln_time_us();
#endif
    }
    int r;uint8_t*b=v.record.bytes;
    switch(v.phase){
    case OPEN:r=io(0,0,0,true);if(r<0)fail(1);else if(r==1)v.phase=HEADER;return;
    case HEADER:r=io(0,b,512,false);if(r<0){fail(2);return;}if(!r)return;if(!header()){fail(3);return;}
        v.verify_at=512;v.verify_crc=~0u;v.verify_end=v.data_at;v.verify_key=0;v.phase=VERIFY;return;
    case VERIFY:{uint32_t n=v.data_at-v.verify_at;if(n>4096)n=4096;r=io(v.verify_at,b,n,false);if(r<0){fail(4);return;}if(!r)return;
        v.verify_crc=crc_update(v.verify_crc,b,n);
        for(uint32_t at=0;at<n;at+=32){if(v.verify_frame<v.count){if(!index_record(b+at,v.verify_frame)||r32(b+at)!=v.verify_end){fail(5);return;}
            uint32_t key=r32(b+at+20),bytes=r32(b+at+4);if(key!=v.verify_frame&&key!=v.verify_key){fail(5);return;}v.verify_key=key;v.verify_end+=bytes;if(bytes>v.verify_max)v.verify_max=bytes;++v.verify_frame;
        }else if(!zero(b+at,32)){fail(5);return;}}
        v.verify_at+=n;if(v.verify_at==v.data_at){if((v.verify_crc^~0u)!=v.index_crc||v.verify_end!=v.file.size||v.verify_max!=v.max_record){fail(6);return;}
            v.ready=true;
            bool resume=saved_resume[0]==v.identity&&saved_resume[1]<v.count;
#if !defined(LINNET_PROFILE_RELEASE)
            if(v.measurement)resume=false;
#endif
            if(resume){v.target=saved_resume[1];v.seeking=true;v.phase=SEEK;}
            else {if(!ln_audio_init(48000)){fail(13);return;}v.phase=INDEX;}}return;}
    case SEEK:r=read_index(v.target);if(r<0){fail(7);return;}if(!r)return;if(!index_record(b,v.target)){fail(7);return;}
        v.next=r32(b+20);v.resume_frame=v.target;v.origin=v.target*(48000u/v.fps);if(!ln_audio_init(48000)){fail(13);return;}v.phase=INDEX;return;
    case INDEX:
        if(v.next>=v.count){if(!v.finish){ln_audio_finish();v.finish=true;}v.phase=WAIT;return;}
        v.building=free_slot();if(v.building==NONE)return;
        r=read_index(v.next);if(r<0){fail(7);return;}if(!r)return;if(!index_record(b,v.next)){fail(7);return;}load_index(b);v.at=0;v.read_time=0;clear(v.cpu,sizeof v.cpu);v.prepare_start=ln_time_us();v.phase=READ;return;
    case READ:{uint32_t n=v.bytes-v.at;if(n>16384)n=16384;r=io(v.offset+v.at,b+v.at,n,false);if(r<0){fail(8);return;}if(!r)return;v.at+=n;if(v.at==v.bytes){if(v.read_time>v.max_read_time)v.max_read_time=v.read_time;v.at=0;v.crc=~0u;v.phase=CRC;}return;}
    case CRC:{
        if(!record_header()){fail(9);return;}
        uint32_t used=32u+v.video_bytes+v.samples*4u;
        /* Validate bounds and zero padding before using any declared lengths.
         * Compute the actual header and padding contribution once. The payload
         * scan below completes the exact whole-record CRC before any decode. */
        v.record_edges_crc=crc_shift(checksum(b,32u),v.bytes-32u)^checksum(b+used,v.bytes-used);
        v.at=0;v.crc=~0u;v.decode_at=v.decode_pixel=0;
        v.lz_state=v.lz_token=v.lz_remaining=v.lz_offset=v.lz_literal=v.lz_span=0;v.lz_matched=false;
        v.phase=DECODE;return;}
    case DECODE:
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
        if(v.type==1){if(v.frame_crc!=v.previous_crc){fail(12);return;}}
        else {uint32_t n=v.width*v.height*2-v.at;if(n>4096)n=4096;v.crc=crc_update(v.crc,(uint8_t*)v.frame[v.building]+v.at,n);v.at+=n;if(v.at!=v.width*v.height*2)return;if((v.crc^~0u)!=v.frame_crc){fail(12);return;}}
        v.previous_crc=v.frame_crc;v.previous=v.building;++v.prepared;
        uint32_t elapsed=ln_time_us()-v.prepare_start;if(elapsed>v.max_prepare)v.max_prepare=elapsed;
        if(v.seeking&&v.next<v.target){++v.next;v.phase=INDEX;return;}
        v.seeking=false;v.at=0;v.phase=PCM;return;}
    case PCM:{uint32_t sent=submit_pcm(b+32+v.video_bytes+4u*v.at,v.samples-v.at);v.at+=sent;v.submitted+=sent;if(v.at!=v.samples)return;
        v.slot_frame[v.building]=v.next;v.queue[(v.qhead+v.qcount)%3]=v.building;++v.qcount;if(v.qcount>v.max_queue)v.max_queue=v.qcount;++v.next;v.phase=INDEX;return;}
    case WAIT:if(v.started&&!v.paused&&!a.queued&&!v.qcount&&!v.offered){if(!ln_audio_stop()){fail(13);return;}v.resume_frame=0;v.completed=true;v.active=false;v.phase=IDLE;++v.revision;
#if !defined(LINNET_PROFILE_RELEASE)
        v.measurement=0;
#endif
        }return;
    default:return;
    }
}
void ln_video_step(void){
    if(v.stepping)return;v.stepping=true;uint32_t batch_started=ln_time_us();
    for(uint32_t slices=0;slices<64u;slices++){
        uint32_t started=ln_time_us(),phase=v.phase,at=v.at,next=v.next,revision=v.revision,epoch=v.epoch;
        uint32_t decode_at=v.decode_at,decode_pixel=v.decode_pixel,tile_count=v.tile_count;
        uint32_t stage=phase==CRC?0:phase==DECODE?(v.at<v.video_bytes+v.samples*4u?1:2):phase==FRAME_CRC?3:NONE;
        step();uint32_t elapsed=ln_time_us()-started;
        if(stage!=NONE){v.cpu[stage]+=elapsed;if(v.cpu[stage]>v.max_cpu[stage])v.max_cpu[stage]=v.cpu[stage];}
        if(!v.active||v.pending||ln_time_us()-batch_started>=500u)break;
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
    if(v.started){struct ln_audio_status a;ln_audio_snapshot(&a);uint32_t clock=v.origin+a.consumed,sample=v.slot_frame[v.front]*(48000u/v.fps);
        if(clock>sample){uint32_t late=clock-sample;++v.late;if(late>v.max_late)v.max_late=late;}}
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
    /* A settled pause with all three slots owned has no read/decode work to
     * advance. Input IRQs, executive deadlines and the watchdog cap still
     * bound the sleep; transition, cancel and seek states remain runnable. */
    if(paused_quiescent())return now+200000u;
    if(v.pending||v.phase==WAIT||(v.phase==INDEX&&free_slot()==NONE))return now+1000u;
    return now;
}
void ln_video_diagnostics(uint32_t out[32]){uint32_t a[32]={0x36544956u,2,v.phase,v.error,v.active,v.pending,v.paused,v.next,v.count,v.front==NONE?NONE:v.slot_frame[v.front],v.reads,v.read_bytes,v.prepared,v.presented,v.late,v.max_late,v.max_prepare,v.qcount,v.max_queue,v.audio_gaps,v.audio_silence,v.audio_fault,v.submitted,v.revision,v.max_io,v.max_read_time,v.max_cpu[0],v.max_cpu[1],v.max_cpu[2],v.max_cpu[3],v.max_step,v.min_audio};for(uint32_t i=0;i<32;i++)out[i]=a[i];}
