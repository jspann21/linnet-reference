#include "hal/api/display.h"
#include "hal/pp5020/display_internal.h"
#include "hal/api/platform.h"
#include "hal/api/core.h"
#include "boot/include/linnet_boot.h"
#include "targets/ipod4g-q21/lcd.h"

#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define MB(o) REG(LINNET_DISPLAY_MAILBOX+(o))

static uint16_t frame[LINNET_DISPLAY_PIXELS] __attribute__((aligned(32)));
static bool initialized,dirty,pending,direct_frame,clock_park_owned,cop_capable;
static bool startup_rewake_armed,startup_rewake_done;
#define BLOCKS_PER_ROW (LINNET_LCD_WIDTH/8u)
#define ALL_BLOCKS ((1u<<BLOCKS_PER_ROW)-1u)
static uint32_t damage[LINNET_LCD_HEIGHT],active[LINNET_LCD_HEIGHT];
static uint16_t sent[LINNET_LCD_HEIGHT*BLOCKS_PER_ROW];
static bool force_full=true;
static uint32_t cursor,submitted,completed,failures,resets,generation;
static uint32_t last_write,written_blocks,started;
static void damage_all(void)
{
    for(uint32_t y=0;y<LINNET_LCD_HEIGHT;++y)damage[y]=ALL_BLOCKS;
    dirty=true;
}
static uint32_t cop_error,startup_rewake_at;
#if !defined(LINNET_PROFILE_RELEASE)
static uint32_t max_present_us;
#endif

static void barrier(void){__asm__ volatile("":::"memory");}

static bool cop_probe(void)
{
    if(REG(0x11ffe0a0u)!=LINNET_DISPLAY_CAPABILITY){cop_error=1;return false;}
    uint32_t nonce=MB(LN_DISPLAY_PROBE_ACK)+1u,start=ln_time_us();
    MB(LN_DISPLAY_PROBE)=nonce;
    for(uint32_t i=0;i<100000u;++i){
        if(MB(LN_DISPLAY_PROBE_ACK)==nonce)return true;
        if(ln_time_us()-start>=5000u)break;
    }
    cop_error=2;return false;
}

static bool pause_worker(bool pause)
{
    if(!cop_capable)return true;
    MB(LN_DISPLAY_PAUSE)=pause?1u:0u;barrier();
    uint32_t start=ln_time_us();
    for(uint32_t i=0;i<100000u;++i){
        if(MB(LN_DISPLAY_PAUSED)==(pause?1u:0u))return true;
        if(ln_time_us()-start>=5000u)break;
    }
    return false;
}

bool ln_core_cop_pause(bool pause)
{
    cop_error=0;
    if(!pause){
        if(!clock_park_owned)return true;
        MB(LN_DISPLAY_PAUSE)=0;REG(0x11ffe010u)=ln_time_us();barrier();
        REG(0x60007004u)=0;
        uint32_t start=ln_time_us();
        for(uint32_t i=0;i<100000u;++i){
            if(!MB(LN_DISPLAY_PAUSED)){clock_park_owned=false;return true;}
            if(ln_time_us()-start>=5000u)break;
        }
        cop_error=6;return false;
    }
    if(clock_park_owned){cop_error=3;return false;}
    if(REG(0x60007004u)&0x80000000u)return true;
    if(!cop_probe())return false;
    if(MB(LN_DISPLAY_ENABLED)!=1u){
        if(!pause_worker(true)){cop_error=4;return false;}
        MB(LN_DISPLAY_STATE)=0;MB(LN_DISPLAY_TAIL)=MB(LN_DISPLAY_HEAD);
    }
    MB(LN_DISPLAY_PAUSE)=2u;barrier();
    uint32_t start=ln_time_us();
    for(uint32_t i=0;i<100000u;++i){
        if(MB(LN_DISPLAY_PAUSED)==2u&&(REG(0x60007004u)&0x80000000u)){
            clock_park_owned=true;return true;
        }
        if(ln_time_us()-start>=5000u)break;
    }
    cop_error=5;return false;
}

static bool monitor_signature(uint32_t *branch)
{
    if(REG(0x11ffe0a0u)!=LINNET_DISPLAY_CAPABILITY||REG(0x11ffe018u)!=0x4c4e434fu)return false;
    if(REG(0x40001040u)!=0xe5923000u||REG(0x40001044u)!=0xe580301cu||
       REG(0x40001054u)!=0xe5904010u||REG(0x40001058u)!=0xe0434004u||
       REG(0x4000105cu)!=0xe59f504cu||REG(0x40001060u)!=0xe1540005u||
       REG(0x400010b0u)!=750000u||REG(0x400010b8u)!=1500000u)return false;
    *branch=REG(0x40001064u);
    return *branch==0x3afffff4u||*branch==0xbafffff4u;
}

bool ln_display_upgrade_monitor(void)
{
    uint32_t branch;
    if(!monitor_signature(&branch)){cop_error=8;return false;}
    if(branch==0xbafffff4u)return true;
    if(REG(0x60007004u)&0x80000000u){cop_error=8;return false;}
    if(!ln_core_cop_pause(true))return false;
    bool patched=false;
    if(MB(LN_DISPLAY_PAUSED)==2u&&(REG(0x60007004u)&0x80000000u)&&monitor_signature(&branch)){
        REG(0x40001064u)=(branch&0x0fffffffu)|0xb0000000u;barrier();
        patched=REG(0x40001064u)==0xbafffff4u;
    }
    bool resumed=ln_core_cop_pause(false);
    if(!patched)cop_error=9;
    return patched&&resumed;
}

uint32_t ln_display_cop_error(void){return cop_error;}
void ln_display_cop_diagnostics(uint32_t output[8])
{
    if(!output)return;
    output[0]=cop_error;output[1]=REG(0x11ffe0a0u);output[2]=REG(0x60007004u);
    output[3]=MB(LN_DISPLAY_ENABLED);output[4]=MB(LN_DISPLAY_STATE);
    output[5]=MB(LN_DISPLAY_PAUSE);output[6]=MB(LN_DISPLAY_PAUSED);output[7]=MB(LN_DISPLAY_PROBE_ACK);
}

static uint32_t luma(uint16_t color)
{
    /* Exact weighted RGB565 conversion, with constant component contributions. */
    static const uint16_t red[32]={0,633,1266,1900,2533,3166,3800,4433,5067,5700,6333,6967,7600,8234,8867,9500,10134,10767,11400,12034,12667,13301,13934,14567,15201,15834,16468,17101,17734,18368,19001,19635};
    static const uint16_t green[64]={0,607,1214,1821,2428,3035,3642,4250,4857,5464,6071,6678,7285,7892,8500,9107,9714,10321,10928,11535,12142,12750,13357,13964,14571,15178,15785,16392,17000,17607,18214,18821,19428,20035,20642,21250,21857,22464,23071,23678,24285,24892,25500,26107,26714,27321,27928,28535,29142,29750,30357,30964,31571,32178,32785,33392,34000,34607,35214,35821,36428,37035,37642,38250};
    static const uint16_t blue[32]={0,238,477,715,954,1192,1431,1669,1908,2146,2385,2624,2862,3101,3339,3578,3816,4055,4293,4532,4770,5009,5248,5486,5725,5963,6202,6440,6679,6917,7156,7395};
    return (red[(color>>11)&31u]+green[(color>>5)&63u]+blue[color&31u])>>8;
}

static uint8_t physical_gray(uint32_t px,uint32_t py)
{
    uint32_t level=(luma(frame[py*LINNET_UI_WIDTH+px])*3u+127u)/255u;
    return (uint8_t)(3u-level);
}

bool ln_display_init(void)
{
    initialized=false;cop_error=0;cop_capable=cop_probe();
    if(!pause_worker(true))return false;
    generation=MB(LN_DISPLAY_MAGIC)==LINNET_DISPLAY_MAGIC?MB(LN_DISPLAY_GENERATION)+1u:1u;
    MB(LN_DISPLAY_ENABLED)=0;
    for(uint32_t offset=0;offset<120u;offset+=4u)
        if(offset!=LN_DISPLAY_PAUSE&&offset!=LN_DISPLAY_PAUSED)MB(offset)=0;
    MB(LN_DISPLAY_GENERATION)=generation;MB(LN_DISPLAY_MAGIC)=LINNET_DISPLAY_MAGIC;
    for(uint32_t i=0;i<LINNET_DISPLAY_PIXELS;++i)frame[i]=0;
    force_full=true;damage_all();pending=direct_frame=false;startup_rewake_armed=startup_rewake_done=false;
    cursor=submitted=completed=failures=resets=startup_rewake_at=written_blocks=0;
    if(!ln_q21_lcd_init())return false;
    initialized=true;
    if(!pause_worker(false)){initialized=false;return false;}
    return true;
}

uint32_t ln_display_init_error(void){return initialized?0u:0x21000000u|cop_error;}
uint16_t *ln_display_framebuffer(void){return direct_frame?0:frame;}
uint16_t *ln_display_direct_framebuffer(void)
{
    if(!initialized||pending||direct_frame)return 0;
    direct_frame=true;damage_all();return frame;
}
bool ln_display_damage(int32_t x,int32_t y,int32_t width,int32_t height)
{
    if(!initialized||width<=0||height<=0||x>=(int32_t)LINNET_UI_WIDTH||y>=(int32_t)LINNET_UI_HEIGHT)return false;
    if(x<0){if(x<=-width)return false;width+=x;x=0;}
    if(y<0){if(y<=-height)return false;height+=y;y=0;}
    if(width>(int32_t)LINNET_UI_WIDTH-x)width=(int32_t)LINNET_UI_WIDTH-x;
    if(height>(int32_t)LINNET_UI_HEIGHT-y)height=(int32_t)LINNET_UI_HEIGHT-y;
    uint32_t first=(uint32_t)x/8u,end=((uint32_t)(x+width)+7u)/8u;
    uint32_t mask=((1u<<end)-1u)&~((1u<<first)-1u);
    for(uint32_t row=(uint32_t)y;row<(uint32_t)(y+height);++row)damage[row]|=mask;
    dirty=true;return true;
}
void ln_display_column_mode(bool enabled){(void)enabled;}
bool ln_display_upgrade_blit(void){return false;}

bool ln_display_present(void)
{
    if(!initialized||!dirty||pending)return false;
    for(uint32_t y=0;y<LINNET_LCD_HEIGHT;++y){active[y]=damage[y];damage[y]=0;}
    pending=true;dirty=false;direct_frame=false;cursor=0;last_write=UINT32_MAX;++submitted;
    started=ln_time_us();
    return true;
}

bool ln_display_service(uint32_t max_blocks)
{
    if(!initialized)return false;
    if(!pending){
        /* The HD66753 can acknowledge early OS writes while retaining the ROM
         * Apple frame on the glass.  Once the first complete Linnet frame has
         * settled, wake the controller once more and replay that framebuffer.
         * This is confined to the monochrome target and ordinary later frames
         * never pay the reset cost. */
        if(startup_rewake_armed&&(int32_t)(ln_time_us()-startup_rewake_at)>=0){
            startup_rewake_armed=false;startup_rewake_done=true;
            if(!ln_display_reset()||!ln_display_present()){++failures;return false;}
        }else return true;
    }
    if(ln_time_us()-started>=500000u)goto failed;
    uint32_t service_started=ln_time_us();
    if(max_blocks>256u)max_blocks=256u;
    const uint32_t blocks_per_row=LINNET_LCD_WIDTH/8u;
    const uint32_t total=blocks_per_row*LINNET_LCD_HEIGHT;
    while(max_blocks--&&cursor<total){
        uint32_t py=cursor/blocks_per_row,bx=cursor%blocks_per_row;
        if(ln_time_us()-service_started>=2000u)break;
        if(!(active[py]&(1u<<bx))){++cursor;continue;}
        uint8_t bytes[2]={0,0};
        for(uint32_t p=0;p<8u;++p){
            uint32_t px=bx*8u+p;
            bytes[p>>2]|=(uint8_t)(physical_gray(px,py)<<(6u-2u*(p&3u)));
        }
        uint16_t packed=(uint16_t)((uint16_t)bytes[0]<<8)|bytes[1];
        if(force_full||sent[cursor]!=packed){
            if((!bx||last_write==UINT32_MAX||last_write+1u!=cursor)&&
               !ln_q21_lcd_begin_span(py,bx))goto failed;
            if(!ln_q21_lcd_write(bytes[0],bytes[1]))goto failed;
            sent[cursor]=packed;last_write=cursor;++written_blocks;
        }
        ++cursor;
    }
    if(cursor==total){
        pending=false;force_full=false;++completed;
#if !defined(LINNET_PROFILE_RELEASE)
        uint32_t elapsed=ln_time_us()-started;
        if(elapsed>max_present_us)max_present_us=elapsed;
#endif
        if(!startup_rewake_done&&!startup_rewake_armed){
            startup_rewake_armed=true;startup_rewake_at=ln_time_us()+500000u;
        }
    }
    return true;
failed:
    pending=false;force_full=true;damage_all();++failures;return false;
}

void ln_display_sync_irq(void){}
bool ln_display_busy(void){return pending;}
bool ln_display_cop_capable(void){return false;}
bool ln_display_quiesce(void)
{
    if(!initialized)return true;
    pending=false;MB(LN_DISPLAY_ENABLED)=0;
    return pause_worker(true);
}
bool ln_display_reset(void)
{
    if(!initialized||!ln_display_quiesce())return false;
    if(!ln_q21_lcd_reinitialize())return false;
    ++resets;++generation;MB(LN_DISPLAY_GENERATION)=generation;force_full=true;damage_all();
    return pause_worker(false);
}
bool ln_display_diagnostic(uint32_t pattern)
{
    (void)pattern;
    /* A direct panel diagnostic has no queued completion record.  Admit it
     * only between ordinary frames so it cannot cancel a submitted frame or
     * leave presentation telemetry permanently out of balance. */
    if(!initialized||pending||dirty||direct_frame||!ln_display_quiesce())return false;
    bool ok=ln_q21_lcd_diagnostic();
    force_full=true;damage_all();
    return pause_worker(false)&&ok;
}
void ln_display_presentation_snapshot(struct ln_display_presentation *output)
{
    if(output)*output=(struct ln_display_presentation){submitted,completed,failures,resets,generation};
}
void ln_display_get_metrics(struct ln_display_metrics *output)
{
    if(output)*output=(struct ln_display_metrics){submitted,completed,completed,
        written_blocks*4u,1u,failures,failures?1u:0u,resets,
        generation,pending?1u:0u,0u,0u,
#if !defined(LINNET_PROFILE_RELEASE)
        max_present_us,
#else
        0,
#endif
        submitted,completed};
}
const uint16_t *ln_display_snapshot(void){return direct_frame?0:frame;}
uint32_t ln_display_snapshot_crc32(void)
{
    const uint16_t *value=ln_display_snapshot();
    return value?ln_crc32((const uint8_t *)value,LINNET_DISPLAY_BYTES):0;
}
size_t ln_display_capture(uint8_t *output,size_t capacity)
{
    if(!initialized||direct_frame||!output||capacity<LINNET_DISPLAY_BYTES)return 0;
    for(uint32_t i=0;i<LINNET_DISPLAY_PIXELS;++i){output[i*2u]=(uint8_t)frame[i];output[i*2u+1u]=(uint8_t)(frame[i]>>8);}
    return LINNET_DISPLAY_BYTES;
}
#if !defined(LINNET_PROFILE_RELEASE)
uint32_t ln_display_column_mismatches(void){return 0;}
void ln_display_sync_diagnostics(uint32_t output[16])
{
    if(!output)return;uint32_t values[16]={0x31595344u,2u,completed,0,0,0,pending,pending,
        submitted,completed,failures,written_blocks*4u,max_present_us,
        pending?ln_time_us()-started:0,max_present_us,ln_time_us()};
    for(uint32_t i=0;i<16u;++i)output[i]=values[i];
}
void ln_display_blit_diagnostics(uint32_t output[16])
{
    if(!output)return;for(uint32_t i=0;i<16u;++i)output[i]=0;output[0]=0x314c4251u;
}
int ln_recovery_presentation_stop(void){return ln_display_quiesce()?1:0;}
#endif
