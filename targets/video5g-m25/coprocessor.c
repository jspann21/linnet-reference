/* Independent, bounded BCM2722 runtime startup qualification.
 * Hardware protocol references and evidence: NATIVE_VIDEO.md.
 * No vendor firmware or third-party implementation is embedded here. */
#include "boot/include/linnet_bytes.h"
#include "targets/video5g-m25/coprocessor.h"
#include "targets/video5g-m25/lcd.h"
#include "hal/api/platform.h"
#include "hal/api/display.h"
#include "hal/api/power.h"
#include "services/storage/storage.h"
#include "services/video/mp4.h"
#include "services/audio/aac/aac.h"
#include "hal/api/audio.h"
#include "boot/include/sha256.h"
/* Native playback exclusively owns the existing media staging arena. */
#define audio_decoder (*(struct ln_aac *)(uintptr_t)LINNET_STAGE_ADDRESS)
#define AUDIO_PRIME_FRAMES 32768u
#define AUDIO_BUFFER_FRAMES 49152u
#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define HALF(a) (*(volatile uint16_t *)(uintptr_t)(a))
#if !defined(LINNET_PROFILE_RELEASE)
static uint32_t fault_mode,fault_deadline;
#endif
enum { IDLE,OPEN,READ,HASH,ACQUIRE,POWER_OFF,POWER_ON,BUS_READY,BUS_SETUP,
       BUS_LATCH,UPLOAD,VALIDATE_BEGIN,VALIDATE_WAIT,EXECUTE,READY_WAIT,
       DIRECTORY,OBSERVE,RESTORED,FAILED,ROM_CHECK,CHANNELS,VERSION_SEND,VERSION_REPLY,PLAYER_SETTLE,
       MEDIA_OPEN,MEDIA_SCAN,MEDIA_PACKET,MEDIA_FRAME,AUDIO_SCAN,AUDIO_PRIME,SYNC_WAIT };
static struct {
    uint32_t phase,error,restore,at,deadline,generation,requested,hash_at;
    char path[256];bool normal,paused,want_paused,seek_pending,clock_valid;uint8_t options;
    uint32_t requested_seek,clock_ms,clock_us,position_base,revision,board_revision;
    uint32_t header[4],directory[4],legacy_header[4],restore_error;
    bool io,owned,reply_stream,fs_canceling,syncing_seek,seek_forward,seek_seen;
    const uint8_t *rom;
    uint32_t rom_bytes;
    uint32_t rom_sum,rom_expected,rom_checked,map_logical,map_physical;
    uint32_t rom_diagnostic[8];
    uint32_t channel[8][20],slot;
    uint32_t reply[256],reply_bytes,command_slot,command_index,reply_parsed;
    uint32_t host_channel[32],host_event[32],epoch,epoch_at;bool epoch_valid;
    uint32_t operation,host_request[32],file_slot,control,return_deadline,sync_deadline,start_elapsed,seek_ms,seek_stage,seek_sequence,seek_frames;
    struct {struct ln_fat32_file file;uint32_t position;bool open;} files[8];
    uint32_t fs_phase,fs_fd,fs_count,fs_opcode,fs_requested,fs_bytes,fs_tx_bytes,fs_tx_at,fs_wr,fs_element_size;
    uint32_t fs_packet[2064] __attribute__((aligned(32)));
    struct ln_mp4 movie;struct ln_mp4_packet packet;struct ln_fat32_file video_file;
    uint8_t frame[65536] __attribute__((aligned(32)));
    struct ln_mp4 soundtrack;struct ln_mp4_packet audio_packet;
    struct ln_audio_status audio_status;
    uint32_t audio_phase,audio_frames,read_kind;uint64_t audio_skip;bool audio_ready,audio_started,audio_eof;
    struct {uint64_t offset[3];uint32_t bytes[3],age[3],clock,filling;bool pending;} cache[2];
    uint64_t read_offset;void *read_buffer;uint32_t read_bytes,read_at,read_requested;
    bool read_active,read_io;
    uint32_t stream_packet[332],stream_phase,stream_at,stream_wr,stream_address,stream_capacity,stream_frames;
    bool mapped,stream_waiting;
    struct ln_fat32_file file;
    struct ln_sha256 hash;
    uint8_t image[201376] __attribute__((aligned(32)));
} vc;
/* This revision has been extracted from the device's checksum-verified rsrc.
 * Other vendor revisions need their own qualification before admission. */
static const uint8_t expected_sha[32]={
    0xcd,0xe4,0xb5,0xa9,0xc9,0xa0,0x20,0xb6,0xe2,0x3d,0xe1,0xbe,0x04,0x92,0xd9,0xa8,
    0x53,0xb7,0xd9,0x74,0xc4,0x06,0x04,0x62,0xd5,0xf5,0x7a,0x80,0xe4,0x7f,0x55,0xbe};
static void unmap_rom(void){
    if(!vc.mapped)return;
    REG(0xf000f00cu)=vc.map_physical;REG(0xf000f008u)=vc.map_logical;
    __asm__ volatile("nop\n\tnop\n\tnop":::"memory");vc.mapped=false;
}
static bool rom_image(void){
    for(uint32_t i=0;i<8u;++i)vc.rom_diagnostic[i]=0;
    /* The native ROM handoff maps SDRAM over address zero, but does not
     * establish Rockbox's later NOR alias. Never dereference the alias before
     * explicitly installing and checking its dedicated mapping window. */
    vc.map_logical=REG(0xf000f008u);vc.map_physical=REG(0xf000f00cu);
    if((vc.map_physical&0xf00u)&&vc.map_logical!=0x20003c00u)return false;
    REG(0xf000f008u)=0x20003c00u;REG(0xf000f00cu)=0x00003f84u;vc.mapped=true;
    __asm__ volatile("nop\n\tnop\n\tnop":::"memory");
    vc.rom_diagnostic[0]=REG(0xf000f008u);vc.rom_diagnostic[1]=REG(0xf000f00cu);
    /* PP5022 reads the two reserved physical bits [13:12] back as zero.
     * Check the address and access fields; retain the documented write value. */
    if(REG(0xf000f008u)!=0x20003c00u||(REG(0xf000f00cu)&~0x3000u)!=0x00000f84u){unmap_rom();return false;}
    const uint8_t *rom=(const uint8_t *)(uintptr_t)0x20000000u;
    /* Directory is the final 512 bytes of the 1 MiB NOR. Bound every entry
     * and every image extent before reading or selecting recovery firmware. */
    for(uint32_t at=0xffe00u;at+40u<=0x100000u;at+=40u){
        const uint8_t *e=rom+at;
        vc.rom_diagnostic[2]=at;
        for(uint32_t i=0;i<5u;++i)vc.rom_diagnostic[3+i]=ln_read_le32(e+i*4u);
        if(ln_read_le32(e)!=0x666c7368u)break;
        if(ln_read_le32(e+4)!=0x766d6373u)continue;
        uint32_t offset=ln_read_le32(e+12),length=ln_read_le32(e+16);
        if((offset&3u)||(length&3u)||!length||length>262144u||offset>0xffe00u||length>0xffe00u-offset)break;
        vc.rom=rom+offset;vc.rom_bytes=length;vc.rom_expected=ln_read_le32(e+28);
        vc.rom_sum=vc.rom_checked=0;return true;
    }
    unmap_rom();return false;
}
static void phase(uint32_t next,uint32_t timeout){vc.phase=next;vc.deadline=ln_time_us()+timeout;}
static bool expired(void){return (int32_t)(ln_time_us()-vc.deadline)>=0;}
static bool put(uint32_t address,uint32_t value){return ln_m25_bcm_write(address,&value,1u);}
static uint32_t halfword(const uint32_t *words,uint32_t byte){return (words[byte/4u]>>((byte&2u)*8u))&0xffffu;}
static bool ring_valid(uint32_t lo,uint32_t hi,uint32_t at){
    return !(lo&15u)&&!(hi&15u)&&!(at&15u)&&hi>lo&&at>=lo&&at<hi&&vc.header[3]<=0xffffffffu-hi;
}
static bool ring_transfer(bool write,uint32_t lo,uint32_t hi,uint32_t *at,uint32_t *words,uint32_t bytes){
    if(!ring_valid(lo,hi,*at)||(bytes&15u)||bytes>128u||bytes>hi-lo-16u)return false;
    uint32_t first=hi-*at;if(first>bytes)first=bytes;
    if(write?!ln_m25_bcm_write(vc.header[3]+*at,words,first/4u):!ln_m25_bcm_read(vc.header[3]+*at,words,first/4u))return false;
    *at+=first;if(*at==hi)*at=lo;
    if(first<bytes){
        if(write?!ln_m25_bcm_write(vc.header[3]+*at,words+first/4u,(bytes-first)/4u):!ln_m25_bcm_read(vc.header[3]+*at,words+first/4u,(bytes-first)/4u))return false;
        *at+=bytes-first;
    }
    return true;
}
static bool notify_channel(uint32_t slot){
    uint32_t host[4],remote[4];
    if(!ln_m25_bcm_read(vc.header[3]+0x10u,host,4u)||!ln_m25_bcm_read(vc.header[3]+0x20u,remote,4u))return false;
    host[0]^=(1u<<slot)&~(host[0]^remote[0]);
    host[0]=(host[0]&~0xff00u)|(remote[0]&0xff00u);
    if(!ln_m25_bcm_write(vc.header[3]+0x10u,host,4u))return false;
    HALF(0x30030000u)=0x31u;return true;
}
static int media_read(void *context,uint64_t at,void *buffer,uint32_t bytes){
    uint32_t kind=(uint32_t)(uintptr_t)context;
    if(vc.read_active&&vc.read_kind!=kind)return 0;
    if(!vc.read_active){vc.read_kind=kind;vc.read_offset=at;vc.read_buffer=buffer;vc.read_bytes=bytes;vc.read_at=0;vc.read_active=true;}
    if(at!=vc.read_offset||buffer!=vc.read_buffer||bytes!=vc.read_bytes||at>0xffffffffu)return -1;
    if(vc.read_io){
        uint32_t transferred=0;int result=ln_storage_media_poll_deferred(vc.generation,0,&transferred);
        if(!result)return 0;vc.read_io=false;
        if(result<0||transferred!=vc.read_requested){vc.read_active=false;return -1;}
        vc.read_at+=transferred;
        if(vc.read_at==bytes){vc.read_active=false;return 1;}
    }
    uint32_t count=bytes-vc.read_at;if(count>16384u)count=16384u;
    int result=ln_storage_media_read(&vc.video_file,(uint32_t)at+vc.read_at,(uint8_t *)buffer+vc.read_at,count,vc.generation);
    if(result<0){vc.read_active=false;return -1;}
    if(result>0){vc.read_requested=count;vc.read_io=true;}
    return 0;
}
static int video_read(void *context,uint64_t at,void *buffer,uint32_t bytes){
    uint32_t kind=(uint32_t)(uintptr_t)context;
    if(kind>1u)return -1;
    /* Cached audio may advance while a video disk read is outstanding.
     * media_read arbitrates actual I/O; the two caches own separate memory. */
    if(bytes>16384u)return media_read(context,at,buffer,bytes);
    __typeof__(vc.cache[0]) *cache=&vc.cache[kind];
    uint8_t *base=(uint8_t *)(uintptr_t)(LINNET_STAGE_ADDRESS+0x20000u+kind*49152u);
    if(cache->pending){
        uint32_t slot=cache->filling;
        int result=media_read(context,cache->offset[slot],base+slot*16384u,cache->bytes[slot]);
        if(result<=0)return result;cache->pending=false;cache->age[slot]=++cache->clock;
    }
    for(uint32_t i=0;i<3u;++i)if(cache->bytes[i]&&at>=cache->offset[i]&&at-cache->offset[i]<=cache->bytes[i]&&bytes<=cache->bytes[i]-(uint32_t)(at-cache->offset[i])){
        const uint8_t *source=base+i*16384u+(uint32_t)(at-cache->offset[i]);
        for(uint32_t j=0;j<bytes;++j)((uint8_t *)buffer)[j]=source[j];cache->age[i]=++cache->clock;return 1;
    }
    uint32_t slot=0;for(uint32_t i=1;i<3u;++i)if(cache->age[i]<cache->age[slot])slot=i;
    uint64_t offset=at&~4095ull;if(at-offset+bytes>16384u)offset=at;
    if(offset>=vc.video_file.size)return -1;
    uint32_t count=vc.video_file.size-(uint32_t)offset;if(count>16384u)count=16384u;
    cache->offset[slot]=offset;cache->bytes[slot]=count;cache->filling=slot;cache->pending=true;
    return 0;
}
/* Track timestamps can exceed 32 bits even when playback time fits in ms. */
static uint64_t divide_ticks(uint64_t ticks,uint32_t rate){
    uint64_t quotient=0,remainder=0;
    if(!rate)return UINT64_MAX;
    for(uint32_t bit=64u;bit;--bit){
        remainder=(remainder<<1)|((ticks>>(bit-1u))&1u);
        if(remainder>=rate){remainder-=rate;quotient|=(uint64_t)1u<<(bit-1u);}
    }
    return quotient;
}
static uint32_t duration_ms(uint64_t ticks,uint32_t rate){
    if(ticks>UINT64_MAX/1000u)return UINT32_MAX;
    uint64_t ms=divide_ticks(ticks*1000u,rate);
    return ms>UINT32_MAX?UINT32_MAX:(uint32_t)ms;
}
static uint32_t elapsed_value(const uint8_t *text,uint32_t bytes){
    for(uint32_t j=0;j+8u<bytes;++j)if(text[j]=='e'&&text[j+1]=='l'&&text[j+2]=='a'&&text[j+3]=='p'&&text[j+4]=='s'&&text[j+5]=='e'&&text[j+6]=='d'&&text[j+7]=='='){
        uint32_t value=0;for(j+=8u;j<bytes&&text[j]>='0'&&text[j]<='9';++j){if(value>429496728u)return 0;value=value*10u+text[j]-'0';}return value;
    }
    return 0;
}
static bool status_field(const uint8_t *text,uint32_t bytes,const char *field,bool prefix){
    for(uint32_t at=0;at<bytes&&text[at];++at){
        if(at&&text[at-1u]!=' ')continue;
        uint32_t n=0;while(field[n]&&at+n<bytes&&text[at+n]==(uint8_t)field[n])++n;
        if(!field[n]&&(prefix||at+n==bytes||!text[at+n]||text[at+n]==' '))return true;
    }
    return false;
}
static bool playback_running(const uint8_t *text,uint32_t bytes){
    /* A valid first or repeated picture can retain elapsed=0. */
    return status_field(text,bytes,"state=play",false)&&status_field(text,bytes,"substate=running",false)&&
           status_field(text,bytes,"paused=no",false)&&(!status_field(text,bytes,"buffering=",true)||
           status_field(text,bytes,"buffering=0",false));
}
static bool audio_service(void){
    if(!vc.audio_ready||vc.audio_eof||vc.fs_phase||(vc.seek_stage&&vc.seek_stage!=6u&&!(vc.seek_stage==1u&&vc.read_active)))return true;
    struct ln_audio_status status;ln_audio_snapshot(&status);
    if(status.fault)return false;
    if(status.queued>=AUDIO_BUFFER_FRAMES&&!vc.read_active)return true;
    int result;
    if(vc.audio_phase==1u){
        result=ln_mp4_next(&vc.soundtrack,&vc.audio_packet);
        if(result==LN_MP4_EOF){vc.audio_eof=true;ln_audio_finish();return true;}
        if(result<0)return false;
        if(result>0){if(vc.audio_packet.bytes>8191u||vc.audio_packet.duration>1024u)return false;vc.audio_phase=2u;}
    }else if(vc.audio_phase==2u){
        result=video_read((void *)1u,vc.audio_packet.offset,audio_decoder.input,vc.audio_packet.bytes);
        if(result<0)return false;if(result>0)vc.audio_phase=3u;
    }else if(vc.audio_phase==3u){
        result=ln_aac_raw_decode(&audio_decoder,audio_decoder.input,vc.audio_packet.bytes);if(result!=1)return false;
        uint64_t remaining=vc.audio_packet.dts<vc.audio_skip?vc.audio_skip-vc.audio_packet.dts:0u;
        uint32_t skip=remaining>vc.audio_packet.duration?vc.audio_packet.duration:(uint32_t)remaining;
        audio_decoder.pcm_cursor=skip;audio_decoder.pcm_frames=vc.audio_packet.duration;vc.audio_phase=4u;
    }else{
        uint32_t remaining=audio_decoder.pcm_frames-audio_decoder.pcm_cursor;
        uint32_t accepted=remaining?ln_audio_submit(audio_decoder.pcm+audio_decoder.pcm_cursor*2u,remaining):0u;
        audio_decoder.pcm_cursor+=accepted;vc.audio_frames+=accepted;
        if(audio_decoder.pcm_cursor==audio_decoder.pcm_frames)vc.audio_phase=1u;
    }
    return true;
}
static bool stream_service(void){
    vc.stream_waiting=false;
    if(vc.operation!=2u)return true;
    uint32_t slot=0;while(slot<8u&&halfword(vc.channel[slot],4u)!=7u)++slot;
    if(slot==8u)return false;
    uint32_t *c=vc.channel[slot],off=(vc.directory[slot/2u]>>((slot&1u)*16u))&0xffffu,record=vc.header[3]+off;
    if(vc.seek_stage){
        int result;
        if(vc.seek_stage==1u){
            if(vc.read_active||vc.fs_phase)return true;
            for(uint32_t i=0;i<2u;++i)if(vc.cache[i].pending){vc.cache[i].bytes[vc.cache[i].filling]=0;vc.cache[i].pending=false;}
            vc.movie.packet_phase=0;
            if(!ln_mp4_seek(&vc.movie,divide_ticks((uint64_t)vc.seek_ms*vc.movie.timescale,1000u),vc.seek_forward?1:-1))return false;
            if(vc.audio_ready){
                if(!ln_audio_halt()||!ln_audio_init(vc.soundtrack.rate)||ln_aac_raw_init(&audio_decoder,vc.soundtrack.config,vc.soundtrack.config_bytes)!=1)return false;
                vc.audio_phase=1u;vc.audio_frames=0;vc.audio_eof=vc.audio_started=false;
            }
            vc.seek_stage=2u;
        }else if(vc.seek_stage==2u){result=ln_mp4_seek_step(&vc.movie);if(result<0)return false;if(result>0)vc.seek_stage=3u;}
        else if(vc.seek_stage==3u){
            result=ln_mp4_next(&vc.movie,&vc.packet);if(result<0||result==LN_MP4_EOF)return false;
            if(result>0){
                vc.seek_ms=duration_ms(vc.packet.dts,vc.movie.timescale);vc.position_base=vc.seek_ms;
                if(vc.audio_ready){
                    vc.audio_skip=vc.soundtrack.lead+divide_ticks((uint64_t)vc.seek_ms*vc.soundtrack.rate,1000u);
                    vc.soundtrack.packet_phase=0;
                    if(!ln_mp4_seek(&vc.soundtrack,vc.audio_skip>1024u?vc.audio_skip-1024u:0u,0))return false;
                }
                vc.seek_stage=4u;
            }
        }
        else if(vc.seek_stage==4u){result=vc.audio_ready?ln_mp4_seek_step(&vc.soundtrack):1;if(result<0)return false;if(result>0)vc.seek_stage=5u;}
        else if(vc.seek_stage==5u){result=video_read(0,vc.packet.offset,vc.frame,vc.packet.bytes);if(result<0)return false;if(result>0)vc.seek_stage=6u;}
        else if(vc.seek_stage==6u){
            if(vc.audio_ready&&!vc.audio_eof&&vc.audio_frames<AUDIO_PRIME_FRAMES)return true;
            vc.stream_phase=2u;vc.seek_stage=0;
        }
        return true;
    }
    if(vc.stream_phase==5u||vc.stream_phase==6u){
        if(vc.fs_phase)return true;
        int result=vc.stream_phase==5u?ln_mp4_next(&vc.movie,&vc.packet):video_read(0,vc.packet.offset,vc.frame,vc.packet.bytes);
        if(result<0)return false;
        if(result==LN_MP4_EOF&&vc.stream_phase==5u){vc.stream_phase=7u;return true;}
        if(result>0)vc.stream_phase=vc.stream_phase==5u?6u:2u;
        return true;
    }
    if(vc.stream_phase==3u){
        uint32_t total=(vc.packet.bytes+15u)&~15u,count=total-vc.stream_at;
        if(total>vc.stream_capacity)return false;
        if(count>4096u)count=4096u;
        if(!ln_m25_bcm_write(vc.stream_address+vc.stream_at,(const uint32_t *)(vc.frame+vc.stream_at),count/4u))return false;
        vc.stream_at+=count;if(vc.stream_at==total)vc.stream_phase=4u;
        return true;
    }
    if(vc.stream_phase==4u){
        if(!ln_m25_bcm_read(record+16u,c+4,4u))return false;
        uint32_t lo=halfword(c,6),hi=halfword(c,8),rd=halfword(c,16),wr=halfword(c,32);
        if(!ring_valid(lo,hi,rd)||!ring_valid(lo,hi,wr))return false;
        uint32_t used=wr>=rd?wr-rd:hi-rd+wr-lo;
        if(hi-lo-used<80u)return true;
        if(!ring_transfer(true,lo,hi,&wr,vc.stream_packet,64u))return false;
        c[8]=(c[8]&0xffff0000u)|wr;
        if(!ln_m25_bcm_write(record+32u,c+8,4u)||!notify_channel(slot))return false;
        ++vc.stream_frames;vc.stream_phase=5u;return true;
    }
    if(vc.stream_phase==1u){
        if(!ln_m25_bcm_read(record+16u,c+4,4u))return false;
        uint32_t lo=halfword(c,6),hi=halfword(c,8),rd=halfword(c,16),wr=halfword(c,32);
        if(!ring_valid(lo,hi,rd)||!ring_valid(lo,hi,wr))return false;
        uint32_t used=wr>=rd?wr-rd:hi-rd+wr-lo;
        if(sizeof vc.stream_packet>hi-lo-used-16u)return true;
        if(!vc.stream_at)vc.stream_wr=wr;
        uint32_t count=sizeof vc.stream_packet-vc.stream_at;if(count>128u)count=128u;
        if(!ring_transfer(true,lo,hi,&vc.stream_wr,vc.stream_packet+vc.stream_at/4u,count))return false;
        vc.stream_at+=count;
        if(vc.stream_at==sizeof vc.stream_packet){
            c[8]=(c[8]&0xffff0000u)|vc.stream_wr;
            if(!ln_m25_bcm_write(record+32u,c+8,4u)||!notify_channel(slot))return false;
            vc.stream_phase=2u;
        }
        return true;
    }
    if(!ln_m25_bcm_read(record+64u,c+16,4u))return false;
    uint32_t lo=halfword(c,10),hi=halfword(c,12),rd=halfword(c,48),wr=halfword(c,64);
    if(!ring_valid(lo,hi,rd)||!ring_valid(lo,hi,wr))return false;
    uint32_t available=wr>=rd?wr-rd:hi-rd+wr-lo;
    if(available<16u){vc.stream_waiting=true;return true;}
    uint32_t count=available>128u?128u:available;
    if(!ring_transfer(false,lo,hi,&rd,vc.host_channel,count)||vc.host_channel[0]!=0xf1a55a1fu)return false;
    if(vc.host_channel[2]==68u){
        if((vc.host_channel[3]&0xffffu)!=4u||available<32u)return false;
        if(!ln_m25_bcm_read(record+16u,c+4,4u))return false;
        uint32_t txlo=halfword(c,6),txhi=halfword(c,8),txrd=halfword(c,16),txwr=halfword(c,32);
        if(!ring_valid(txlo,txhi,txrd)||!ring_valid(txlo,txhi,txwr))return false;
        uint32_t used=txwr>=txrd?txwr-txrd:txhi-txrd+txwr-txlo;if(txhi-txlo-used<48u)return true;
        uint32_t reply[8]={0xf1a55a1fu,vc.host_channel[1],99u,8u,19u,0,0,0};
        if(!ring_transfer(true,txlo,txhi,&txwr,reply,32u))return false;c[8]=(c[8]&0xffff0000u)|txwr;
        rd=halfword(c,48)+32u;if(rd>=hi)rd=lo+rd-hi;c[12]=(c[12]&0xffff0000u)|rd;
        return ln_m25_bcm_write(record+48u,c+12,4u)&&ln_m25_bcm_write(record+32u,c+8,4u)&&notify_channel(slot);
    }
    if(vc.host_channel[2]==67u){
        if((vc.host_channel[3]&0xffffu)!=8u||available<32u)return false;
        vc.seek_ms=vc.host_channel[5];vc.seek_sequence=vc.host_channel[1];vc.seek_stage=1u;
        vc.seek_seen=true;vc.seek_frames=vc.stream_frames;
        rd=halfword(c,48)+32u;if(rd>=hi)rd=lo+rd-hi;c[12]=(c[12]&0xffff0000u)|rd;
        return ln_m25_bcm_write(record+48u,c+12,4u)&&notify_channel(slot);
    }
    if(vc.host_channel[2]==66u&&(vc.stream_phase==2u||vc.stream_phase==7u)){
        if((vc.host_channel[3]&0xffffu)!=12u||available<32u)return false;
        rd=halfword(c,48)+32u;if(rd>=hi)rd=lo+rd-hi;
        c[12]=(c[12]&0xffff0000u)|rd;
        if(!ln_m25_bcm_write(record+48u,c+12,4u)||!notify_channel(slot))return false;
        if(vc.stream_phase==7u){
            uint32_t end[8]={0xf1a55a1fu,vc.host_channel[1],97u,8u,0,0,0,0};
            if(!ln_m25_bcm_read(record+16u,c+4,4u))return false;
            uint32_t txlo=halfword(c,6),txhi=halfword(c,8),txrd=halfword(c,16),txwr=halfword(c,32);
            if(!ring_valid(txlo,txhi,txrd)||!ring_valid(txlo,txhi,txwr))return false;
            uint32_t used=txwr>=txrd?txwr-txrd:txhi-txrd+txwr-txlo;
            if(txhi-txlo-used<48u)return false;
            if(!ring_transfer(true,txlo,txhi,&txwr,end,32u))return false;
            c[8]=(c[8]&0xffff0000u)|txwr;
            if(!ln_m25_bcm_write(record+32u,c+8,4u)||!notify_channel(slot))return false;
            vc.stream_phase=8u;return true;
        }
        for(uint32_t i=0;i<16u;++i)vc.stream_packet[i]=0;
        vc.stream_packet[0]=0xf1a55a1fu;vc.stream_packet[1]=vc.host_channel[1];
        vc.stream_packet[2]=97u;vc.stream_packet[3]=48u;
        vc.stream_packet[5]=vc.packet.key?1u:0u;vc.stream_packet[6]=duration_ms(vc.packet.dts,vc.movie.timescale);
        vc.stream_packet[7]=vc.stream_frames+1u;vc.stream_packet[9]=vc.packet.bytes;
        /* Fragment bits: first=1, last=2; an entire sample carries both. */
        vc.stream_packet[10]=3u;vc.stream_packet[11]=vc.stream_address;
        for(uint32_t i=vc.packet.bytes;i<((vc.packet.bytes+15u)&~15u);++i)vc.frame[i]=0;
        vc.stream_at=0;vc.stream_phase=3u;return true;
    }
    if(vc.host_channel[2]!=65u||vc.stream_phase)return true;
    if((vc.host_channel[3]&0xffffu)!=1312u||available<1328u||count<40u)return false;
    vc.stream_address=vc.host_channel[6];vc.stream_capacity=vc.host_channel[7];
    if(!vc.stream_address||(vc.stream_address&15u)||vc.stream_capacity<vc.packet.bytes||vc.stream_capacity>0x100000u||vc.stream_address>0x10000000u-vc.stream_capacity)return false;
    rd=lo+((rd-lo+1328u-count)%(hi-lo));c[12]=(c[12]&0xffff0000u)|rd;
    if(!ln_m25_bcm_write(record+48u,c+12,4u)||!notify_channel(slot))return false;
    for(uint32_t i=0;i<332u;++i)vc.stream_packet[i]=0;
    vc.stream_packet[0]=0xf1a55a1fu;vc.stream_packet[1]=vc.host_channel[1];vc.stream_packet[2]=96u;vc.stream_packet[3]=1312u;
    uint8_t config[256];uint32_t config_bytes=vc.movie.config_bytes;
    for(uint32_t i=0;i<config_bytes;++i)config[i]=vc.movie.config[i];
    if(vc.movie.nal_bytes){
        const uint8_t *source=vc.movie.config;uint32_t at=6u,out=0,count=source[5]&31u;
        for(uint32_t group=0;group<2u;++group){
            if(group){if(at>=vc.movie.config_bytes)return false;count=source[at++];}
            for(uint32_t item=0;item<count;++item){
                if(at+2u>vc.movie.config_bytes)return false;
                uint32_t size=((uint32_t)source[at]<<8)|source[at+1u];at+=2u;
                if(!size||size>vc.movie.config_bytes-at||size+4u>sizeof config-out)return false;
                config[out++]=0;config[out++]=0;config[out++]=0;config[out++]=1;
                for(uint32_t i=0;i<size;++i)config[out++]=source[at++];
            }
        }
        config_bytes=out;
    }
    uint32_t *p=vc.stream_packet+4;p[0]=1u;p[1]=duration_ms(vc.movie.duration,vc.movie.timescale);p[2]=p[4]=p[5]=1u;
    p+=8u;p[0]=1u;p[1]=vc.movie.nal_bytes?0x48323634u:0x4d504734u;p[4]=config_bytes;
    for(uint32_t i=0;i<config_bytes;++i)p[5u+i]=config[i];
    p+=5u+config_bytes;p[0]=vc.movie.width;p[1]=vc.movie.height;p[2]=1u;/* Retail ARM 0x1cab94 preserves avcC lengthSizeMinusOne. */
    p[53]=vc.movie.nal_bytes?vc.movie.nal_bytes-1u:0u;
    vc.stream_phase=1u;vc.stream_at=0;return true;
}
static uint32_t file_record(void){return vc.header[3]+((vc.directory[vc.file_slot/2u]>>((vc.file_slot&1u)*16u))&0xffffu);}
static bool service_resets(void){
    for(uint32_t slot=0;slot<8u;++slot){
        uint32_t *c=vc.channel[slot],tag=halfword(c,4u);
        if(tag!=6u&&tag!=7u)continue;
        uint32_t off=(vc.directory[slot/2u]>>((slot&1u)*16u))&0xffffu,record=vc.header[3]+off;
        if(!ln_m25_bcm_read(record+64u,c+16,4u))return false;
        uint32_t lo=halfword(c,10),hi=halfword(c,12),rd=halfword(c,48),wr=halfword(c,64);
        if(!ring_valid(lo,hi,rd)||!ring_valid(lo,hi,wr))return false;
        uint32_t available=wr>=rd?wr-rd:hi-rd+wr-lo;
        if(available<16u)continue;
        uint32_t message[8]={0};
        if(!ring_transfer(false,lo,hi,&rd,message,16u)||message[0]!=0xf1a55a1fu)return false;
        if(tag==6u&&message[2]!=64u){
            uint32_t peek=halfword(c,48),bytes=available>128u?128u:available;
            if(!ring_transfer(false,lo,hi,&peek,vc.host_event,bytes))return false;
        }
        bool clock=tag==6u&&message[2]==70u;
        bool notification=tag==6u&&message[2]==71u&&(message[3]&0xffffu)==8u;
        if(!notification&&((message[2]!=64u&&!clock)||(message[3]&0xffffu)!=0u))continue;
        if(notification){
            if(available<32u)continue;
            if(!ring_transfer(false,lo,hi,&rd,message+4,16u))return false;
        }
        uint32_t txlo=halfword(c,6),txhi=halfword(c,8),txwr=halfword(c,32);
        if(!ln_m25_bcm_read(record+16u,c+4,4u))return false;
        uint32_t txrd=halfword(c,16);
        if(!ring_valid(txlo,txhi,txrd)||!ring_valid(txlo,txhi,txwr))return false;
        uint32_t used=txwr>=txrd?txwr-txrd:txhi-txrd+txwr-txlo;
        if(txhi-txlo-used<48u)continue;
        c[12]=(c[12]&0xffff0000u)|rd;
        if(!ln_m25_bcm_write(record+48u,c+12,4u))return false;
        message[2]=clock&&!vc.epoch_valid?1u:0u;message[3]=notification?0u:4u;
        if(clock)message[4]=vc.epoch_valid?vc.epoch+(ln_time_us()-vc.epoch_at)/1000000u:10u;
        if(!ring_transfer(true,txlo,txhi,&txwr,message,notification?16u:32u))return false;
        c[8]=(c[8]&0xffff0000u)|txwr;
        if(!ln_m25_bcm_write(record+32u,c+8,4u)||!notify_channel(slot))return false;
    }
    return true;
}
static void file_response(bool ok,uint32_t value,uint32_t bytes){
    vc.fs_packet[2]=ok?0u:1u;vc.fs_packet[3]=bytes;vc.fs_packet[4]=value;
    vc.fs_tx_bytes=16u+((bytes+15u)&~15u);vc.fs_tx_at=0;vc.fs_phase=3u;
}
static bool same_name(const char *a,const char *b){
    while(*a&&*b){char c=*a++;if(c>='a'&&c<='z')c-=32;if(c!=*b++)return false;}
    return !*a&&!*b;
}
static const char *codec_path(const char *name){
    const char *base=name;
    for(const char *p=name;*p;++p)if(*p=='/'||*p=='\\')base=p+1;
    if(same_name(base,"MPLAYER")||same_name(base,"MPLAYER.VLL"))return "/.LINNET/BCM/MPLAYER.VLL";
    if(same_name(base,"H264DEC.VLL"))return "/.LINNET/BCM/H264DEC.VLL";
    if(same_name(base,"MPG4DEC.VLL"))return "/.LINNET/BCM/MPG4DEC.VLL";
    if(same_name(base,"AACDEC.VLL"))return "/.LINNET/BCM/AACDEC.VLL";
    if(same_name(base,"PASSTHRUHANDLER.VLL"))return "/.LINNET/BCM/PASSTHRU.VLL";
    return 0;
}
/* The VC file service owns no disk writes. Library names map to an explicit
 * local resource set; handles and offsets are bounded independently of VC. */
static bool file_service(void){
    if(vc.read_active||vc.read_io)return true;
    if(vc.file_slot>=8u)return true;
    uint32_t *c=vc.channel[vc.file_slot],record=file_record(),n=0;
    if(vc.fs_phase==1u||vc.fs_phase==2u){
        int result=ln_storage_media_poll_deferred(vc.generation,&vc.files[vc.fs_fd].file,&n);
        if(!result)return true;
        if(result<0){file_response(false,(uint32_t)-7009,4u);return true;}
        if(vc.fs_phase==1u){vc.files[vc.fs_fd].open=true;vc.files[vc.fs_fd].position=0;file_response(true,vc.fs_fd+1u,4u);}
        else{
            vc.files[vc.fs_fd].position+=n;vc.fs_bytes+=n;
            for(uint32_t i=n;i<((n+15u)&~15u);++i)((uint8_t *)(vc.fs_packet+8))[i]=0;
            file_response(true,n/vc.fs_element_size,16u+n);
        }
        return true;
    }
    if(vc.fs_phase==3u){
        if(!ln_m25_bcm_read(record+16u,c+4,4u))return false;
        uint32_t lo=halfword(c,6),hi=halfword(c,8),rd=halfword(c,16),wr=halfword(c,32);
        if(!ring_valid(lo,hi,rd)||!ring_valid(lo,hi,wr))return false;
        uint32_t used=wr>=rd?wr-rd:hi-rd+wr-lo;
        if(vc.fs_tx_bytes>hi-lo-16u-used)return true;
        if(!vc.fs_tx_at)vc.fs_wr=wr;
        n=vc.fs_tx_bytes-vc.fs_tx_at;if(n>128u)n=128u;
        if(!ring_transfer(true,lo,hi,&vc.fs_wr,vc.fs_packet+vc.fs_tx_at/4u,n))return false;
        vc.fs_tx_at+=n;
        if(vc.fs_tx_at==vc.fs_tx_bytes){
            c[8]=(c[8]&0xffff0000u)|vc.fs_wr;
            if(!ln_m25_bcm_write(record+32u,c+8,4u)||!notify_channel(vc.file_slot))return false;
            vc.fs_phase=0;
        }
        return true;
    }
    if(!ln_m25_bcm_read(record+64u,c+16,4u))return false;
    uint32_t lo=halfword(c,10),hi=halfword(c,12),rd=halfword(c,48),wr=halfword(c,64);
    if(!ring_valid(lo,hi,rd)||!ring_valid(lo,hi,wr))return false;
    uint32_t available=wr>=rd?wr-rd:hi-rd+wr-lo;
    if(available<16u)return true;
    if(!ring_transfer(false,lo,hi,&rd,vc.fs_packet,16u)||vc.fs_packet[0]!=0xf1a55a1fu)return false;
    uint32_t length=vc.fs_packet[3]&0xffffu,padded=(length+15u)&~15u;
    if(length<4u||length>304u)return false;
    if(available<16u+padded)return true;
    for(uint32_t at=0;at<padded;at+=n){n=padded-at;if(n>128u)n=128u;if(!ring_transfer(false,lo,hi,&rd,vc.fs_packet+4u+at/4u,n))return false;}
    for(uint32_t j=0;j<32u;++j)vc.host_request[j]=j<(16u+padded)/4u?vc.fs_packet[j]:0;
    c[12]=(c[12]&0xffff0000u)|rd;
    if(!ln_m25_bcm_write(record+48u,c+12,4u)||!notify_channel(vc.file_slot))return false;
    ++vc.fs_count;vc.fs_opcode=vc.fs_packet[2];
    uint32_t fd=vc.fs_packet[4],arg=vc.fs_packet[5],arg2=vc.fs_packet[6];
    vc.fs_packet[3]=0;
    if(vc.fs_opcode==76u){
        if(length<=16u||fd!=1u){file_response(false,(uint32_t)-7003,4u);return true;}
        char *name=(char *)(vc.fs_packet+8);bool terminated=false;
        for(uint32_t j=0;j<length-16u;++j)if(!name[j]){terminated=true;break;}
        const char *path=terminated?codec_path(name):0;
        for(vc.fs_fd=0;vc.fs_fd<8u&&vc.files[vc.fs_fd].open;++vc.fs_fd){}
        if(!path||vc.fs_fd==8u){file_response(false,(uint32_t)-7001,4u);return true;}
        int result=ln_storage_media_open(path,vc.generation);
        if(result!=1){file_response(false,(uint32_t)-7009,4u);return true;}
        vc.fs_phase=1u;return true;
    }
    if(!fd||fd>8u||!vc.files[fd-1u].open){file_response(false,(uint32_t)-7001,4u);return true;}
    vc.fs_fd=fd-1u;
    if(vc.fs_opcode==65u){vc.files[vc.fs_fd].open=false;file_response(true,0,4u);return true;}
    if(vc.fs_opcode==67u&&length>=12u){
        int64_t position=(int32_t)arg;
        if(arg2==1u)position+=vc.files[vc.fs_fd].position;
        else if(arg2==2u)position+=vc.files[vc.fs_fd].file.size;
        else if(arg2!=0u)position=-1;
        if(position<0||position>vc.files[vc.fs_fd].file.size)file_response(false,(uint32_t)-7002,4u);
        else{vc.files[vc.fs_fd].position=(uint32_t)position;file_response(true,(uint32_t)position,4u);}
        return true;
    }
    if(vc.fs_opcode==68u&&length>=12u){
        /* VC02 READ is fread(fd, element_size, count), unlike the later
         * VCHI service's offset/count request. Position changes use LSEEK. */
        uint32_t position=vc.files[vc.fs_fd].position;
        if(position>vc.files[vc.fs_fd].file.size||!arg||arg>8192u||arg2>8192u/arg){file_response(false,(uint32_t)-7002,4u);return true;}
        n=vc.files[vc.fs_fd].file.size-position;if(n>arg*arg2)n=arg*arg2;
        vc.fs_requested=n;vc.fs_element_size=arg;
        if(!n){vc.fs_packet[5]=vc.fs_packet[6]=vc.fs_packet[7]=0;file_response(true,0,16u);return true;}
        int result=ln_storage_media_read(&vc.files[vc.fs_fd].file,position,vc.fs_packet+8,n,vc.generation);
        if(result!=1){file_response(false,(uint32_t)-7009,4u);return true;}
        vc.fs_phase=2u;return true;
    }
    file_response(false,(uint32_t)-7002,4u);return true;
}
static void recover(uint32_t error){
    vc.clock_ms=ln_m25_coprocessor_position();vc.clock_us=ln_time_us();vc.clock_valid=true;vc.paused=true;
    if(vc.audio_ready){ln_audio_snapshot(&vc.audio_status);if(!ln_audio_stop()&&!error)error=49u;vc.audio_ready=false;}
    if(vc.fs_phase==1u||vc.fs_phase==2u||vc.read_io||vc.io){ln_storage_media_cancel(vc.generation);vc.fs_canceling=true;}
    vc.read_active=vc.read_io=vc.io=false;
    vc.fs_phase=0;
    if(!vc.error)vc.error=error;++vc.revision;
    if(!vc.owned){unmap_rom();phase(FAILED,0);return;}
    if(vc.restore){
        vc.restore_error=error;phase(FAILED,0);
        /* A failed NOR reload still owns the display bus. Return through the
         * platform recovery path, which resets if presentation cannot drain. */
        ln_panic(32u,0,error);
    }
    vc.restore=1u;vc.at=0;REG(0x70000080u)&=~0x4000u;phase(POWER_OFF,50000u);
}
static bool direct_file;
bool ln_m25_coprocessor_begin(uint32_t operation){
    if(vc.owned||vc.fs_canceling||(vc.phase!=IDLE&&vc.phase!=FAILED&&vc.phase!=RESTORED))return false;
    direct_file=false;
    struct ln_calendar calendar;
    vc.epoch_valid=ln_power_calendar_read(&calendar);vc.epoch_at=ln_time_us();vc.epoch=0;
    if(vc.epoch_valid){
        static const uint8_t days[]={31,28,31,30,31,30,31,31,30,31,30,31};
        uint32_t years=calendar.year-2000u,total=years*365u+(years+3u)/4u+calendar.day-1u;
        for(uint32_t month=1;month<calendar.month;++month)total+=days[month-1u]+(month==2u&&!(calendar.year&3u));
        vc.epoch=946684800u+total*86400u+calendar.hour*3600u+calendar.minute*60u+calendar.second;
    }
    uint32_t info=REG(0x4001ff1cu);
    if((info&3u)||info<0x40000000u||info>0x4001ff00u-0x88u||REG(0x4001ff18u)!=0x53797349u){vc.error=51u;phase(FAILED,0);return false;}
    /* Retail display selection uses the SysCfg model/revision at +0x84;
     * the older boardHwRev field at +0x48 is zero on production M25. */
    vc.board_revision=REG(info+0x84u);
    if((vc.board_revision>>16)!=0xbu){vc.error=51u;phase(FAILED,0);return false;}
    if(!rom_image()){vc.error=18u;phase(FAILED,0);return false;}
    vc.error=vc.restore_error=vc.restore=vc.at=vc.hash_at=vc.requested=0;vc.io=false;
    vc.normal=vc.paused=vc.want_paused=vc.seek_pending=vc.clock_valid=vc.syncing_seek=vc.seek_seen=false;vc.seek_ms=vc.position_base=vc.seek_frames=0;++vc.revision;
    vc.audio_ready=vc.audio_started=vc.audio_eof=false;vc.audio_phase=vc.audio_frames=vc.start_elapsed=0;vc.audio_status=(struct ln_audio_status){0};
    for(uint32_t i=0;i<2u;++i)vc.cache[i]=(__typeof__(vc.cache[0])){0};
    for(uint32_t i=0;i<4u;++i)vc.header[i]=vc.directory[i]=vc.legacy_header[i]=0;
    for(uint32_t i=0;i<8u;++i)for(uint32_t j=0;j<20u;++j)vc.channel[i][j]=0;
    vc.slot=0;
    vc.reply_bytes=0;vc.command_slot=8u;
    vc.command_index=vc.reply_parsed=0;
    vc.operation=operation;vc.file_slot=8u;vc.control=vc.seek_stage=0;
    vc.fs_phase=vc.fs_count=vc.fs_opcode=vc.fs_bytes=0;
    vc.stream_phase=vc.stream_at=vc.stream_address=vc.stream_capacity=vc.stream_frames=0;vc.read_active=vc.read_io=false;
    for(uint32_t i=0;i<8u;++i)vc.files[i].open=false;
    for(uint32_t i=0;i<256u;++i)vc.reply[i]=0;
    for(uint32_t i=0;i<32u;++i)vc.host_channel[i]=vc.host_request[i]=0;
    if(++vc.generation<0x7a000000u||vc.generation>=0x7b000000u)vc.generation=0x7a000000u;
    /* Idle scheduling can space service calls by 64 ms. Keep each NOR read
     * small, but allow a full validation at that cadence. */
    phase(ROM_CHECK,30000000u);return true;
}
bool ln_m25_coprocessor_control(uint32_t command){
    if(command<1u||command>5u||vc.operation!=2u||vc.phase!=PLAYER_SETTLE||vc.command_index!=8u||vc.control)return false;
    if(command>=4u){vc.seek_forward=command==4u;vc.seek_ms=command==4u?10000u:2000u;command=4u;}
    vc.control=command;vc.return_deadline=vc.deadline;phase(VERSION_SEND,5000000u);return true;
}
bool ln_m25_coprocessor_active(void){return vc.fs_canceling||(vc.phase!=IDLE&&vc.phase!=RESTORED&&vc.phase!=FAILED);}
uint32_t ln_m25_coprocessor_deadline(uint32_t now){
    if(!ln_m25_coprocessor_active())return now+200000u;
    /* Poll an empty BCM request ring at the LCD wait cadence only after
     * startup, with no host work and a full PCM reserve. IRQs still wake us. */
    if(vc.phase!=PLAYER_SETTLE||!vc.normal||vc.command_index!=8u||vc.control||
       vc.restore||vc.fs_canceling||vc.fs_phase||vc.read_active||vc.seek_pending||vc.seek_stage||
       vc.want_paused!=vc.paused||!vc.stream_waiting)return now;
#if !defined(LINNET_PROFILE_RELEASE)
    if(fault_mode)return now;
#endif
    if(vc.audio_ready){
        struct ln_audio_status a;ln_audio_snapshot(&a);
        if(a.fault||(!vc.audio_eof&&a.queued<AUDIO_BUFFER_FRAMES))return now;
    }
    if((int32_t)(vc.deadline-now)<=0)return now;
    return (int32_t)(vc.deadline-now)<1000?vc.deadline:now+1000u;
}
bool ln_m25_coprocessor_open(const char *path,uint8_t options){
    if(!path||path[0]!='/')return false;uint32_t n=0;while(path[n]&&n<255u)++n;if(!n||n==255u)return false;
    if(!ln_m25_coprocessor_begin(2u))return false;
    for(uint32_t i=0;i<=n;++i)vc.path[i]=path[i];vc.normal=true;vc.options=options;return true;
}
void ln_m25_coprocessor_file(const struct ln_fat32_file*file){vc.video_file=*file;direct_file=true;}
void ln_m25_coprocessor_stop(void){if(ln_m25_coprocessor_active()&&!vc.restore)recover(0);}
void ln_m25_coprocessor_pause(bool paused){vc.want_paused=paused;++vc.revision;}
bool ln_m25_coprocessor_paused(void){return vc.want_paused;}
uint32_t ln_m25_coprocessor_position(void){
    uint32_t position=vc.clock_valid?vc.clock_ms+(!vc.paused?(ln_time_us()-vc.clock_us)/1000u:0u):vc.position_base;
    if(vc.audio_ready&&vc.audio_started){
        struct ln_audio_status a;ln_audio_snapshot(&a);
        /* Audio can end before the last video frame. Once PCM is drained,
         * use the coprocessor clock so the shorter soundtrack cannot stall EOF. */
        uint32_t audio_position=vc.position_base+duration_ms(a.consumed,a.rate);
        if(!vc.audio_eof||a.queued||a.playing||audio_position>position)return audio_position;
    }
    return position;
}
bool ln_m25_coprocessor_seek(uint32_t ms){
    if(!vc.normal||!vc.movie.opened||vc.restore||!ln_m25_coprocessor_active())return false;
    uint32_t duration=duration_ms(vc.movie.duration,vc.movie.timescale);if(!duration)return false;
    if(ms>=duration){recover(0);vc.clock_ms=duration;return true;}vc.requested_seek=ms;vc.seek_pending=true;++vc.revision;return true;
}
uint32_t ln_m25_coprocessor_duration(void){return vc.movie.opened?duration_ms(vc.movie.duration,vc.movie.timescale):0u;}
uint32_t ln_m25_coprocessor_revision(void){return vc.revision;}
uint32_t ln_m25_coprocessor_error(void){return vc.error?vc.error:vc.restore_error;}
bool ln_m25_coprocessor_owned(void){return vc.owned;}
#if !defined(LINNET_PROFILE_RELEASE)
bool ln_m25_coprocessor_fault(uint32_t mode){
    if(mode<1u||mode>2u||fault_mode||!vc.owned||vc.restore||vc.phase!=PLAYER_SETTLE)return false;
    /* Defer until after the Link acknowledgement has drained. No disk writes
     * are permitted while video owns the media/display resources. */
    fault_mode=mode;fault_deadline=ln_time_us()+500000u;return true;
}
#endif
/* Returns true once the ROM display runtime is restored. Every invocation is
 * bounded; disk waits, power delays and firmware waits return to the executive. */
bool ln_m25_coprocessor_step(void){
    uint32_t value=0,n=0;int result;
#if !defined(LINNET_PROFILE_RELEASE)
    if(fault_mode&&(int32_t)(ln_time_us()-fault_deadline)>=0){
        uint32_t mode=fault_mode;fault_mode=0;
        if(vc.owned&&!vc.restore){
            if(vc.audio_ready)ln_audio_pause();
            if(mode==1u){
                /* Exercise the actual external-bus access with BCM clocked
                 * off. The independent COP lease handles a stalled CPU. */
                REG(0x70000080u)&=~0x4000u;
                (void)REG(0x70000080u);
                (void)ln_m25_bcm_read(0x1f0u,&value,1u);
                recover(52u);
            }else{
                recover(52u);
                recover(53u);
            }
        }
        return false;
    }
#endif
    if(vc.fs_canceling&&ln_storage_media_poll_deferred(vc.generation,0,&n))vc.fs_canceling=false;
    if(vc.phase==IDLE||vc.phase==FAILED||vc.phase==RESTORED)return false;
    if(vc.phase==ROM_CHECK){
        if(expired()){recover(16);return false;}
        n=vc.rom_bytes-vc.rom_checked;if(n>512u)n=512u;
        for(uint32_t i=0;i<n;++i)vc.rom_sum+=vc.rom[vc.rom_checked+i];
        vc.rom_checked+=n;
        if(vc.rom_checked==vc.rom_bytes){
            if(vc.rom_sum!=vc.rom_expected)recover(17);else phase(OPEN,60000000u);
        }
        return false;
    }
    if(vc.phase==OPEN||vc.phase==READ){
        if(vc.io){
            result=ln_storage_media_poll_deferred(vc.generation,&vc.file,&n);
            if(!result){if(expired())ln_storage_media_cancel(vc.generation);return false;}
            vc.io=false;
            if(result<0){recover(0x100u+(uint32_t)-result);return false;}
            if(vc.phase==OPEN){
                if(vc.file.size!=sizeof vc.image){recover(2);return false;}
                phase(READ,60000000u);
            }else{
                if(n!=vc.requested){recover(3);return false;}
                vc.at+=n;
                if(vc.at==sizeof vc.image){ln_sha256_init(&vc.hash);phase(HASH,5000000u);}
            }
            return false;
        }
        if(expired()){recover(4);return false;}
        if(vc.phase==OPEN)result=ln_storage_media_open("/.LINNET/BCM/VMCS.BIN",vc.generation);
        else{
            n=sizeof vc.image-vc.at;if(n>16384u)n=16384u;vc.requested=n;
            result=ln_storage_media_read(&vc.file,vc.at,vc.image+vc.at,n,vc.generation);
        }
        if(result<0)recover(5);else if(result>0)vc.io=true;
        return false;
    }
    if(vc.phase==HASH){
        n=sizeof vc.image-vc.hash_at;if(n>2048u)n=2048u;
        ln_sha256_update(&vc.hash,vc.image+vc.hash_at,n);vc.hash_at+=n;
        if(vc.hash_at==sizeof vc.image){
            uint8_t digest[32];ln_sha256_finish(&vc.hash,digest);
            for(uint32_t i=0;i<32u;++i)if(digest[i]!=expected_sha[i]){recover(6);return false;}
            phase(vc.operation==2u?MEDIA_OPEN:ACQUIRE,vc.operation==2u?60000000u:1000000u);
        }
        return false;
    }
    if(vc.phase==ACQUIRE){
        if(ln_display_busy()){if(expired())recover(7);return false;}
        vc.owned=true;vc.at=0;REG(0x70000080u)&=~0x4000u;phase(POWER_OFF,50000u);return false;
    }
    if(vc.phase==MEDIA_OPEN){
        if(direct_file){direct_file=false;ln_mp4_init(&vc.movie,video_read,0,vc.video_file.size);phase(MEDIA_SCAN,60000000u);return false;}
        if(expired()){recover(41);return false;}
        if(vc.io){
            result=ln_storage_media_poll_deferred(vc.generation,&vc.video_file,&n);
            if(!result)return false;vc.io=false;
            if(result<0){recover(40);return false;}
            ln_mp4_init(&vc.movie,video_read,0,vc.video_file.size);phase(MEDIA_SCAN,60000000u);
        }else{
            result=ln_storage_media_open(vc.normal?vc.path:"/Videos/MOTION.mp4",vc.generation);
            if(result<0)recover(40);else if(result>0)vc.io=true;
        }
        return false;
    }
    if(vc.phase==MEDIA_SCAN||vc.phase==MEDIA_PACKET||vc.phase==MEDIA_FRAME){
        if(expired()){recover(41);return false;}
        if(vc.phase==MEDIA_SCAN){
            result=ln_mp4_open_step(&vc.movie);
            if(result<0)recover(0x300u+(uint32_t)-result);
            else if(result>0){
                if(vc.movie.config_bytes>256u||vc.movie.width>640u||vc.movie.height>480u||
                   (vc.movie.nal_bytes&&(vc.movie.config[1]!=66u||vc.movie.config[3]>13u||vc.movie.width>320u||vc.movie.height>240u)))recover(42);
                else phase(MEDIA_PACKET,30000000u);
            }
        }else if(vc.phase==MEDIA_PACKET){
            result=ln_mp4_next(&vc.movie,&vc.packet);
            if(result<0||result==LN_MP4_EOF)recover(43);else if(result>0)phase(MEDIA_FRAME,30000000u);
        }else{
            result=video_read(0,vc.packet.offset,vc.frame,vc.packet.bytes);
            if(result<0)recover(44);else if(result>0){ln_mp4_init_audio(&vc.soundtrack,video_read,(void *)1u,vc.video_file.size);phase(AUDIO_SCAN,60000000u);}
        }
        return false;
    }
    if(vc.phase==AUDIO_SCAN){
        if(expired()){recover(47);return false;}
        result=ln_mp4_open_step(&vc.soundtrack);
        if(result==LN_MP4_EOF)phase(ACQUIRE,1000000u);
        else if(result<0)recover(0x400u+(uint32_t)-result);
        else if(result>0){
            if(ln_aac_raw_init(&audio_decoder,vc.soundtrack.config,vc.soundtrack.config_bytes)!=1||audio_decoder.rate!=vc.soundtrack.rate||!ln_audio_init(audio_decoder.rate)){recover(48);return false;}
            vc.audio_ready=true;vc.audio_phase=1u;vc.audio_skip=vc.soundtrack.lead;phase(AUDIO_PRIME,30000000u);
        }
        return false;
    }
    if(vc.phase==AUDIO_PRIME){
        if(expired()||!audio_service()){recover(49);return false;}
        if(vc.audio_frames>=AUDIO_PRIME_FRAMES||vc.audio_eof)phase(ACQUIRE,1000000u);
        return false;
    }
    if(vc.phase==POWER_OFF){
        if(expired()){REG(0x70000080u)|=0x4000u;phase(POWER_ON,50000u);}return false;
    }
    if(vc.phase==POWER_ON){
        if(expired()){
            REG(0x70000008u)&=~0xf00u;REG(0x70000040u)=0x1313u;
            phase(BUS_READY,1000000u);
        }
        return false;
    }
    if(vc.phase==SYNC_WAIT){
        /* Keep PCM and native stream requests moving between status polls. */
        if(!service_resets()){recover(36);return false;}
        if(!file_service()){recover(30);return false;}
        if(!audio_service()||!stream_service()){recover(37);return false;}
        if(expired())phase(VERSION_SEND,5000000u);
        return false;
    }
    if(vc.phase==PLAYER_SETTLE){
        if(!service_resets()||!file_service()||!audio_service()||!stream_service()){recover(36);return false;}
        if(vc.normal&&vc.command_index==8u){
            uint32_t command=0;
            if(vc.seek_pending&&vc.paused)command=2u;
            else if(vc.seek_pending){
                vc.seek_forward=vc.requested_seek>=ln_m25_coprocessor_position();vc.seek_ms=vc.requested_seek;vc.seek_pending=false;command=4u;
            }else if(vc.want_paused!=vc.paused)command=vc.want_paused?1u:2u;
            else if(expired()){
                uint32_t duration=duration_ms(vc.movie.duration,vc.movie.timescale);
                struct ln_audio_status audio={0};
                if(vc.audio_ready)ln_audio_snapshot(&audio);
                /* The video completion tolerance must not discard the final
                 * PCM block. Wait for the soundtrack and DMA queue to drain. */
                if(vc.stream_phase==8u&&ln_m25_coprocessor_position()+80u>=duration&&
                   (!vc.audio_ready||(vc.audio_eof&&!audio.queued&&!audio.playing))){recover(0);return false;}
                command=3u;
            }
            if(command){vc.control=command;vc.return_deadline=vc.deadline;phase(VERSION_SEND,5000000u);}
        }else if(expired()){++vc.command_index;phase(VERSION_SEND,5000000u);}
        return false;
    }
    if(expired()){recover(vc.phase==OBSERVE?0u:0x200u+vc.phase);return false;}
    switch(vc.phase){
    case BUS_READY:
        value=HALF(0x30070000u);
        if(!(value&0x80u)&&(value&0x40u))phase(BUS_SETUP,1000000u);
        break;
    case BUS_SETUP:{
        static const uint8_t controls[]={0xa1,0x81,0x91,0x02,0x12,0x22,0x72,0x62};
        for(uint32_t i=0;i<8u;++i)HALF(0x30030000u)=controls[i];
        for(uint32_t i=3;i<8u;++i)HALF(0x30070000u)=controls[i];
        phase(BUS_LATCH,1000000u);break;}
    case BUS_LATCH:
        if((HALF(0x30020000u)&1u)&&(HALF(0x30060000u)&1u)){
            (void)HALF(0x30010000u);(void)HALF(0x30050000u);
            value=HALF(0x30070000u);
            if(!(value&0x80u)&&(value&0x40u))phase(UPLOAD,5000000u);
        }
        break;
    case UPLOAD:{
        const uint8_t *source=vc.restore?vc.rom:vc.image;
        uint32_t bytes=vc.restore?vc.rom_bytes:sizeof vc.image;
        n=bytes-vc.at;if(n>4096u)n=4096u;
        if(!ln_m25_bcm_write(vc.at,(const uint32_t *)(source+vc.at),n/4u)){recover(8);break;}
        vc.at+=n;if(vc.at==bytes)phase(VALIDATE_BEGIN,1000000u);break;}
    case VALIDATE_BEGIN:
        /* RetailOS at 0x265518 selects model 1 for family 0xb revisions
         * below 0x10, and model 2 for revisions from 0x10 onward. */
        if(!vc.restore&&!put(0x1f4u,(vc.board_revision&0xffffu)>=0x10u?2u:1u)){recover(9);break;}
        if(!put(0x1f8u,0)||!put(0x10000c00u,0xc0000000u)){recover(9);break;}
        phase(VALIDATE_WAIT,2000000u);break;
    case VALIDATE_WAIT:
        if(!ln_m25_bcm_read(0x10000c00u,&value,1u)){recover(10);break;}
        if(value&1u)phase(EXECUTE,1000000u);break;
    case EXECUTE:
        if(!put(0x10000c00u,0)||!put(0x10000400u,0xa5a50002u)){recover(11);break;}
        phase(READY_WAIT,5000000u);break;
    case READY_WAIT:{
        uint32_t *header=vc.restore?vc.legacy_header:vc.header;
        if(!ln_m25_bcm_read(0x1f0u,header,4u)){recover(12);break;}
        if(header[2]){
            if(vc.restore){vc.owned=false;unmap_rom();phase(RESTORED,0);return true;}
            if(header[2]!=1u||!header[3]||(header[3]&3u)||header[3]>0xffffffefu){recover(13);break;}
            phase(DIRECTORY,1000000u);
        }
        break;}
    case DIRECTORY:
        if(!ln_m25_bcm_read(vc.header[3],vc.directory,4u)){recover(14);break;}
        phase(CHANNELS,1000000u);break;
    case CHANNELS:{
        uint32_t offset=(vc.directory[vc.slot/2u]>>((vc.slot&1u)*16u))&0xffffu;
        if(offset){
            if((offset&15u)||vc.header[3]>0xffffffffu-offset-80u){recover(19);break;}
            if(!ln_m25_bcm_read(vc.header[3]+offset,vc.channel[vc.slot],20u)){recover(20);break;}
            if(halfword(vc.channel[vc.slot],4u)==1u)vc.command_slot=vc.slot;
            if(halfword(vc.channel[vc.slot],4u)==5u)vc.file_slot=vc.slot;
        }
        if(++vc.slot==8u)phase(VERSION_SEND,5000000u);
        break;}
    case VERSION_SEND:{
        if(!service_resets()){recover(36);break;}
        if(vc.command_slot>=8u){recover(21);break;}
        uint32_t *c=vc.channel[vc.command_slot];
        uint32_t offset=(vc.directory[vc.command_slot/2u]>>((vc.command_slot&1u)*16u))&0xffffu;
        if(!ln_m25_bcm_read(vc.header[3]+offset+16u,c+4,4u)){recover(25);break;}
        uint32_t lo=halfword(c,6),hi=halfword(c,8),rd=halfword(c,16),wr=halfword(c,32);
        if(!ring_valid(lo,hi,rd)||!ring_valid(lo,hi,wr)||rd!=wr||hi-lo<48u){recover(22);break;}
        static const char *const native_commands[]={"load_application mplayer","display_control 0 model=2 power=2","display_control 0 freeze=0","vmcs_display_enable","mp_selectplay passthru:linnet 0","mp_pause","mp_region display=0 dest=\"0 0 320 240\" mode=fill","mp_play","mp_get_status","mp_get_stats video"};
        static const char *const tv_encoding[]={"display_control 2 dac=1 encoding=0","display_control 2 dac=1 encoding=1"};
        static const char *const tv_shape[]={"display_control 2 svideo=0 wide=0","display_control 2 svideo=0 wide=1","display_control 2 svideo=1 wide=0","display_control 2 svideo=1 wide=1"};
        static const char *const lcd_region="mp_region display=0 dest=\"0 0 320 240\" mode=fill";
        char seek_command[32]="mp_seek ";
        if(vc.control==4u){vc.seek_seen=false;uint32_t n=vc.seek_ms,at=8u,divisor=1000000000u;while(divisor>1u&&n<divisor)divisor/=10u;do{seek_command[at++]=(char)('0'+n/divisor);n%=divisor;divisor/=10u;}while(divisor);seek_command[at]=0;}
        bool tv=(vc.options&32u)!=0,wide=(vc.options&8u)!=0,svideo=(vc.options&16u)!=0,pal=(vc.options&4u)!=0;
        const char *native=vc.command_index==1u?tv?tv_encoding[pal?1u:0u]:(vc.board_revision&0xffffu)<0x10u?"display_control 0 model=1 power=2":native_commands[1u]:vc.command_index==2u&&tv?tv_shape[(svideo?2u:0u)|(wide?1u:0u)]:vc.command_index==6u?lcd_region:native_commands[vc.command_index];
        const char *command=vc.control==4u?seek_command:vc.control?(vc.control==1u?"mp_pause":vc.control==2u?"mp_play":"mp_get_status"):vc.operation==2u?native:!vc.operation?"version":vc.command_index==0u?"load_application mplayer":vc.command_index==2u?"mp_selectplay passthru:linnet 0":"mp_get_status";
        uint32_t message[32]={0xf1a55a1fu,vc.command_index+1u,1u,0},length=0;
        while(command[length]){((uint8_t *)(message+4))[length]=(uint8_t)command[length];++length;}
        message[3]=length+1u;length=16u+((length+16u)&~15u);
        if(!ring_transfer(true,lo,hi,&wr,message,length)){recover(23);break;}
        c[8]=(c[8]&0xffff0000u)|wr;
        if(!ln_m25_bcm_write(vc.header[3]+offset+32u,c+8,4u)||!notify_channel(vc.command_slot)){recover(24);break;}
        vc.reply_bytes=vc.reply_parsed=0;
        vc.reply_stream=false;
        for(uint32_t i=0;i<256u;++i)vc.reply[i]=0;
        phase(VERSION_REPLY,vc.operation?120000000u:5000000u);break;}
    case VERSION_REPLY:{
        if(!service_resets()){recover(36);break;}
        if(!file_service()){recover(30);break;}
        if(!audio_service()||!stream_service()){recover(37);break;}
        /* Retain an unconsumed host-request message while qualifying the
         * player stream contract. Unsupported requests never receive success. */
        for(uint32_t slot=0;slot<8u;++slot)if(halfword(vc.channel[slot],4u)==7u){
            uint32_t *h=vc.channel[slot],off=(vc.directory[slot/2u]>>((slot&1u)*16u))&0xffffu;
            if(!ln_m25_bcm_read(vc.header[3]+off+64u,h+16,4u)){recover(31);break;}
            uint32_t lo=halfword(h,10),hi=halfword(h,12),rd=halfword(h,48),wr=halfword(h,64);
            if(!ring_valid(lo,hi,rd)||!ring_valid(lo,hi,wr)){recover(32);break;}
            uint32_t bytes=wr>=rd?wr-rd:hi-rd+wr-lo;
            if(bytes){if(bytes>128u)bytes=128u;if(!ring_transfer(false,lo,hi,&rd,vc.host_channel,bytes)){recover(33);break;}}
        }
        if(vc.phase!=VERSION_REPLY)break;
        uint32_t *c=vc.channel[vc.command_slot];
        uint32_t offset=(vc.directory[vc.command_slot/2u]>>((vc.command_slot&1u)*16u))&0xffffu;
        if(!ln_m25_bcm_read(vc.header[3]+offset+64u,c+16,4u)){recover(25);break;}
        uint32_t lo=halfword(c,10),hi=halfword(c,12),rd=halfword(c,48),wr=halfword(c,64);
        if(!ring_valid(lo,hi,rd)||!ring_valid(lo,hi,wr)){recover(26);break;}
        uint32_t available=wr>=rd?wr-rd:hi-rd+wr-lo;
        if(available<16u)break;
        if(available>128u)available=128u;
        if(available>sizeof vc.reply-vc.reply_bytes){recover(34);break;}
        if(!ring_transfer(false,lo,hi,&rd,vc.reply+vc.reply_bytes/4u,available)){recover(27);break;}
        vc.reply_bytes+=available;
        c[12]=(c[12]&0xffff0000u)|rd;
        if(!ln_m25_bcm_write(vc.header[3]+offset+48u,c+12,4u)||!notify_channel(vc.command_slot)){recover(29);break;}
        while(vc.reply_bytes-vc.reply_parsed>=16u){
            uint32_t *message=vc.reply+vc.reply_parsed/4u,bytes=message[3]&0xffffu;
            if(message[0]!=0xf1a55a1fu||message[1]!=vc.command_index+1u){recover(28);break;}
            bool stream=bytes==0xffffu;
            if(vc.reply_stream){
                /* After the NUL-terminated stream, the final 16-byte header
                 * reports completion; its length is not another payload. */
                if(message[2]>1u){recover(28);break;}bytes=0;
            }else if(stream){
                const uint8_t *text=(const uint8_t *)(message+4);bytes=0;
                uint32_t remaining=vc.reply_bytes-vc.reply_parsed-16u;
                while(bytes<remaining&&text[bytes])++bytes;
                if(bytes==remaining)break;
                ++bytes;
            }
            uint32_t total=16u+((bytes+15u)&~15u);
            if(total>vc.reply_bytes-vc.reply_parsed)break;
            vc.reply_parsed+=total;
            const uint8_t *response=(const uint8_t *)(message+4);
            if(bytes>=7u&&response[0]=='e'&&response[1]=='r'&&response[2]=='r'&&
               response[3]=='o'&&response[4]=='r'&&response[5]=='='&&
               response[6]>='1'&&response[6]<='9'){recover(35);break;}
            if(stream)vc.reply_stream=true;
            if(message[2]<=1u){
                if(message[2]){recover(35);break;}
                if(vc.control){
                    uint32_t position=ln_m25_coprocessor_position();
                    if(vc.control==1u){vc.paused=true;if(vc.audio_ready)ln_audio_pause();}
                    if(vc.control==2u||vc.control==4u){
                        vc.syncing_seek=vc.control==4u;
                        vc.control=6u;vc.sync_deadline=ln_time_us()+15000000u;phase(SYNC_WAIT,10000u);break;
                    }
                    if(vc.control==6u){
                        uint32_t elapsed=elapsed_value(response,bytes);
                        bool waiting=!playback_running(response,bytes)||
                            (vc.syncing_seek&&(!vc.seek_seen||vc.seek_stage||vc.stream_frames==vc.seek_frames));
                        if(waiting){if((int32_t)(ln_time_us()-vc.sync_deadline)>=0){recover(50);break;}phase(SYNC_WAIT,10000u);break;}
                        vc.start_elapsed=elapsed;vc.paused=false;
                        if(vc.audio_ready&&!ln_audio_start()){recover(49);break;}vc.audio_started=vc.audio_ready;
                    }
                    uint32_t elapsed=elapsed_value(response,bytes);
                    if(vc.control==6u&&vc.syncing_seek)elapsed=vc.seek_ms;
                    else if(vc.clock_valid&&elapsed<position)elapsed=position;
                    /* Status can retain the last changed picture's timestamp.
                     * Only an explicit seek may move playback time backward. */
                    vc.clock_ms=elapsed;vc.clock_us=ln_time_us();vc.clock_valid=true;
                    vc.control=0;vc.phase=PLAYER_SETTLE;vc.deadline=vc.normal?ln_time_us()+500000u:vc.return_deadline;++vc.revision;break;
                }
                if(vc.operation==2u&&vc.command_index==7u)vc.sync_deadline=ln_time_us()+5000000u;
                if(vc.operation==2u&&vc.command_index==8u){
                    uint32_t elapsed=elapsed_value(response,bytes);
                    if(!playback_running(response,bytes)){if((int32_t)(ln_time_us()-vc.sync_deadline)>=0){recover(50);break;}phase(SYNC_WAIT,10000u);break;}
                    vc.start_elapsed=elapsed;vc.clock_ms=elapsed;vc.clock_us=ln_time_us();vc.clock_valid=true;
                    if(vc.audio_ready&&!ln_audio_start()){recover(49);break;}vc.audio_started=vc.audio_ready;
                    ++vc.revision;phase(PLAYER_SETTLE,vc.normal?500000u:30000000u);
                }else if(vc.operation==2u&&vc.command_index==6u)phase(PLAYER_SETTLE,2000000u);
                else if(vc.operation==1u&&vc.command_index==2u)phase(PLAYER_SETTLE,2000000u);
                else if(vc.operation&&vc.command_index<(vc.operation==2u?8u:2u)){++vc.command_index;phase(VERSION_SEND,5000000u);}
                else phase(OBSERVE,1000000u);
                break;
            }
        }
        break;}
    case OBSERVE:if(!file_service()||!audio_service()||!stream_service())recover(30);break;
    default:recover(15);break;
    }
    return false;
}
uint32_t ln_m25_coprocessor_snapshot(uint32_t out[32]){
    if(!out)return 0;
    for(uint32_t i=0;i<32u;++i)out[i]=0;
    out[0]=0x4d250002u;out[1]=vc.phase;out[2]=vc.error;out[3]=vc.restore;
    out[4]=vc.at;out[5]=sizeof vc.image;out[6]=vc.rom_bytes;out[7]=vc.owned;
    for(uint32_t i=0;i<4u;++i){out[8+i]=vc.header[i];out[12+i]=vc.directory[i];out[16+i]=vc.legacy_header[i];}
    out[20]=vc.restore_error;out[21]=vc.rom_checked;out[22]=vc.map_logical;out[23]=vc.map_physical;
    for(uint32_t i=0;i<8u;++i)out[24+i]=vc.rom_diagnostic[i];
    return 32u;
}
uint32_t ln_m25_coprocessor_channel(uint32_t slot,uint32_t out[32]){
    if(slot==14u&&out){struct ln_audio_status a=vc.audio_status;if(vc.audio_ready)ln_audio_snapshot(&a);for(uint32_t i=0;i<32u;++i)out[i]=0;out[0]=vc.audio_phase;out[1]=vc.audio_frames;out[2]=vc.soundtrack.samples;out[3]=vc.soundtrack.lead;out[4]=vc.soundtrack.error;out[5]=vc.audio_phase?audio_decoder.error:0u;out[6]=a.rate;out[7]=a.queued;out[8]=a.consumed;out[9]=a.underruns;out[10]=a.fault;out[11]=vc.audio_eof;out[12]=a.silence_frames;out[13]=vc.start_elapsed;out[14]=vc.seek_stage;out[15]=vc.seek_ms;out[16]=vc.board_revision;out[17]=REG(0x4001ff1cu);out[18]=REG(0x4001ff18u);return 32u;}
    if(slot==13u&&out){for(uint32_t i=0;i<32u;++i)out[i]=vc.host_event[i];return 32u;}
    if(slot>=16u&&slot<24u&&out){for(uint32_t i=0;i<32u;++i)out[i]=vc.reply[(slot-16u)*32u+i];return 32u;}
    if(slot==8u&&out){for(uint32_t i=0;i<32u;++i)out[i]=vc.reply[i];return 32u;}
    if(slot==9u&&out){for(uint32_t i=0;i<32u;++i)out[i]=vc.host_request[i];return 32u;}
    if(slot==10u&&out){for(uint32_t i=0;i<32u;++i)out[i]=0;out[0]=vc.fs_count;out[1]=vc.fs_opcode;out[2]=vc.fs_phase;out[3]=vc.fs_bytes;out[4]=vc.fs_requested;out[5]=vc.fs_tx_at;out[6]=vc.fs_tx_bytes;out[7]=vc.command_index;out[8]=vc.reply_bytes;out[9]=vc.reply_parsed;return 32u;}
    if(slot==11u&&out){for(uint32_t i=0;i<32u;++i)out[i]=vc.host_channel[i];return 32u;}
    if(slot==12u&&out){for(uint32_t i=0;i<32u;++i)out[i]=0;out[0]=vc.stream_phase;out[1]=vc.stream_address;out[2]=vc.stream_capacity;out[3]=vc.movie.codec;out[4]=vc.movie.width;out[5]=vc.movie.height;out[6]=vc.movie.timescale;out[7]=vc.movie.config_bytes;out[8]=vc.movie.nal_bytes;out[9]=vc.packet.bytes;out[10]=vc.movie.error;out[11]=vc.stream_frames;return 32u;}
    if(slot>=8u||!out)return 0;
    for(uint32_t i=0;i<32u;++i)out[i]=0;
    out[0]=0x4d250010u+slot;out[1]=vc.phase;out[2]=vc.header[3];
    out[3]=(vc.directory[slot/2u]>>((slot&1u)*16u))&0xffffu;
    for(uint32_t i=0;i<20u;++i)out[4+i]=vc.channel[slot][i];
    return 32u;
}
