#include "kernel/audio_link.h"
#include "hal/pp5020/audio.h"
#include "hal/pp5020/core.h"
#include "hal/pp5020/recovery.h"
#include "services/storage/storage.h"
#include "services/music/player.h"
#include "services/music/library.h"
#include "services/music/controller.h"
#if defined(LINNET_PHOTOS)
#include "services/photos/photos.h"
#endif
#if defined(LINNET_VIDEO)
#include "services/video/video.h"
#endif
static uint8_t reply[128];
static int16_t pcm[508];
static uint32_t read32(const uint8_t*p){return(uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void write32(uint8_t*p,uint32_t v){for(uint32_t b=0;b<4;++b)p[b]=(uint8_t)(v>>(b*8));}
int ln_audio_link_dispatch(const ln_link_frame *q,ln_link_frame *r){
    if(q->command<112||q->command>123)return 0;
#if !defined(LINNET_PHOTOS)
    if(q->command==121)return 0;
#endif
#if !defined(LINNET_VIDEO)
    if(q->command==122||q->command==123)return 0;
#endif
    if(q->flags||!q->sequence||q->length>1024||(q->length&&!q->payload))return 0;
    uint32_t generation=ln_recovery_generation();
    r->command=q->command;r->sequence=q->sequence;r->flags=LINNET_LINK_ACK|LINNET_LINK_ERROR;
    r->payload=reply;r->length=8;write32(reply,generation);write32(reply+4,0);
#if defined(LINNET_VIDEO)
    if((ln_video_active()||ln_video_pending())&&q->command>=113&&q->command<=118&&q->command!=116)return 1;
#endif
    struct ln_audio_status a;ln_audio_snapshot(&a);
    if(q->command==123){
#if defined(LINNET_VIDEO) && !defined(LINNET_PROFILE_RELEASE)
        if(q->length!=8||read32(q->payload)!=generation||
           !ln_video_measurement_arm(read32(q->payload+4)))return 1;
        write32(reply+4,read32(q->payload+4));
#else
        return 0;
#endif
    }else if(q->command==122){
#if defined(LINNET_VIDEO)
#if !defined(LINNET_PROFILE_RELEASE)
        if(q->length==4u&&read32(q->payload)<8u){
            ln_video_metadata(read32(q->payload),reply);r->length=128;r->flags=LINNET_LINK_ACK;return 1;
        }
#endif
        if(q->length)return 1;uint32_t words[32];ln_video_diagnostics(words);
        for(uint32_t n=0;n<32;++n)write32(reply+n*4,words[n]);r->length=128;
#endif
    }else if(q->command==121){
#if defined(LINNET_PHOTOS)
        if(q->length)return 1;uint32_t words[32];ln_photos_diagnostics(words);
        for(uint32_t n=0;n<32;++n)write32(reply+n*4,words[n]);r->length=128;
#endif
    }else if(q->command==120){
        if(q->length)return 1;struct ln_player_timing t;ln_player_timing_snapshot(&t);
        struct ln_core_status c;ln_core_snapshot(&c);
        uint32_t words[20]={0x34544d50u,4,t.decode_calls,t.decode_us,t.decode_max_us,t.dsp_calls,t.dsp_frames,t.dsp_us,t.dsp_max_us,t.runtime_calls,t.runtime_us,t.runtime_max_us,t.music_us,t.storage_us,t.link_us,
            c.clock_hz,c.cache_control,*(volatile uint32_t *)(uintptr_t)0x60006044u,c.idle_us,c.clock_source};
        for(uint32_t n=0;n<20;n++)write32(reply+n*4,words[n]);r->length=80;
    }else if(q->command==119){
        if(q->length)return 1;
        uint32_t words[8]={0x3442494cu,1,ln_music_library_status(),(uint32_t)ln_music_library_error(),
            ln_music_library_count(),ln_music_library_group_count(),ln_music_library_verified_bytes(),ln_music_library_revision()};
        for(uint32_t i=0;i<8;++i)write32(reply+i*4,words[i]);
        for(uint32_t i=32;i<64;++i)reply[i]=0;
        (void)ln_music_library_identity(reply+32);r->length=64;
    }else if(q->command==116){
        if(q->length)return 1;struct ln_player_status p;ln_player_snapshot(&p);
        uint64_t position=ln_player_position();
        uint32_t words[16]={0x34524c50u,p.phase,p.error,p.generation,p.rate,p.decoded,p.rendered,p.underruns,(uint32_t)p.frames,(uint32_t)(p.frames>>32),
            p.next_phase,p.next_error,p.gapless_joins,p.missed_joins,(uint32_t)position,(uint32_t)(position>>32)};
        for(uint32_t i=0;i<16;++i)write32(reply+i*4,words[i]);r->length=64;
    }else if(q->command==117){
        if(q->length<6||q->length>260||read32(q->payload)!=generation||q->payload[q->length-1]||a.initialized)return 1;
        if(!ln_player_open((const char*)q->payload+4))return 1;
    }else if(q->command==118){
        if((q->length!=8&&q->length!=16)||read32(q->payload)!=generation)return 1;
        uint32_t action=read32(q->payload+4);
        if((action==4)!=(q->length==16))return 1;
        if(action==1){if(!ln_player_pause(true))return 1;}
        else if(action==2){if(!ln_player_pause(false))return 1;}
        else if(action==3)ln_music_stop();
        else if(action==4){uint64_t frame=(uint64_t)read32(q->payload+8)|((uint64_t)read32(q->payload+12)<<32);
            if(!ln_music_seek(frame))return 1;}else return 1;
        write32(reply+4,action);
    }else if(q->command==112){
        if(q->length)return 1;
        uint32_t words[20]={0x34445541u,2,a.rate,a.queued,a.free_frames,a.consumed,a.submitted,
            a.interrupts,a.underruns,a.silence_frames,a.fault,a.playing,a.paused,a.initialized,
            a.last_irq_us,a.max_irq_us,(uint32_t)a.volume_db_tenths,
            a.fifo_empty_irqs,a.max_completion_interval_us,a.max_completion_late_us};
        for(uint32_t i=0;i<20;++i)write32(reply+i*4,words[i]);r->length=80;
    }else{
        if(q->length<8||read32(q->payload)!=generation||ln_storage_busy()||ln_player_busy())return 1;
        uint32_t value=read32(q->payload+4);
        if(q->command==113){
            if(q->length!=8||a.initialized||!ln_audio_init(value))return 1;
            write32(reply+4,value);
        }else if(q->command==114){
            if(q->length<12||(q->length-8u)%4u||value!=a.submitted)return 1;
            uint32_t frames=(q->length-8u)/4u;if(frames>a.free_frames)return 1;
            for(uint32_t i=0;i<frames*2u;++i)pcm[i]=(int16_t)((uint16_t)q->payload[8+i*2]|(uint16_t)q->payload[9+i*2]<<8);
            if(ln_audio_submit(pcm,frames)!=frames)return 1;write32(reply+4,value+frames);
        }else{
            if(q->length!=12)return 1;uint32_t arg=read32(q->payload+8);
            if(value==1){if(arg||!ln_audio_start())return 1;}
            else if(value==2){if(arg)return 1;ln_audio_pause();}
            else if(value==3){if(arg||!ln_audio_stop())return 1;}
            else if(value==4){if(!a.initialized||!ln_audio_volume((int32_t)arg))return 1;}
            else if(value==5){if(arg||!a.initialized)return 1;ln_audio_finish();}
            else return 1;write32(reply+4,value);
        }
    }
    r->flags=LINNET_LINK_ACK;return 1;
}
