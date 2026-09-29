#include "boot/include/linnet_bytes.h"
#include "services/update/native.h"
#include "services/storage/storage.h"
#include "services/storage/block.h"
#include "hal/api/platform.h"
#include "boot/include/linnet_boot.h"
#include "boot/include/sha256.h"
#include "linnet_build.h"

/* A fixed-purpose development maintenance operation, never a raw-write API. */
static uint8_t package[LINNET_NATIVE_PACKAGE_BYTES] __attribute__((aligned(32)));
static uint8_t sector[4096] __attribute__((aligned(32)));
static uint8_t expected[32],observed[32];
static uint32_t phase,error,offset,writes,request_generation=0x40000000u,bytes_read;
static uint32_t apply_started,package_size;
static int equal(const uint8_t *a,const uint8_t *b,uint32_t n){for(uint32_t i=0;i<n;++i)if(a[i]!=b[i])return 0;return 1;}
static int zero(const uint8_t *a,uint32_t n){for(uint32_t i=0;i<n;++i)if(a[i])return 0;return 1;}
static void hash(const uint8_t *data,uint32_t n,uint8_t out[32]){
    struct ln_sha256 s;ln_sha256_init(&s);
    while(n){uint32_t chunk=n>4096u?4096u:n;ln_sha256_update(&s,data,chunk);data+=chunk;n-=chunk;ln_storage_progress(0);}
    ln_sha256_finish(&s,out);
}
static int matches(const uint8_t *data,uint32_t n,const uint8_t sha[32]){uint8_t d[32];hash(data,n,d);return equal(d,sha,32);}
int ln_native_begin(uint32_t length,const uint8_t sha[32]){
    if(length<68096u||length>sizeof package||((length-2560u)&511u)||!sha||(phase>=3&&phase<=9)||writes||ln_storage_busy())return 0;
    for(uint32_t i=0;i<32;++i)expected[i]=sha[i];package_size=length;offset=error=bytes_read=0;phase=1;return 1;
}
int ln_native_write(uint32_t start,const uint8_t *data,uint32_t n){
    if(phase!=1||!data||!n||n>1008||start!=offset||n>package_size-offset)return 0;
    for(uint32_t i=0;i<n;++i)package[offset+i]=data[i];offset+=n;if(offset==package_size)phase=2;return 1;
}
static int io(enum ln_block_op op,uint64_t address,uint8_t *data,uint32_t count){
    uint32_t id,generation=++request_generation;
    if(ln_time_us()-apply_started>600000000u)return 0;
    if(!ln_block_submit(op,address>>9,count,data,generation,ln_time_us()+5000000u,&id))return 0;
    struct ln_block_completion done;
    do{ln_storage_progress(0);}while(!ln_block_take(generation,&done));
    return done.request_id==id&&done.status==LN_ATA_OK&&done.sectors_done==count;
}
static int digest_disk(uint64_t address,uint32_t n,const uint8_t sha[32]){
    struct ln_sha256 s;ln_sha256_init(&s);
    while(n){uint32_t chunk=n>4096u?4096u:n,count=(chunk+511u)>>9;
        if(!io(LN_BLOCK_READ,address,sector,count))return 0;
        ln_sha256_update(&s,sector,chunk);ln_storage_progress(0);
        address+=chunk;n-=chunk;bytes_read+=chunk;
    }
    ln_sha256_finish(&s,observed);return equal(observed,sha,32);
}
static int directory_valid(uint64_t candidate,uint32_t length){
    const uint8_t *old=package+1024,*next=package+1536;uint32_t os=UINT32_MAX;
    uint32_t sum=0;for(uint32_t i=0;i<length;++i)sum+=package[2560+i];
    for(uint32_t entry=0;entry+40<=512;entry+=40){
        const uint8_t *p=old+entry;if(zero(p,4))break;
        if(!equal(p,(const uint8_t *)"!ATA",4))return 0;
        uint64_t start=32256u+(uint64_t)ln_read_le32(p+12)+512u;uint32_t size=ln_read_le32(p+16);
        if(!size||start<49152u+512u||start+size>41126400u||
           (candidate<start+size&&start<candidate+ln_read_le32(package+40)))return 0;
        if(equal(p+4,(const uint8_t *)"soso",4)){if(os!=UINT32_MAX)return 0;os=entry;}
    }
    if(os==UINT32_MAX||ln_read_le32(next+os+12)!=candidate-32256u-512u||ln_read_le32(next+os+16)!=length||
       ln_read_le32(next+os+24)||ln_read_le32(next+os+28)!=sum)return 0;
    for(uint32_t i=0;i<512;++i){
        bool mutable=(i>=os+12&&i<os+20)||(i>=os+24&&i<os+32);
        if(!mutable&&old[i]!=next[i])return 0;
    }
    return 1;
}
static int validate(void){
    static const uint8_t original_sha[32]={0x0e,0x21,0xc2,0xbc,0x8c,0xba,0xbd,0xee,0xd6,0xe3,0xd6,0xa0,0x34,0xea,0xcc,0x8e,0x3c,0xa7,0xd6,0xfb,0x04,0xcd,0x2d,0x5d,0x1b,0x4c,0xfc,0x5f,0xd8,0x5d,0x96,0x11};
    static const uint8_t serial[16]="JQ5081G3SAY",usb[33]=LINNET_USB_SERIAL;
    const uint8_t *p=package;uint64_t candidate=ln_read_le64(p+32);uint32_t n=ln_read_le32(p+44),span=ln_read_le32(p+40);
    if(ln_read_le32(p)!=0x4b504e4cu||ln_read_le32(p+4)||ln_read_le32(p+8)!=package_size||ln_read_le32(p+12)!=98||ln_read_le32(p+16)||
       ln_read_le32(p+20)!=41094144u||ln_read_le64(p+24)!=32256u||span!=package_size-2560u||n<32||n>span||
       ln_read_le64(p+48)!=49152u||ln_read_le64(p+56)!=21003776u||ln_read_le32(p+64)!=1549256u||
       ln_read_le32(p+68)>2||ln_read_le64(p+72)!=64021856256ull||
       !equal(p+80,serial,16)||!equal(p+96,usb,16)||!equal(p+208,original_sha,32)||
       !zero(p+464,44)||ln_crc32(p,508)!=ln_read_le32(p+508)||
       candidate%512||candidate<22553032u||candidate+ln_read_le32(package+40)>41126400u)return 0;
    if(!matches(p,package_size,expected)||!matches(p+512,package_size-512,p+432)||
       !matches(p+512,512,p+240)||!matches(p+1024,512,p+304)||!matches(p+1536,512,p+336)||
       !matches(p+2560,span,p+272)||!zero(p+2176,384)||!zero(p+2560+n,span-n)||!directory_valid(candidate,n))return 0;
    const uint8_t *mbr=p+512;if(mbr[510]!=0x55||mbr[511]!=0xaa||mbr[450]||ln_read_le32(mbr+454)!=63||ln_read_le32(mbr+458)!=80262)return 0;
    uint8_t *image=(uint8_t *)(uintptr_t)LINNET_STAGE_ADDRESS;
    for(uint32_t i=0;i<128;++i)image[i]=p[2048+i];for(uint32_t i=0;i<n;++i)image[128+i]=p[2560+i];
    struct ln_image_policy policy={98,7,0,0x100000};struct ln_image_info info;
    return matches(image,n+128,p+368)&&ln_image_validate_progress(image,n+128,&policy,&info,ln_storage_progress,0)==LINNET_IMAGE_OK&&
        info.load_address==0&&info.entry_address==0&&info.payload_size==n&&info.profile==ln_read_le32(p+68)&&equal(info.build_id,p+400,32);
}
int ln_native_apply(void){
    if(phase!=2||offset!=package_size||writes)return 0;
    phase=3;apply_started=ln_time_us();
    if(!validate()){error=1;phase=11;return 0;}
    struct ln_block_info b;ln_block_snapshot(&b);
    if(b.sectors!=125042688u||!ln_storage_maintenance_begin()){error=2;phase=11;return 0;}
    phase=4;
    if(!digest_disk(0,512,package+240)||!digest_disk(32256,41094144,package+112)||
       !digest_disk(21003776,1549256,package+208)||!digest_disk(49152,512,package+304)){error=3;goto failed;}
    uint64_t candidate=ln_read_le64(package+32);uint32_t span=ln_read_le32(package+40);
    for(uint32_t n=0;n<span;n+=4096){uint32_t chunk=span-n>4096u?4096u:span-n;if(!io(LN_BLOCK_READ,candidate+n,sector,chunk/512u)||!zero(sector,chunk)){error=4;goto failed;}}
    phase=5;
    for(uint32_t n=0;n<span;n+=4096){uint32_t chunk=span-n>4096u?4096u:span-n;writes|=1u;if(!io(LN_BLOCK_WRITE,candidate+n,package+2560+n,chunk/512u)){error=5;goto failed;}}
    if(!io(LN_BLOCK_FLUSH,0,0,0)){error=6;goto failed;}
    phase=6;
    if(!digest_disk(candidate,span,package+272)||!digest_disk(32256,41094144,package+144)){error=7;goto failed;}
    phase=7;writes|=2u;
    if(!io(LN_BLOCK_WRITE,49152,package+1536,1)||!io(LN_BLOCK_FLUSH,0,0,0)){error=8;goto failed;}
    phase=8;
    if(!digest_disk(49152,512,package+336)||!digest_disk(32256,41094144,package+176)){error=9;goto failed;}
    phase=10;ln_storage_maintenance_end(true);return 1;
failed:phase=11;ln_storage_maintenance_end(false);return 0;
}
void ln_native_status(uint32_t words[16]){
    uint32_t v[8]={0x32424e4cu,phase,error,offset,writes,bytes_read,ln_time_us()-apply_started,request_generation};
    for(uint32_t i=0;i<8;++i){words[i]=v[i];words[8+i]=ln_read_le32(observed+i*4);}
}
