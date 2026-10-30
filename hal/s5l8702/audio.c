#include "hal/api/audio.h"
#include "hal/api/click_pcm.h"
#include "hal/api/core.h"
#include "hal/codecs/codec.h"
#include "hal/arm926/cache.h"
#include "board.h"
#include "irq.h"
#include "pcm_dma.h"
#if !defined(LINNET_PROFILE_RELEASE)
#include "i2c.h"
#include "registers.h"
#endif
extern void ln_memory_copy(void *,const void *,uint32_t);
extern uint32_t ln_time_us(void);
#ifdef LINNET_SRAM_MONITOR
#define AUDIO_MEMORY __attribute__((section(".dram.audio"),aligned(32)))
#else
/* DMA sees only submitted, cache-cleaned PCM; ring contents need no reset. */
#define AUDIO_MEMORY __attribute__((section(".media_workspace"),aligned(32)))
#endif
#define BLOCK 1024u
#define MASK (LINNET_AUDIO_RING_FRAMES-1u)
static uint32_t ring[LINNET_AUDIO_RING_FRAMES] AUDIO_MEMORY;
static uint32_t click_pcm[BLOCK] AUDIO_MEMORY;
static volatile struct ln_pcm_click click;
static bool click_owned;
static volatile bool click_block,click_draining;
static uint32_t click_last;
static volatile uint32_t click_drain_until;
static void copy_frames(uint32_t offset,const int16_t *samples,uint32_t frames) {
    if(frames>=8u && !((uintptr_t)samples&3u))ln_memory_copy(ring+offset,samples,frames*4u);
    else for(uint32_t i=0;i<frames;i++)ring[offset+i]=(uint16_t)samples[i*2u]|
        ((uint32_t)(uint16_t)samples[i*2u+1u]<<16);
}
#ifdef LINNET_SRAM_MONITOR
/* The monitor clears BSS on entry; keep this zeroed DMA buffer out of NOR. */
static uint32_t silence[BLOCK] AUDIO_MEMORY;
#else
static const uint32_t silence[BLOCK] __attribute__((aligned(32)))={0};
#endif
static volatile struct ln_audio_status status;
static volatile uint32_t head,tail,inflight,armed,expected,previous,drain_until;
static volatile bool active,real,finishing,pause_pending,draining,starved;
static bool owned,codec_ready,lineout,muted,amplifier_open;
static uint32_t frame_q12;
static uint32_t frame_period(uint32_t rate) {
    switch(rate) {
    case 8000:return 4096000000u/8000;case 11025:return 4096000000u/11025;
    case 12000:return 4096000000u/12000;case 16000:return 4096000000u/16000;
    case 22050:return 4096000000u/22050;case 24000:return 4096000000u/24000;
    case 32000:return 4096000000u/32000;case 44100:return 4096000000u/44100;
    case 48000:return 4096000000u/48000;default:return 0;
    }
}
static void fault(uint32_t reason) {
    if(!status.fault)status.fault=reason;
    ln_s5l_irq_enable(16,false);status.playing=0;
}
static bool arm(bool continuing) {
    uint32_t queued=head-tail,count=status.playing?queued:0,offset=tail&MASK;
    if(queued>LINNET_AUDIO_RING_FRAMES){fault(1);return false;}
    click_block=!status.playing;
    real=count!=0;
    if(count) {
        if(count>BLOCK)count=BLOCK;
        if(count>LINNET_AUDIO_RING_FRAMES-offset)count=LINNET_AUDIO_RING_FRAMES-offset;
        starved=false;
    } else {
        count=click_block?click.left:BLOCK;
        if(!click_block){if(!starved)status.underruns++;starved=true;}
    }
    if(!count)return false;
    const int16_t *samples=(const int16_t *)(real?ring+offset:silence);
    if(ln_pcm_click_mix(&click,click_pcm,(const uint32_t *)samples,count))samples=(const int16_t *)click_pcm;
    bool ok=continuing?ln_s5l_pcm_rearm(samples,count):ln_s5l_pcm_begin(samples,count);
    if(!ok){fault(2);return false;}
    inflight=count;active=true;armed=ln_time_us();expected=(count*frame_q12+4095u)>>12;
    ln_s5l_pcm_interrupt(true);ln_s5l_irq_enable(16,true);return true;
}
bool ln_audio_volume(int32_t value) {
    if(value<-1020 || value>0 || !codec_ready || !ln_codec_volume(ln_s5l_board_codec_write,value))return false;
    status.volume_db_tenths=value;return true;
}
bool ln_audio_lineout(bool enabled) {
    if(codec_ready && !ln_codec_lineout(ln_s5l_board_codec_write,enabled))return false;
    lineout=enabled;return true;
}
bool ln_audio_halt(void) {
    ln_audio_click_stop();click_draining=false;
    if(!owned)return true;
    bool ok=true;
    if(codec_ready&&!muted&&!status.playing){
        muted=ln_codec_digital_mute(ln_s5l_board_codec_write,true);
        if(!muted||!ln_core_delay_us(10000u))return false;
    }
    if(status.playing && !status.fault) {
        /* A manual track change must drain through silence like Pause.
         * Aborting a live I2S FIFO makes an audible output transient. */
        ln_audio_pause();
        uint32_t began=ln_time_us();
        uint32_t block_us=(BLOCK*frame_q12+4095u)>>12;
        uint32_t timeout=2u*block_us+20000u;
        while(status.playing && !status.fault && ln_time_us()-began<timeout) {
            uint32_t now=ln_time_us();ln_audio_service(now);
            if(status.playing)ln_core_idle_until(now+1000u);
        }
        if(status.playing || status.fault)ok=false;
    }
    uint32_t flags=ln_s5l_irq_save();ln_s5l_irq_enable(16,false);
    bool stopped=ln_s5l_pcm_stop();
    if(stopped){active=draining=pause_pending=false;head=tail=inflight=0;status.initialized=status.playing=status.paused=0;}
    else fault(3);
    ln_s5l_irq_restore(flags);return ok && stopped;
}
bool ln_audio_stop(void) {
    click_owned=false;
    if(!owned)return true;
    if(!ln_audio_halt())return false;
    bool ok;
#if defined(LINNET_IMAGE_OS) && LINNET_AUDIO_CLOCK_GATING
    /* Even a partially initialized codec must acknowledge power-down before
     * its MCLK can stop. A failed stop preserves ownership for recovery. */
    ok=ln_codec_off(ln_s5l_board_codec_write);
    if(!ok||!ln_s5l_board_audio_clock_off())return false;
#else
    ok=!codec_ready || ln_codec_off(ln_s5l_board_codec_write);
#endif
    codec_ready=owned=amplifier_open=false;return ok;
}
bool ln_audio_init(uint32_t rate) {
    click_owned=false;
    uint32_t period=frame_period(rate),codec_rate;
    if(!period || !ln_codec_rate_supported(rate))return false;
    bool warm=owned && codec_ready && !status.fault;
    uint32_t old_rate=status.rate;
    int32_t volume=warm?status.volume_db_tenths:-400;
    if(!ln_audio_halt())return false;
    status=(struct ln_audio_status){0};head=tail=inflight=0;active=draining=finishing=pause_pending=starved=false;
    owned=true;previous=0;frame_q12=period;
    if(!warm) {
        codec_ready=false;
        if(!ln_s5l_board_audio_power(true) || !ln_core_delay_us(1000) ||
           !ln_s5l_board_audio_power(false) || !ln_core_delay_us(1000))goto failed;
    }
    if(!warm || old_rate!=rate) {
        if(!ln_s5l_board_audio_clock(rate,&codec_rate))goto failed;
        if(warm) {if(!ln_codec_rate(ln_s5l_board_codec_write,codec_rate))goto failed;}
        else if(!ln_codec_init(ln_s5l_board_codec_write,codec_rate))goto failed;
    }
    codec_ready=true;muted=true;if(!warm)amplifier_open=false;
    if(warm)status.volume_db_tenths=volume;
    else if(!ln_audio_volume(volume) || !ln_codec_lineout(ln_s5l_board_codec_write,lineout))goto failed;
    status.rate=rate;status.initialized=1;return true;
failed:
    (void)ln_s5l_pcm_stop();(void)ln_codec_mute(ln_s5l_board_codec_write,true);
#if defined(LINNET_IMAGE_OS) && LINNET_AUDIO_CLOCK_GATING
    if(ln_codec_off(ln_s5l_board_codec_write))(void)ln_s5l_board_audio_clock_off();
#endif
    codec_ready=amplifier_open=false;status.fault=4;return false;
}
void ln_audio_click_stop(void){
    uint32_t flags=ln_s5l_irq_save();ln_pcm_click_clear(&click);ln_s5l_irq_restore(flags);
}
void ln_audio_click(uint8_t tone,uint8_t volume,int32_t output_db_tenths){
    if(tone>3u||tone==1u||!volume||volume>4u)return;
    if(!status.initialized){
        if(!ln_audio_init(44100u))return;
        click_owned=true;
        if(!ln_audio_volume(output_db_tenths)){(void)ln_audio_stop();return;}
    }
    if(status.fault)return;
    uint32_t flags=ln_s5l_irq_save();
    ln_pcm_click_request(&click,status.rate,tone,volume);click_last=ln_time_us();
    ln_s5l_irq_restore(flags);
    ln_audio_service(ln_time_us());
}
uint32_t ln_audio_capacity(void) {
    uint32_t queued=head-tail;
    return status.initialized && !status.fault && queued<=LINNET_AUDIO_RING_FRAMES?
        LINNET_AUDIO_RING_FRAMES-queued:0;
}
uint32_t ln_audio_submit(const int16_t *samples,uint32_t frames) {
    if(!samples || finishing)return 0;
    uint32_t room=ln_audio_capacity();if(frames>room)frames=room;
    uint32_t cursor=head,offset=cursor&MASK,first=frames;
    if(first>LINNET_AUDIO_RING_FRAMES-offset)first=LINNET_AUDIO_RING_FRAMES-offset;
    copy_frames(offset,samples,first);
    if(frames>first)copy_frames(0,samples+first*2u,frames-first);
    ln_arm926_data_clean_range(ring+offset,first*4u);
    if(frames>first)ln_arm926_data_clean_range(ring,(frames-first)*4u);
    __asm__ volatile("":::"memory");head=cursor+frames;status.submitted+=frames;return frames;
}
bool ln_audio_rewrite(uint32_t frame,const int16_t *samples,uint32_t frames) {
    /* Effect rewrites are bounded foreground work between completion IRQs. */
    if(!samples || frames>2048u)return false;
    uint32_t flags=ln_s5l_irq_save(),offset=frame-tail,queued=head-tail;
    bool ok=status.initialized && !status.fault && offset<=queued && frames<=queued-offset &&
        (!active || !real || offset>=inflight);
    if(ok) {
        uint32_t start=frame&MASK,first=frames;
        if(first>LINNET_AUDIO_RING_FRAMES-start)first=LINNET_AUDIO_RING_FRAMES-start;
        copy_frames(start,samples,first);
        if(frames>first)copy_frames(0,samples+first*2u,frames-first);
        ln_arm926_data_clean_range(ring+start,first*4u);
        if(frames>first)ln_arm926_data_clean_range(ring,(frames-first)*4u);
    }
    ln_s5l_irq_restore(flags);return ok;
}
bool ln_audio_start(void) {
    if(!status.initialized || status.fault || head==tail)return false;
    uint32_t flags=ln_s5l_irq_save();pause_pending=draining=click_draining=false;status.paused=0;status.playing=1;
    if(!active)previous=0;
    bool ok=active || arm(false);ln_s5l_irq_restore(flags);
    if(ok)ok=amplifier_open?ln_codec_digital_mute(ln_s5l_board_codec_write,false):
        ln_codec_mute(ln_s5l_board_codec_write,false);
    click_owned=false;
    if(!ok){fault(4);return false;}muted=false;amplifier_open=true;return true;
}
void ln_audio_pause(void) {
    if(!status.playing || pause_pending)return;
    /* Keep LRCK running while the digital soft ramp settles. The headphone
     * amplifier stays on across routine pause/resume transitions. */
    if(!ln_codec_digital_mute(ln_s5l_board_codec_write,true)){fault(4);return;}
    muted=true;
    uint32_t flags=ln_s5l_irq_save();if(status.playing)pause_pending=true;ln_s5l_irq_restore(flags);
}
void ln_audio_finish(void) {
    uint32_t flags=ln_s5l_irq_save();finishing=true;ln_s5l_irq_restore(flags);
}
void ln_audio_irq(void) {
    uint32_t started=ln_time_us(),words[5];ln_s5l_pcm_status(words);
    if(!active || words[1] || !words[0]){fault(5);return;}
    ln_s5l_irq_enable(16,false);status.interrupts++;
    uint32_t interval=started-previous;
    if(previous && interval>status.max_completion_interval_us)status.max_completion_interval_us=interval;
    previous=started;
    uint32_t elapsed=started-armed;
    if(elapsed>expected && elapsed-expected>status.max_completion_late_us)status.max_completion_late_us=elapsed-expected;
    if(real){tail+=inflight;status.consumed+=inflight;}else if(!click_block)status.silence_frames+=inflight;
    active=false;inflight=0;status.last_irq_us=started;
    if(click_block&&!status.playing){
        click_draining=true;click_drain_until=started+10000u;ln_s5l_pcm_interrupt(false);
    } else if(pause_pending) {
        pause_pending=false;draining=true;drain_until=0;
        if(!ln_s5l_pcm_rearm((const int16_t *)silence,BLOCK)){fault(2);return;}
        real=false;inflight=BLOCK;active=true;armed=ln_time_us();
        expected=(BLOCK*frame_q12+4095u)>>12;
        ln_s5l_pcm_interrupt(true);ln_s5l_irq_enable(16,true);
    } else if(draining || (finishing && head==tail)) {
        draining=true;drain_until=started+10000u;
        ln_s5l_pcm_interrupt(false);
    } else if(status.playing)(void)arm(true);
    elapsed=ln_time_us()-started;if(elapsed>status.max_irq_us)status.max_irq_us=elapsed;
}
void ln_audio_service(uint32_t now) {
    uint32_t flags=ln_s5l_irq_save();
    /* Completion may arm a new block after the executive sampled now. */
    if(active && (int32_t)(now-armed)>250000)fault(6);
    /* The final IRQ leaves DMA inactive. A wrapped deadline may be zero. */
    if(draining && !active && (int32_t)(now-drain_until)>=0) {
        draining=false;status.playing=0;status.paused=1;
        if(!ln_s5l_pcm_stop())fault(3);
    }
    bool start_click=status.initialized&&!status.fault&&!status.playing&&!active&&!draining&&click.left;
    if(start_click){click_draining=false;start_click=arm(false);}
    if(click_draining&&!active&&!click.left&&(int32_t)(now-click_drain_until)>=0){
        click_draining=click_block=false;if(!ln_s5l_pcm_stop())fault(3);
    }
    bool needs_mute=codec_ready && !muted && ((!status.playing&&!active&&!click_draining) || status.fault);
    ln_s5l_irq_restore(flags);
    if(start_click){
        bool ok=amplifier_open?ln_codec_digital_mute(ln_s5l_board_codec_write,false):ln_codec_mute(ln_s5l_board_codec_write,false);
        if(!ok)fault(4);else {muted=false;amplifier_open=true;}
    }
    if(needs_mute){muted=ln_codec_digital_mute(ln_s5l_board_codec_write,true);if(!muted)fault(4);}
    if(status.fault && active){(void)ln_s5l_pcm_stop();active=false;}
    if(click_owned&&(status.fault||(!active&&!click_draining&&!click.left&&(int32_t)(now-click_last)>=500000)))(void)ln_audio_stop();
}
uint32_t ln_audio_deadline(uint32_t now){
    if(status.fault)return UINT32_MAX;
    if(click_draining)return click_drain_until;
    if(click_owned)return (int32_t)(now-(click_last+500000u))>=0?now:click_last+500000u;
    return UINT32_MAX;
}
void ln_audio_snapshot(struct ln_audio_status *out) {
    if(!out)return;
    uint32_t flags=ln_s5l_irq_save();*out=status;out->queued=head-tail;out->free_frames=ln_audio_capacity();
    if(active&&real){
        uint32_t dma[5];ln_s5l_pcm_status(dma);
        uint32_t remaining=(dma[2]+1u)/2u;
        if(remaining<=inflight)out->inflight_consumed=inflight-remaining;
    }
    ln_s5l_irq_restore(flags);
}
#if !defined(LINNET_PROFILE_RELEASE) && defined(LINNET_IMAGE_OS)
void ln_s5l_audio_diagnostics(uint32_t out[16]) {
    uint8_t registers[32]={0};
    for(unsigned n=0;n<16u;++n)out[n]=0;
    out[0]=0x43445541u; /* AUDC: read-only codec registers 01h..20h. */
    /* MAP bit 7 enables CS42L55 address auto-increment. One transaction has
     * the existing I2C driver's 20 ms deadline; no IRQ masking or writes. */
    if(codec_ready && ln_s5l_i2c_read(0,0x4a,0x81,registers,sizeof(registers))) {
        out[1]=1;
        for(unsigned n=0;n<32u;++n)out[2u+n/4u]|=(uint32_t)registers[n]<<((n%4u)*8u);
    }
    if(!(LN_CLOCK_GATE1&(1u<<7))){
        out[10]=LN_REG(0x3ca00000u);out[11]=LN_REG(0x3ca00004u);
        out[12]=LN_REG(0x3ca00008u);out[13]=LN_REG(0x3ca00040u);
    }
    out[14]=LN_REG(0x3c50000cu);out[15]=codec_ready;
}
#endif
