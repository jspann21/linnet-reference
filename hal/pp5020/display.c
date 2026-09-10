#include "hal/pp5020/display.h"
#include "hal/pp5020/platform.h"
#include "hal/pp5020/core.h"
#include "boot/include/linnet_boot.h"

#define REG(address) (*(volatile uint32_t *)(uintptr_t)(address))
#define MB(offset) REG(LINNET_DISPLAY_MAILBOX + (offset))
#define PORT REG(0x70008a0c)
#define CONTROL REG(0x70008a20)
#define CONFIG REG(0x70008a24)
#define DATA REG(0x70008b00)
#define FRAME_DEADLINE 500000u
#define NATIVE(address) ((uintptr_t)(address) | (uintptr_t)0x10000000u)

struct rectangle { uint32_t x, y, width, height; };
static uint16_t draw_buffer[LINNET_DISPLAY_PIXELS] __attribute__((aligned(4)));
static uint16_t scanout_buffer[LINNET_DISPLAY_PIXELS] __attribute__((aligned(32)));
static struct rectangle damage[LINNET_DISPLAY_QUEUE_CAPACITY];
static uint32_t damage_count, submitted, completed, frame_failures;
static uint32_t frame_started, max_present_us;
static bool initialized, cop_capable, frame_pending;
static bool direct_frame, draw_stale;
static bool clock_park_owned;
static uint32_t cop_error;
static uint32_t init_error;
static volatile bool sync_waiting;
static uint32_t sync_head;
static uint32_t sync_frames,sync_timeouts,sync_wait_us,sync_max_wait_us,transfer_started;
static uint32_t transfer_us,transfer_max_us;

/* P98 GPIO A0: observed active-low frame pulse, 579 us every 16575 us.
 * Arm only while a frame is pending; idle display causes no extra IRQs. */
static void sync_cancel(void) {
    REG(0x6000d050u)&=~1u;
    REG(0x6000d070u)=1u;
    sync_waiting=false;
}
void ln_display_sync_irq(void) {
    if(!sync_waiting || !(REG(0x6000d040u)&1u))return;
    if(REG(0x6000d030u)&1u){
        /* We armed during blanking. Wait for the next complete low pulse. */
        REG(0x6000d060u)&=~1u;
        REG(0x6000d070u)=1u;
        return;
    }
    sync_cancel();
    transfer_started=ln_time_us();
    sync_wait_us=transfer_started-frame_started;
    if(sync_wait_us>sync_max_wait_us)sync_max_wait_us=sync_wait_us;
    ++sync_frames;
    __asm__ volatile("" ::: "memory");
    MB(LN_DISPLAY_HEAD)=sync_head;
}

static void barrier(void) { __asm__ volatile("" ::: "memory"); }
static volatile uint16_t *scanout(void) {
    return (volatile uint16_t *)NATIVE(scanout_buffer);
}

static bool cop_probe(void) {
    /* The nonce exchange rejects a stale capability word left by an older
     * monitor. Old resident instructions are never replaced by this image. */
    if (REG(0x11ffe0a0) != LINNET_DISPLAY_CAPABILITY) { cop_error=1;return false; }
    uint32_t nonce = MB(LN_DISPLAY_PROBE_ACK) + 1u, start = ln_time_us();
    MB(LN_DISPLAY_PROBE) = nonce;
    for (uint32_t budget = 0; budget < 100000u; ++budget) {
        if (MB(LN_DISPLAY_PROBE_ACK) == nonce) return true;
        if (ln_time_us() - start >= 5000u) break;
    }
    cop_error=2;return false;
}

static bool pause_worker(bool pause) {
    if (!cop_capable) return true;
    MB(LN_DISPLAY_PAUSE) = pause ? 1u : 0u;
    barrier();
    uint32_t start = ln_time_us();
    for (uint32_t budget = 0; budget < 100000u; ++budget) {
        if (MB(LN_DISPLAY_PAUSED) == (pause ? 1u : 0u)) return true;
        if (ln_time_us() - start >= 5000u) break;
    }
    return false;
}

bool ln_core_cop_pause(bool pause) {
    cop_error=0;
    if (!pause) {
        if (!clock_park_owned) return true; /* Never wake an inherited sleeper. */
        /* The CPU has finished the clock transaction before this call. */
        MB(LN_DISPLAY_PAUSE)=0;
        REG(0x11ffe010)=ln_time_us();
        barrier();
        REG(0x60007004)=0;
        uint32_t start=ln_time_us();
        for (uint32_t i=0;i<100000u;++i) {
            if (MB(LN_DISPLAY_PAUSED)==0) { clock_park_owned=false;return true; }
            if (ln_time_us()-start>=5000u) break;
        }
        cop_error=6;return false;
    }
    if (clock_park_owned) { cop_error=3;return false; }
    if (REG(0x60007004)&0x80000000u) return true;
    if (!cop_probe()) return false;
    /* Fresh Boot v2 initializes ENABLED but may inherit an arbitrary STATE
     * word before the OS calls display_init. A proven, disabled worker is
     * paused first, then its dormant state is normalized before clock park.
     * This handshake works with the already resident v2 instructions. */
    if (MB(LN_DISPLAY_ENABLED)!=1u) {
        MB(LN_DISPLAY_PAUSE)=1;
        uint32_t prepare_start=ln_time_us();
        bool prepared=false;
        for (uint32_t i=0;i<100000u;++i) {
            if (MB(LN_DISPLAY_PAUSED)==1u) { prepared=true;break; }
            if (ln_time_us()-prepare_start>=5000u) break;
        }
        if (!prepared) { MB(LN_DISPLAY_PAUSE)=0;cop_error=4;return false; }
        MB(LN_DISPLAY_STATE)=0;
        barrier();
    }
    MB(LN_DISPLAY_PAUSE)=2;
    uint32_t start=ln_time_us();
    for (uint32_t i=0;i<5000000u;++i) {
        if (MB(LN_DISPLAY_PAUSED)==2 && (REG(0x60007004)&0x80000000u)) {
            clock_park_owned=true;return true;
        }
        if (ln_time_us()-start>=300000u) break;
    }
    /* Withdraw a failed request. If COP crossed the park point concurrently,
     * observe its actual sleep before waking only this acknowledged worker. */
    MB(LN_DISPLAY_PAUSE)=0;
    start=ln_time_us();
    for (uint32_t i=0;i<100000u;++i) {
        if (MB(LN_DISPLAY_PAUSED)==0) { cop_error=5;return false; }
        if (MB(LN_DISPLAY_PAUSED)==2 && (REG(0x60007004)&0x80000000u)) {
            clock_park_owned=true;(void)ln_core_cop_pause(false);cop_error=5;return false;
        }
        if (ln_time_us()-start>=5000u) break;
    }
    cop_error=7;return false;
}

uint32_t ln_display_cop_error(void) { return cop_error; }
static bool monitor_signature(uint32_t *branch)
{
    /* Boot v2 header copied from ln_cop_begin to0x40001000. These offsets are
     * bounded to its first184 bytes and were checked against installed Boot
     * 3dfc7bd0a7b1. Reject any other layout rather than scanning or relocating
     * an executing resident worker. The branch displacement stays unchanged. */
    if(REG(0x11ffe0a0u)!=LINNET_DISPLAY_CAPABILITY||REG(0x11ffe018u)!=0x4c4e434fu)
        return false;
    if(REG(0x40001040u)!=0xe5923000u|| /* ldr r3,[r2]: timer */
       REG(0x40001044u)!=0xe580301cu|| /* publish COP tick */
       REG(0x40001054u)!=0xe5904010u|| /* ldr r4,[r0,#16]: CPU progress */
       REG(0x40001058u)!=0xe0434004u|| /* sub r4,r3,r4 */
       REG(0x4000105cu)!=0xe59f504cu|| /* load750ms literal */
       REG(0x40001060u)!=0xe1540005u|| /* cmp elapsed,deadline */
       REG(0x400010b0u)!=750000u||REG(0x400010b8u)!=1500000u)return false;
    *branch=REG(0x40001064u);
    return *branch==0x3afffff4u||*branch==0xbafffff4u;
}
bool ln_display_upgrade_monitor(void)
{
    uint32_t branch;
    if(!monitor_signature(&branch)){cop_error=8;return false;}
    if(branch==0xbafffff4u)return true;
    /* A monitor we did not park must not be modified or woken by this call. */
    if(REG(0x60007004u)&0x80000000u){cop_error=8;return false;}
    if(!ln_core_cop_pause(true))return false;
    bool patched=false;
    if(MB(LN_DISPLAY_PAUSED)==2u&&(REG(0x60007004u)&0x80000000u)&&
       monitor_signature(&branch)){
        /* Signed LT also rejects a future progress sample after timer wrap.
         * Normal watchdog deadlines are well inside the signed half-range. */
        REG(0x40001064u)=(branch&0x0fffffffu)|0xb0000000u;
        barrier();
        patched=REG(0x40001064u)==0xbafffff4u;
    }
    bool resumed=ln_core_cop_pause(false);
    if(!patched)cop_error=9;
    return patched&&resumed;
}
void ln_display_cop_diagnostics(uint32_t output[8]) {
    if (!output) return;
    output[0]=cop_error;output[1]=REG(0x11ffe0a0);output[2]=REG(0x60007004);
    output[3]=MB(LN_DISPLAY_ENABLED);output[4]=MB(LN_DISPLAY_STATE);
    output[5]=MB(LN_DISPLAY_PAUSE);output[6]=MB(LN_DISPLAY_PAUSED);
    output[7]=MB(LN_DISPLAY_PROBE_ACK);
}

static void fail_job(uint32_t reason) {
    CONFIG = 0;
    MB(LN_DISPLAY_ERROR) = reason;
    MB(LN_DISPLAY_FAILURES)++;
    MB(LN_DISPLAY_STATE) = 0;
    MB(LN_DISPLAY_TAIL) = MB(LN_DISPLAY_HEAD);
}

/* Same five states and mailbox offsets as the resident COP worker. One step
 * performs one command write, pixel-pair write or readiness observation. */
static void cpu_step(void) {
    uint32_t state = MB(LN_DISPLAY_STATE);
    MB(LN_DISPLAY_TICKS)++;
    if (state == 0) {
        uint32_t head = MB(LN_DISPLAY_HEAD), tail = MB(LN_DISPLAY_TAIL);
        if (head == tail) return;
        if (head - tail > LINNET_DISPLAY_QUEUE_CAPACITY) { fail_job(3); return; }
        uint32_t slot = LN_DISPLAY_QUEUE + (tail & 7u) * 16u;
        uint32_t x = MB(slot), y = MB(slot + 4), width = MB(slot + 8), height = MB(slot + 12);
        uint32_t buffer = MB(LN_DISPLAY_BUFFER);
        if (x >= 220u || y >= 176u || !width || !height || width > 220u-x ||
            height > 176u-y || ((x | width) & 1u) || (buffer & 3u) ||
            buffer < 0x10000000u || buffer > 0x10800000u-LINNET_DISPLAY_BYTES) { fail_job(4); return; }
        MB(LN_DISPLAY_X) = x; MB(LN_DISPLAY_Y) = y;
        MB(LN_DISPLAY_WIDTH) = width; MB(LN_DISPLAY_HEIGHT) = height;
        MB(LN_DISPLAY_ROWS_LEFT) = height;
        MB(LN_DISPLAY_X_CURSOR) = MB(LN_DISPLAY_Y_CURSOR) = MB(LN_DISPLAY_COMMAND) = 0;
        MB(LN_DISPLAY_BUDGET) = 1000000u;
        MB(LN_DISPLAY_STARTED) = ln_time_us();
        MB(LN_DISPLAY_STATE) = 1;
        return;
    }
    if (ln_time_us() - MB(LN_DISPLAY_STARTED) >= FRAME_DEADLINE) { fail_job(1); return; }
    if (!MB(LN_DISPLAY_BUDGET)) { fail_job(2); return; }
    MB(LN_DISPLAY_BUDGET)--;
    if (state == 1) {
        if (PORT & 0x80000000u) return;
        uint32_t command = MB(LN_DISPLAY_COMMAND), value;
        if (command == 0) value = 0x12u;
        else if (command == 1) value = MB(LN_DISPLAY_Y);
        else if (command == 2) value = 0x13u;
        else if (command == 3) value = 219u-MB(LN_DISPLAY_X);
        else if (command == 4) value = 0x15u;
        else if (command == 5) value = MB(LN_DISPLAY_Y)+MB(LN_DISPLAY_HEIGHT)-1u;
        else if (command == 6) value = 0x16u;
        else value = 220u-MB(LN_DISPLAY_X)-MB(LN_DISPLAY_WIDTH);
        PORT = 0x80000000u | value;
        MB(LN_DISPLAY_COMMAND) = command+1u;
        if (command == 7) MB(LN_DISPLAY_STATE) = 2;
        return;
    }
    if (state == 2) {
        if (PORT & 0x80000000u) return;
        uint32_t rows = MB(LN_DISPLAY_ROWS_LEFT);
        if (rows > 128u) rows = 128u;
        uint32_t bytes = rows * MB(LN_DISPLAY_WIDTH) * 2u;
        MB(LN_DISPLAY_BLOCK_ROWS) = rows;
        MB(LN_DISPLAY_PAIRS_LEFT) = bytes / 4u;
        CONTROL = 0x10000080u; CONFIG = 0xc0010000u | (bytes-1u); CONTROL = 0x34000000u;
        MB(LN_DISPLAY_STATE) = 3;
        return;
    }
    if (state == 3) {
        if (!(CONTROL & 0x01000000u)) return;
        uint32_t offset = (MB(LN_DISPLAY_Y)+MB(LN_DISPLAY_Y_CURSOR))*220u +
                          MB(LN_DISPLAY_X)+MB(LN_DISPLAY_X_CURSOR);
        const volatile uint16_t *pixels = (const volatile uint16_t *)(uintptr_t)MB(LN_DISPLAY_BUFFER);
        uint16_t first = pixels[offset], second = pixels[offset+1u];
        DATA = ((uint32_t)(first & 255u)<<8) | (first>>8) |
               ((uint32_t)(second & 255u)<<24) | ((uint32_t)(second>>8)<<16);
        uint32_t column = MB(LN_DISPLAY_X_CURSOR)+2u;
        if (column == MB(LN_DISPLAY_WIDTH)) { column=0; MB(LN_DISPLAY_Y_CURSOR)++; }
        MB(LN_DISPLAY_X_CURSOR)=column;
        MB(LN_DISPLAY_PAIRS)++;
        MB(LN_DISPLAY_PAIRS_LEFT)--;
        if (!MB(LN_DISPLAY_PAIRS_LEFT)) MB(LN_DISPLAY_STATE)=4;
        return;
    }
    if (state == 4) {
        if (!(CONTROL & 0x04000000u)) return;
        CONFIG=0;
        MB(LN_DISPLAY_ROWS_LEFT)-=MB(LN_DISPLAY_BLOCK_ROWS);
        if (MB(LN_DISPLAY_ROWS_LEFT)) { MB(LN_DISPLAY_STATE)=2; return; }
        MB(LN_DISPLAY_STATE)=0;
        barrier();
        MB(LN_DISPLAY_TAIL)++;
        MB(LN_DISPLAY_COMPLETED)++;
        return;
    }
    fail_job(5);
}

bool ln_display_init(void) {
    initialized=false;
    init_error=0;
    cop_capable=cop_probe();
    if (!pause_worker(true)) {init_error=0x01000000u|((MB(LN_DISPLAY_PAUSED)&255u)<<16)|cop_error;return false;}
    uint32_t generation=MB(LN_DISPLAY_MAGIC)==LINNET_DISPLAY_MAGIC ? MB(LN_DISPLAY_GENERATION)+1u : 1u;
    MB(LN_DISPLAY_ENABLED)=0;
    CONFIG=0;
    for (uint32_t offset=0;offset<120u;offset+=4u)
        if (offset!=LN_DISPLAY_PAUSE && offset!=LN_DISPLAY_PAUSED) MB(offset)=0;
    if (!cop_capable) MB(LN_DISPLAY_PAUSE)=MB(LN_DISPLAY_PAUSED)=0;
    MB(LN_DISPLAY_GENERATION)=generation;
    MB(LN_DISPLAY_BUFFER)=(uint32_t)NATIVE(scanout_buffer);
    MB(LN_DISPLAY_MAGIC)=LINNET_DISPLAY_MAGIC;
    for (uint32_t i=0;i<LINNET_DISPLAY_PIXELS;++i) { draw_buffer[i]=0; scanout()[i]=0; }
    damage_count=submitted=completed=frame_failures=max_present_us=0;
    frame_pending=direct_frame=draw_stale=false;
    sync_cancel();
    sync_frames=sync_timeouts=sync_wait_us=sync_max_wait_us=0;
    transfer_us=transfer_max_us=0;
    if (!ln_lcd_fill(0)) {
        init_error=0x02000000u;
#if !defined(LINNET_PROFILE_RELEASE)
        uint32_t lcd[8];ln_lcd_diagnostics(lcd);init_error|=((lcd[1]&255u)<<16)|(lcd[0]&65535u);
#endif
        return false;
    }
    initialized=true;
    MB(LN_DISPLAY_ENABLED)=cop_capable?1u:0u;
    if (!pause_worker(false)) {init_error=0x03000000u|((MB(LN_DISPLAY_PAUSED)&255u)<<16)|cop_error;initialized=false;return false;}
    return ln_display_damage(0,0,220,176);
}
uint32_t ln_display_init_error(void){return init_error;}

uint16_t *ln_display_framebuffer(void) {
    if(direct_frame)return NULL;
    if(draw_stale){
        /* Import the retained video once before ordinary incremental UI
         * resumes. The COP only reads scanout, so this is also safe when busy. */
        barrier();
#if defined(__arm__)
        extern void ln_memory_copy(void *,const void *,uint32_t);
        ln_memory_copy(draw_buffer,(const void *)(uintptr_t)scanout(),LINNET_DISPLAY_BYTES);
#else
        for(uint32_t i=0;i<LINNET_DISPLAY_PIXELS;++i)draw_buffer[i]=scanout()[i];
#endif
        barrier();draw_stale=false;
    }
    return draw_buffer;
}

uint16_t *ln_display_direct_framebuffer(void) {
    if(!initialized||direct_frame||frame_pending||damage_count||
       MB(LN_DISPLAY_HEAD)!=MB(LN_DISPLAY_TAIL))return NULL;
    /* A synchronous full repaint owns scanout until present publishes it.
     * Seed full damage even if the painter coalesces its own damage callbacks. */
    direct_frame=draw_stale=true;
    damage[0]=(struct rectangle){0,0,220,176};damage_count=1;
    barrier();
    return (uint16_t *)(uintptr_t)scanout();
}

bool ln_display_damage(int32_t x,int32_t y,int32_t width,int32_t height) {
    if (!initialized || width<=0 || height<=0 || x>=220 || y>=176) return false;
    if (x<0) { if (x<=-width) return false; width+=x; x=0; }
    if (y<0) { if (y<=-height) return false; height+=y; y=0; }
    if (width>220-x) width=220-x;
    if (height>176-y) height=176-y;
    uint32_t right=((uint32_t)(x+width)+1u)&~1u;
    x&=~1;
    struct rectangle rectangle={(uint32_t)x,(uint32_t)y,right-(uint32_t)x,(uint32_t)height};
    for (uint32_t i=0;i<damage_count;++i) {
        struct rectangle *other=&damage[i];
        if (rectangle.x<=other->x+other->width && other->x<=rectangle.x+rectangle.width &&
            rectangle.y<=other->y+other->height && other->y<=rectangle.y+rectangle.height) {
            uint32_t left=rectangle.x<other->x?rectangle.x:other->x;
            uint32_t top=rectangle.y<other->y?rectangle.y:other->y;
            uint32_t end_x=rectangle.x+rectangle.width>other->x+other->width?rectangle.x+rectangle.width:other->x+other->width;
            uint32_t end_y=rectangle.y+rectangle.height>other->y+other->height?rectangle.y+rectangle.height:other->y+other->height;
            /* A scrollbar touching a selection row must not expand that row
             * into a full list transfer. Merge only when the bounding box
             * costs no more pixels than the two existing jobs. */
            if ((end_x-left)*(end_y-top)>
                rectangle.width*rectangle.height+other->width*other->height) continue;
            *other=(struct rectangle){left,top,end_x-left,end_y-top};
            return true;
        }
    }
    if (damage_count==LINNET_DISPLAY_QUEUE_CAPACITY) {
        damage[0]=(struct rectangle){0,0,220,176};damage_count=1;
    } else damage[damage_count++]=rectangle;
    return true;
}

bool ln_display_present(void) {
    if (!initialized || !damage_count || frame_pending || MB(LN_DISPLAY_HEAD)!=MB(LN_DISPLAY_TAIL)) return false;
    /* A reset/retry may publish without another ordinary UI render. */
    if(!direct_frame&&draw_stale)(void)ln_display_framebuffer();
    /* The scanout buffer retains the previous complete frame. Publish only
     * damaged pixels while the COP is idle; small focus changes must not
     * copy an entire framebuffer through uncached SDRAM. */
    for (uint32_t i=0;!direct_frame&&i<damage_count;++i) {
        const struct rectangle *r=&damage[i];
#if defined(__arm__)
        /* The external assembly routine performs every store to the uncached
         * alias. Barriers retain volatile publication ordering; ownership
         * remains with the CPU until the existing mailbox head publication. */
        extern void ln_memory_copy(void *,const void *,uint32_t);
        barrier();
        if(r->x==0u&&r->width==220u){
            uint32_t begin=r->y*220u;
            ln_memory_copy((void *)(uintptr_t)(scanout()+begin),
                draw_buffer+begin,r->height*440u);
        }else for(uint32_t y=r->y;y<r->y+r->height;++y){
            uint32_t begin=y*220u+r->x;
            ln_memory_copy((void *)(uintptr_t)(scanout()+begin),
                draw_buffer+begin,r->width*2u);
        }
        barrier();
#else
        for(uint32_t y=r->y;y<r->y+r->height;++y) {
            uint32_t begin=y*220u+r->x, remaining=r->width;
            /* Both buffers are word aligned. Keep scalar edges so this copy
             * also remains exact if a future damage producer uses odd spans. */
            if((begin&1u)&&remaining){scanout()[begin]=draw_buffer[begin];++begin;--remaining;}
            typedef uint32_t copy_word __attribute__((__may_alias__));
            const copy_word *source=(const copy_word *)(draw_buffer+begin);
            volatile copy_word *destination=(volatile copy_word *)(scanout()+begin);
            while(remaining>=2u){*destination++=*source++;remaining-=2u;}
            if(remaining)*(volatile uint16_t *)destination=*(const uint16_t *)source;
        }
#endif
    }
    /* The panel reaches the right edge first. A narrow first strip must
     * finish before that edge is scanned; subsequent strips follow it left.
     * Keep large repaints contiguous to avoid extra command overhead. */
    struct rectangle jobs[LINNET_DISPLAY_QUEUE_CAPACITY];
    uint32_t job_count=0,eligible=0;
    for(uint32_t i=0;i<damage_count;++i)
        if(damage[i].width>64u&&damage[i].height<=64u)++eligible;
    for(uint32_t i=0;i<damage_count;++i){
        struct rectangle r=damage[i];uint32_t parts=1;
        if(r.width>64u&&r.height<=64u){
            parts+=(LINNET_DISPLAY_QUEUE_CAPACITY-damage_count-(job_count-i))/eligible;
            --eligible;
        }
        uint32_t right=r.x+r.width,remaining=r.width;
        for(uint32_t j=0;j<parts;++j){
            uint32_t width=parts==1u?r.width:j==0u?8u:((remaining/2u)/(parts-j))*2u;
            right-=width;remaining-=width;
            jobs[job_count++]=(struct rectangle){right,r.y,width,r.height};
        }
    }
    for(uint32_t i=1;i<job_count;++i){
        struct rectangle r=jobs[i];uint32_t j=i;
        while(j&&jobs[j-1u].x<r.x){jobs[j]=jobs[j-1u];--j;}
        jobs[j]=r;
    }
    uint32_t head=MB(LN_DISPLAY_HEAD);
    for (uint32_t i=0;i<job_count;++i) {
        uint32_t slot=LN_DISPLAY_QUEUE+((head+i)&7u)*16u;
        MB(slot)=jobs[i].x;MB(slot+4)=jobs[i].y;
        MB(slot+8)=jobs[i].width;MB(slot+12)=jobs[i].height;
    }
    if (job_count>MB(LN_DISPLAY_HIGH_WATER)) MB(LN_DISPLAY_HIGH_WATER)=job_count;
    frame_failures=MB(LN_DISPLAY_FAILURES);
    frame_started=ln_time_us();
    frame_pending=true;submitted++;
    barrier();
    uint32_t irq=ln_core_irq_save();
    sync_head=head+job_count;
    sync_waiting=true;
    REG(0x6000d060u)=(REG(0x6000d060u)&~1u)|((REG(0x6000d030u)&1u)?0u:1u);
    REG(0x6000d070u)=1u;
    REG(0x6000d050u)|=1u;
    ln_core_input_rearm();
    ln_core_irq_restore(irq);
    damage_count=0;
    direct_frame=false;
    return true;
}

bool ln_display_service(uint32_t max_pairs) {
    if (!initialized) return false;
    /* A missing panel pulse must not stall display ownership or recovery. */
    if(sync_waiting){
        if(ln_time_us()-frame_started<25000u)return true;
        uint32_t irq=ln_core_irq_save();
        if(sync_waiting){sync_cancel();++sync_timeouts;transfer_started=ln_time_us();barrier();MB(LN_DISPLAY_HEAD)=sync_head;}
        ln_core_irq_restore(irq);
    }
    if (max_pairs>256u) max_pairs=256u;
    if (!cop_capable) for (uint32_t i=0;i<max_pairs && MB(LN_DISPLAY_HEAD)!=MB(LN_DISPLAY_TAIL);++i) cpu_step();
    if (frame_pending && MB(LN_DISPLAY_HEAD)==MB(LN_DISPLAY_TAIL)) {
        frame_pending=false;
        if (frame_failures!=MB(LN_DISPLAY_FAILURES)) { (void)ln_display_damage(0,0,220,176);return false; }
        uint32_t elapsed=ln_time_us()-frame_started;
        transfer_us=ln_time_us()-transfer_started;
        if(transfer_us>transfer_max_us)transfer_max_us=transfer_us;
        if (elapsed>max_present_us) max_present_us=elapsed;
        completed++;
    }
    return true;
}

bool ln_display_busy(void) { return frame_pending || MB(LN_DISPLAY_HEAD)!=MB(LN_DISPLAY_TAIL); }
bool ln_display_cop_capable(void) { return cop_capable; }

bool ln_display_quiesce(void) {
    if (!initialized) return true;
    uint32_t irq=ln_core_irq_save();sync_cancel();ln_core_irq_restore(irq);
    if (!pause_worker(true)) return false;
    MB(LN_DISPLAY_ENABLED)=0;CONFIG=0;
    MB(LN_DISPLAY_STATE)=0;MB(LN_DISPLAY_TAIL)=MB(LN_DISPLAY_HEAD);
    frame_pending=direct_frame=false;
    return true;
}

bool ln_display_reset(void) {
    if (!initialized || !ln_display_quiesce()) return false;
    MB(LN_DISPLAY_GENERATION)++;MB(LN_DISPLAY_RESETS)++;
    MB(LN_DISPLAY_HEAD)=MB(LN_DISPLAY_TAIL)=0;
    damage_count=0;
    MB(LN_DISPLAY_ENABLED)=cop_capable?1u:0u;
    if (!pause_worker(false)) return false;
    return ln_display_damage(0,0,220,176);
}

void ln_display_presentation_snapshot(struct ln_display_presentation *output) {
    if (!output) return;
    *output=(struct ln_display_presentation){submitted,completed,
        MB(LN_DISPLAY_FAILURES),MB(LN_DISPLAY_RESETS),MB(LN_DISPLAY_GENERATION)};
}

void ln_display_get_metrics(struct ln_display_metrics *output) {
    if (!output) return;
    *output=(struct ln_display_metrics){submitted,completed,MB(LN_DISPLAY_COMPLETED),MB(LN_DISPLAY_PAIRS),
        MB(LN_DISPLAY_HIGH_WATER),MB(LN_DISPLAY_FAILURES),MB(LN_DISPLAY_ERROR),MB(LN_DISPLAY_RESETS),
        MB(LN_DISPLAY_GENERATION),MB(LN_DISPLAY_HEAD)-MB(LN_DISPLAY_TAIL),cop_capable,
        cop_capable && MB(LN_DISPLAY_ENABLED) && !MB(LN_DISPLAY_PAUSED),
        max_present_us,MB(LN_DISPLAY_HEAD),MB(LN_DISPLAY_TAIL)};
}

const uint16_t *ln_display_snapshot(void) { return direct_frame?NULL:(const uint16_t *)NATIVE(scanout_buffer); }
uint32_t ln_display_snapshot_crc32(void) { const uint16_t *frame=ln_display_snapshot();return frame?ln_crc32((const uint8_t *)frame,LINNET_DISPLAY_BYTES):0; }
size_t ln_display_capture(uint8_t *output,size_t capacity) {
    if (!initialized || direct_frame || !output || capacity<LINNET_DISPLAY_BYTES) return 0;
    for (uint32_t i=0;i<LINNET_DISPLAY_PIXELS;++i) {
        uint16_t pixel=scanout()[i];output[2u*i]=(uint8_t)pixel;output[2u*i+1u]=(uint8_t)(pixel>>8);
    }
    return LINNET_DISPLAY_BYTES;
}

#if !defined(LINNET_PROFILE_RELEASE)
void ln_display_sync_diagnostics(uint32_t output[16]) {
    uint32_t irq=ln_core_irq_save();
    uint32_t words[16]={0x31595344u,1u,sync_frames,sync_timeouts,sync_wait_us,
        sync_max_wait_us,sync_waiting,frame_pending,submitted,completed,
        MB(LN_DISPLAY_FAILURES),MB(LN_DISPLAY_PAIRS),max_present_us,
        transfer_us,transfer_max_us,ln_time_us()};
    for(uint32_t i=0;i<16u;++i)output[i]=words[i];
    ln_core_irq_restore(irq);
}
#endif

/* Called before any RAM replacement, including panic recovery. */
#if !defined(LINNET_PROFILE_RELEASE)
int ln_recovery_presentation_stop(void) { return ln_display_quiesce()?1:0; }
#endif
