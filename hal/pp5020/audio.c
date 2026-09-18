/* Linnet PP5020 playback sink. Register protocol cross-checked against local
 * Rockbox firmware/target/arm/pp/{pcm-pp,i2s-pp}.c and drivers/audio/wm8975.c,
 * wmcodec-pp.c and export/pp5020.h. Independent implementation.
 * DMA owns only channel 0 and ordinary IRQ 26; recovery retains all FIQ state. */
#include "hal/api/audio.h"
#include "hal/api/core.h"
#include "hal/api/platform.h"
#include "hal/api/power.h"
#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define IRQ (1u<<26)
#define CMD REG(0x6000b000u)
#define STATUS REG(0x6000b004u)
#define REQUEST REG(0x6000a008u)
#define IIS REG(0x70002800u)
#define FIFO REG(0x7000280cu)
#define CHUNK 1024u
#define MASK (LINNET_AUDIO_RING_FRAMES-1u)
static uint32_t ring[LINNET_AUDIO_RING_FRAMES] __attribute__((aligned(32)));
static uint32_t silence[CHUNK] __attribute__((aligned(32)));
static volatile struct ln_audio_status state;
static volatile uint32_t head,tail,inflight;
static volatile bool real_block,active,pause_pending,owned,starved;
static volatile bool finishing;
static bool codec_ready,halted,dma_quiet;
static uint32_t frame_us_q12;
static volatile uint32_t armed_us, expected_us, previous_completion_us;
static volatile bool completion_seen;
static volatile uint32_t *native(uint32_t *p)
{ return (volatile uint32_t *)((uintptr_t)p|0x10000000u); }
static bool codec(uint8_t reg,uint16_t value)
{ return ln_power_i2c_write(0x1au,(uint8_t)((reg<<1)|(value>>8)),(uint8_t)value); }
static void mask_irq(void) { REG(0x60004028u)=IRQ; }
static void fault(uint32_t code)
{
    if(!state.fault)state.fault=code;
    state.playing=0; mask_irq();
    CMD&=~0xc0000000u;
}
static bool quiesce(void)
{
    dma_quiet=false;
    mask_irq(); REQUEST&=~4u; CMD&=~0xc0000000u;
    uint32_t started=ln_time_us();
    for(uint32_t budget=0;budget<1000000u;++budget){
        if(!(STATUS&0xc0000000u)){active=false;inflight=0;dma_quiet=true;return true;}
        if(ln_time_us()-started>=100000u)break;
    }
    fault(1);return false;
}
static void arm(void)
{
    uint32_t queued=head-tail,count=queued;
    if(queued>LINNET_AUDIO_RING_FRAMES){fault(2);return;}
    if(count>CHUNK)count=CHUNK;
    uint32_t offset=tail&MASK;
    if(count>LINNET_AUDIO_RING_FRAMES-offset)count=LINNET_AUDIO_RING_FRAMES-offset;
    volatile uint32_t *source;
    if(count){source=native(ring)+offset;real_block=true;starved=false;}
    else {source=native(silence);count=CHUNK;real_block=false;
        if(!starved)++state.underruns;starved=true;}
    inflight=count;active=true;dma_quiet=false;
    state.last_irq_us=ln_time_us();
    armed_us=state.last_irq_us;
    /* Rates are >=8kHz and count<=1024: both products fit uint32_t.
     * Q12 truncation contributes less than 0.25us per full chunk. */
    expected_us=(count*frame_us_q12+4095u)>>12;
    __asm__ volatile("":::"memory");
    REG(0x6000b010u)=(uint32_t)(uintptr_t)source;
    CMD=0xcd020000u|(count*4u-4u);
}
bool ln_audio_volume(int32_t value)
{
    if(value < -730 || value > 0)return false;
    /* Headphone step is 1 dB. Both channels latch on the right update bit. */
    uint16_t code=(uint16_t)(121+(value-9)/10);
    if(!codec(2,0x80u|code)||!codec(3,0x180u|code))return false;
    state.volume_db_tenths=value;return true;
}
bool ln_audio_halt(void)
{
    if(!owned)return true;
    if(halted)return true;
    bool muted=codec(5,8);
    /* Leave stream clocks running during this bounded mute-settle window.
     * This is a conservative delay, not a measured analog settling guarantee. */
    bool settled=muted&&ln_core_delay_us(10000);
    uint32_t flags=ln_core_irq_save();
    bool idle=quiesce();
    state.playing=0;state.paused=0;pause_pending=false;
    ln_core_irq_restore(flags);
    if(!idle)return false; /* Never reuse a DMA source until BUSY clears. */
    IIS&=~(1u<<29);FIFO|=1u<<8;
    state.initialized=0;head=tail=0;finishing=false;completion_seen=false;
    halted=muted&&settled;
    if(!halted){codec_ready=false;state.fault=3;}
    return halted;
}
bool ln_audio_stop(void)
{
    if(!owned)return true;
    bool muted=ln_audio_halt();
    if(!dma_quiet)return false;
    bool p2=codec(0x1a,0),p1=codec(0x19,0);
    REG(0x60006004u)|=0x800u;
    REG(0x6000600cu)&=~0x800u;
    state.initialized=0;owned=false;codec_ready=false;halted=false;head=tail=0;
    return muted&&p2&&p1;
}
bool ln_audio_init(uint32_t rate)
{
    uint16_t sample;
    switch(rate){case 44100:sample=0x63;break;case 48000:sample=0x41;break;
        case 22050:sample=0x77;break;case 32000:sample=0x59;break;
        /* The reference's unused12 kHz constant0x61 measures44.1 kHz on
         * this device. USB SR=01000 selects12 kHz;11001 selects11.025 kHz. */
        case 8000:sample=0x4d;break;case 12000:sample=0x51;break;
        case 11025:sample=0x73;break;
        case 16000:sample=0x55;break;case 24000:sample=0x79;break;
        case 88200:sample=0x7f;break;case 96000:sample=0x5d;break;default:return false;}
    bool warm=owned&&codec_ready&&!state.fault;
    int32_t volume=state.volume_db_tenths;
    if(warm){if(!ln_audio_halt())return false;}
    else if(!ln_audio_stop())return false;
    owned=true;
    if(!quiesce())return false;
    state=(struct ln_audio_status){0};head=tail=0;pause_pending=false;starved=false;finishing=false;
    frame_us_q12=4096000000u/rate;completion_seen=false;
    if(warm){
        /* Analog paths and headphone gain remain latched across tracks. */
        state.volume_db_tenths=volume;
        if(!codec(8,sample))goto failed;
        goto stream_ready;
    }
    REG(0x70000020u)&=~0x300u;REG(0x70000010u)&=~0x03000000u;
    REG(0x60006004u)|=0x800u;
    __asm__ volatile("nop\n\tnop\n\tnop":::"memory");
    REG(0x60006004u)&=~0x800u;REG(0x6000600cu)|=0x802u;
    REG(0x70000018u)&=~0xcu;
    IIS|=1u<<31;IIS&=~(1u<<31);
    IIS=(IIS&~((3u<<28)|(1u<<25)|3u|(3u<<10)|(3u<<8)|(7u<<4)))|(7u<<4);
    FIFO|=0x1131u;
    REG(0x6000d920u)=0x4040u;REG(0x6000d820u)=0x0404u;
    if(!codec(0xf,0)||!codec(5,8)||!ln_audio_volume(-400)||!codec(0x19,0x1c0))goto failed;
    if(!ln_core_delay_us(10000)||!ln_core_delay_us(10000))goto failed;
    if(!codec(0x19,0xc0)||!codec(0x1a,0x1e0)||!codec(7,0x42)||
       !codec(8,sample)||!codec(0x22,0x100)||!codec(0x23,0)||
       !codec(0x24,0)||!codec(0x25,0x100))goto failed;
    codec_ready=true;
stream_ready:
    for(uint32_t i=0;i<CHUNK;++i)native(silence)[i]=0;
    REG(0x6000a000u)|=1u<<31;
    REG(0x6000b018u)=0x70002840u;REG(0x6000b014u)=1u<<26;
    REG(0x6000b01cu)=0x20010000u;
    REG(0x6000402cu)&=~IRQ;
    state.rate=rate;state.initialized=1;halted=false;return true;
failed:
    (void)ln_audio_stop();state.fault=3;return false;
}
uint32_t ln_audio_capacity(void)
{
    uint32_t queued=head-tail;
    return state.initialized&&!state.fault&&queued<=LINNET_AUDIO_RING_FRAMES?
        LINNET_AUDIO_RING_FRAMES-queued:0;
}
uint32_t ln_audio_submit(const int16_t *pcm,uint32_t frames)
{
    if(!pcm||finishing)return 0;
    uint32_t free=ln_audio_capacity();if(frames>free)frames=free;
    uint32_t cursor=head,first=frames,offset=cursor&MASK;
    if(first>LINNET_AUDIO_RING_FRAMES-offset)first=LINNET_AUDIO_RING_FRAMES-offset;
    volatile uint32_t *out=native(ring)+offset;
    const int16_t *in=pcm,*end=pcm+first*2u;
    while(in!=end){uint32_t left=(uint16_t)*in++;*out++=left|((uint32_t)(uint16_t)*in++<<16);}
    out=native(ring);end=pcm+frames*2u;
    while(in!=end){uint32_t left=(uint16_t)*in++;*out++=left|((uint32_t)(uint16_t)*in++<<16);}
    __asm__ volatile("":::"memory");
    head=cursor+frames;state.submitted+=frames;return frames;
}
/* Replace only queued PCM beyond the DMA-owned block. The short copy is atomic
 * against completion; neither counters nor playback position are changed. */
bool ln_audio_rewrite(uint32_t frame,const int16_t *pcm,uint32_t frames){
    uint32_t flags=ln_core_irq_save(),offset=frame-tail,queued=head-tail;
    bool allowed=state.initialized&&!state.fault&&offset<=queued&&frames<=queued-offset&&
        (!active||!real_block||offset>=inflight);
    if(allowed)for(uint32_t i=0;i<frames;i++)native(ring)[(frame+i)&MASK]=
        (uint16_t)pcm[2*i]|((uint32_t)(uint16_t)pcm[2*i+1]<<16);
    ln_core_irq_restore(flags);return allowed;
}
bool ln_audio_start(void)
{
    if(!state.initialized||state.fault||head==tail)return false;
    uint32_t flags=ln_core_irq_save();
    pause_pending=false;state.paused=0;state.playing=1;
    REQUEST|=4u;IIS|=1u<<29;
    if(!active){completion_seen=false;arm();}
    REG(0x60004024u)=IRQ;
    ln_core_irq_restore(flags);
    if(state.fault)return false;
    if(!codec(5,0)){fault(3);return false;}
    return true;
}
void ln_audio_pause(void)
{
    uint32_t flags=ln_core_irq_save();
    if(state.playing){if(active)pause_pending=true;else{state.playing=0;state.paused=1;}}
    ln_core_irq_restore(flags);
}
void ln_audio_finish(void){uint32_t flags=ln_core_irq_save();finishing=true;ln_core_irq_restore(flags);}
void ln_audio_irq(void)
{
    uint32_t started=ln_time_us(),fifo=FIFO,status=STATUS;
    if(!state.initialized||!active||(status&0xc0000000u)!=0x40000000u){fault(4);return;}
    if(((fifo>>16)&0x3fu)>=16u)++state.fifo_empty_irqs;
    if(completion_seen){
        uint32_t interval=started-previous_completion_us;
        if(interval>state.max_completion_interval_us)state.max_completion_interval_us=interval;
    }
    previous_completion_us=started;completion_seen=true;
    uint32_t duration=started-armed_us;
    if(duration>expected_us&&duration-expected_us>state.max_completion_late_us)
        state.max_completion_late_us=duration-expected_us;
    ++state.interrupts;
    if(real_block){tail+=inflight;state.consumed+=inflight;}
    else state.silence_frames+=inflight;
    active=false;inflight=0;state.last_irq_us=started;
    if(pause_pending||(finishing&&tail==head)){pause_pending=false;state.playing=0;state.paused=1;}
    else if(state.playing)arm();
    uint32_t elapsed=ln_time_us()-started;if(elapsed>state.max_irq_us)state.max_irq_us=elapsed;
}
void ln_audio_service(uint32_t now)
{
    uint32_t flags=ln_core_irq_save();
    if(active&&(int32_t)(now-state.last_irq_us)>=250000)fault(5);
    ln_core_irq_restore(flags);
}
void ln_audio_snapshot(struct ln_audio_status *out)
{
    if(!out)return;
    uint32_t flags=ln_core_irq_save();*out=state;
    out->queued=head-tail;out->free_frames=ln_audio_capacity();ln_core_irq_restore(flags);
}
