#include "kernel/storage_link.h"
#include "services/storage/storage.h"
#include "services/storage/block.h"
#include "hal/api/recovery.h"
#include "hal/api/platform.h"
#if defined(LINNET_IMAGE_OS)
#include "services/update/native.h"
#include "kernel/runtime.h"
#include "hal/api/display.h"
#endif
#if defined(LINNET_VIDEO)
#include "services/video/video.h"
#endif
static uint8_t ln_storage_reply[1024];
static uint8_t ln_storage_restart_pending;
static uint32_t get32(const uint8_t*p){return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put32(uint8_t*p,uint32_t n){for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(n>>(8*i));}
int ln_storage_link_dispatch(const ln_link_frame*q,ln_link_frame*r){
    if(q->command<80||q->command>103||q->flags||!q->sequence||q->length>1024||(q->length&&!q->payload))return 0;
    uint32_t generation=ln_recovery_generation();
    r->command=q->command;r->sequence=q->sequence;r->flags=3;r->payload=ln_storage_reply;r->length=8;
    put32(ln_storage_reply,generation);put32(ln_storage_reply+4,0);
#if defined(LINNET_VIDEO)
    /* Package validation uses STAGE, also owned by retained video records. */
    if((q->command==87u||q->command==102u)&&(ln_video_active()||ln_video_pending()))return 1;
#endif
    switch(q->command){
#if defined(LINNET_IMAGE_OS)
    case 100:
        if(q->length!=40||get32(q->payload)!=generation||!ln_native_begin(get32(q->payload+4),q->payload+8))return 1;
        break;
    case 101:{
        if(q->length<=8||q->length>1016||get32(q->payload)!=generation)return 1;
        uint32_t offset=get32(q->payload+4),n=q->length-8;
        if(!ln_native_write(offset,q->payload+8,n))return 1;
        put32(ln_storage_reply+4,offset+n);break;}
    case 102:
        if(q->length!=4||get32(q->payload)!=generation||!ln_native_apply())return 1;
        break;
    case 103:{
        if(q->length)return 1;uint32_t words[16];ln_native_status(words);
        for(unsigned i=0;i<16;++i)put32(ln_storage_reply+i*4,words[i]);r->length=64;break;}
#endif
    case 80:{
        if(q->length)return 1;uint32_t words[24];ln_storage_state(words);
        for(unsigned i=0;i<24;++i)put32(ln_storage_reply+i*4,words[i]);r->length=96;break;}
    case 94:{
        uint32_t words[32],count=24u;
        if(!q->length)ln_ata_diagnostics(words);
#if !defined(LINNET_PROFILE_RELEASE)
        else if(q->length==4u&&get32(q->payload)==1u){ln_block_performance(words);count=32u;}
        else if(q->length==4u&&get32(q->payload)==2u){ln_storage_media_performance(words);count=16u;}
        else if(q->length==4u&&get32(q->payload)==3u){ln_ata_capabilities(words);count=16u;}
#if defined(LINNET_IMAGE_OS)
        else if(q->length==4u&&get32(q->payload)==4u){ln_runtime_render_timing(words);count=16u;}
        else if(q->length==4u&&get32(q->payload)==7u){ln_display_sync_diagnostics(words);count=16u;}
        else if(q->length==4u&&get32(q->payload)==8u){ln_display_blit_diagnostics(words);count=16u;}
#if defined(LINNET_TARGET_IPOD4G_Q21)
        else if(q->length==4u&&get32(q->payload)==10u){
            extern void ln_runtime_idle_clock_diagnostics(uint32_t output[4]);
            ln_runtime_idle_clock_diagnostics(words);count=4u;
        }

#endif
#if defined(LINNET_TARGET_PHOTO4G_P98)
        else if(q->length==4u&&get32(q->payload)==9u){
            words[0]=0x5044434cu;words[1]=0;
            words[2]=*(volatile uint32_t *)(uintptr_t)0x6000d030u;
            words[3]=ln_lcd_panel_type();
            count=4u;
        }
#endif
#endif
        else if(q->length==4u&&get32(q->payload)==5u){ln_storage_schedule_performance(words);count=24u;}
        else if(q->length==4u&&get32(q->payload)==6u){ln_ata_clock_diagnostics(words);count=8u;}
#endif
        else return 1;
        for(uint32_t i=0;i<count;++i)put32(ln_storage_reply+i*4,words[i]);r->length=(uint16_t)(count*4u);break;}
    case 95:{
        if(q->length)return 1;struct ln_ata_info a;struct ln_block_info b;
        ln_ata_snapshot(&a);ln_block_snapshot(&b);
        for(uint32_t i=0;i<192u;++i)ln_storage_reply[i]=0;
        uint32_t state=(!a.powered?0u:a.sleeping?2u:1u);
        if(a.initializing||b.power_transition)state=3u;
        uint32_t words[16]={0x4944454du,0,(uint32_t)a.sectors,(uint32_t)(a.sectors>>32),
            a.media_kind,a.rotation_rpm,a.logical_sector_bytes,a.physical_sector_bytes,
            a.capabilities,a.quirks,state,a.idle_timeout_us,a.wake_timeout_us,a.poweroffs,a.spinups,b.idle_failures};
        for(uint32_t i=0;i<16u;++i)put32(ln_storage_reply+i*4,words[i]);
        for(uint32_t i=0;i<40u;++i)ln_storage_reply[64+i]=(uint8_t)a.model[i];
        for(uint32_t i=0;i<20u;++i)ln_storage_reply[104+i]=(uint8_t)a.serial[i];
        for(uint32_t i=0;i<8u;++i)ln_storage_reply[124+i]=(uint8_t)a.firmware[i];
        r->length=192;break;}
    case 81:case 97:{
        if(q->length!=8)return 1;uint32_t offset=get32(q->payload),n=get32(q->payload+4);
        if(!n||n>1008||!ln_storage_read(q->command==81?LN_STORAGE_SCRATCH:LN_STORAGE_WORK,offset,ln_storage_reply+4,n))return 1;
        put32(ln_storage_reply,offset);r->length=4+n;break;}
    case 82:case 98:{
        if(q->length<=8||q->length>1016||get32(q->payload)!=generation)return 1;
        uint32_t offset=get32(q->payload+4),n=q->length-8;
        if(offset>UINT32_MAX-n||!ln_storage_write(q->command==82?LN_STORAGE_SCRATCH:LN_STORAGE_WORK,offset,q->payload+8,n)||!ln_storage_flush())return 1;
        put32(ln_storage_reply+4,offset+n);break;}
    case 83:{
        if(q->length)return 1;uint32_t n=480;
        if(!ln_storage_settings(false,ln_storage_reply+4,&n)||n>480)return 1;
        r->length=4+n;break;}
    case 84:{
        if(q->length<4||q->length>484||get32(q->payload)!=generation)return 1;
        uint32_t n=q->length-4;
        for(uint32_t i=0;i<n;++i)ln_storage_reply[4+i]=q->payload[4+i];
        if(!ln_storage_settings(true,ln_storage_reply+4,&n))return 1;
        put32(ln_storage_reply+4,n);break;}
    case 85:{
        if(q->length!=40||get32(q->payload)!=generation)return 1;
        if(!ln_storage_update(1,q->payload+8,get32(q->payload+4),0))return 1;
        break;}
    case 86:{
        if(q->length<=8||q->length>1016||get32(q->payload)!=generation)return 1;
        uint32_t offset=get32(q->payload+4),n=q->length-8;
        if(offset>UINT32_MAX-n||!ln_storage_update(2,q->payload+8,n,offset))return 1;
        put32(ln_storage_reply+4,offset+n);break;}
    case 87:
        if(q->length!=4||get32(q->payload)!=generation||!ln_storage_update(3,0,0,0))return 1;
        break;
    case 88:{
        if(q->length)return 1;uint32_t words[16];ln_storage_update_state(words);
        for(unsigned i=0;i<16;++i)put32(ln_storage_reply+i*4,words[i]);r->length=64;break;}
    case 89:{
        if(q->length!=8||get32(q->payload)!=generation)return 1;
        uint32_t mode=get32(q->payload+4);if(mode<1||mode>5||!ln_block_inject(mode))return 1;
        put32(ln_storage_reply+4,mode);break;}
    case 91:
        if(q->length!=4||get32(q->payload)!=generation||!ln_storage_recover())return 1;
        break;
    case 92:
        if(q->length!=4||get32(q->payload)!=generation||ln_storage_restart_pending||ln_storage_busy()||!ln_storage_prepared())return 1;
        ln_storage_restart_pending=1;break;
    case 93:{
        if(q->length!=8||get32(q->payload)!=generation)return 1;
        uint32_t stage=get32(q->payload+4);if(stage<1||stage>4||!ln_storage_publication_fault(stage))return 1;
        put32(ln_storage_reply+4,stage);break;}
    case 96:{
        if(q->length!=12||get32(q->payload)!=generation)return 1;
        uint32_t action=get32(q->payload+4),size=get32(q->payload+8);
        if(action<1||action>2||!size||size>0x100000u||!ln_storage_file_resize(action,size))return 1;
        put32(ln_storage_reply+4,size);break;}
    default:return 1;
    }
    r->flags=1;return 1;
}
void ln_storage_link_ack_sent(uint16_t command){
    if(command!=92||!ln_storage_restart_pending)return;
    ln_storage_restart_pending=0;(void)ln_storage_restart();ln_panic(35,0,0);
}
