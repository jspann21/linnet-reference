#include "hal/pp5020/platform.h"

/* Register addresses and bus protocol provenance: ARCHITECTURE.md. */
#define LINNET_REG(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define LINNET_LCD_PORT LINNET_REG(0x70008a0cu)
#define LINNET_LCD_CONTROL LINNET_REG(0x70008a20u)
#define LINNET_LCD_CONFIG LINNET_REG(0x70008a24u)
#define LINNET_LCD_DATA LINNET_REG(0x70008b00u)
/* Physical P98 diagnostic: a complete 19,360-pair frame took 109,382 us with
 * only nine unsuccessful polls. The former 100 ms limit could therefore fail
 * on an incidental late FIFO/READY poll. Allow 250 ms for the complete frame,
 * below the independent 500 ms watchdog; do not refresh watchdog progress here. */
#define LINNET_LCD_FRAME_TIMEOUT_US 250000u
static uint32_t ln_last_progress;
static bool ln_panel_ready;
#if !defined(LINNET_PROFILE_RELEASE)
static uint32_t ln_lcd_trace[8];
void ln_lcd_diagnostics(uint32_t output[8])
{
    if (output)
        for (uint32_t i = 0; i < 8u; ++i) output[i] = ln_lcd_trace[i];
}
#define LINNET_LCD_RECORD(index, value) (ln_lcd_trace[(index)] = (value))
#else
#define LINNET_LCD_RECORD(index, value) ((void)0)
#endif

uint32_t ln_time_us(void) { return LINNET_REG(0x60005010u); }

/* Both elapsed time and instruction-count bounds: a stopped timer cannot hang
 * an LCD operation. One budget covers the complete frame, including commands. */
static bool ln_wait(volatile uint32_t *reg, uint32_t mask, bool set,
                    uint32_t started, uint32_t timeout_us, uint32_t *budget)
{
    while (((*reg & mask) != 0u) != set) {
        if (*budget == 0u || ln_time_us() - started >= timeout_us) return false;
        --*budget;
    }
    return true;
}

static bool ln_lcd_wait(volatile uint32_t *reg, uint32_t mask, bool set,
                        uint32_t started, uint32_t *budget)
{
    if (ln_wait(reg, mask, set, started, LINNET_LCD_FRAME_TIMEOUT_US, budget)) return true;
    LINNET_LCD_RECORD(1, *budget == 0u ? 2u : 1u);
    return false;
}

#if defined(LINNET_PLATFORM_CORE) && defined(LINNET_IMAGE_BOOT)
uint32_t ln_platform_boot_clock_ready(void)
{
    /* The measured native handoff leaves USB0 enabled, USB1 gated, neither
     * reset, and INIT_USB clear. Acquire only that known state using the
     * established controller_start/Rockbox enable-then-reset-pulse sequence.
     * USB0 assertion does not remain readable on this device. Neither its
     * pulse nor USB1 alone is an idle proof: the ARC proof below is required. */
    const uint32_t modules=0x00400008u;
    uint32_t enabled=LINNET_REG(0x6000600cu)&modules;
    if(enabled!=modules){
        if(enabled!=8u||(LINNET_REG(0x70000020u)&0x80000000u))return 7u;
        if(LINNET_REG(0x60006004u)&modules)return 8u;
        LINNET_REG(0x6000d01cu)&=~8u;
        LINNET_REG(0x6000d00cu)|=8u;
        LINNET_REG(0x7000002cu)|=0x03000000u;
        LINNET_REG(0x6000600cu)|=modules;
        if((LINNET_REG(0x6000600cu)&modules)!=modules)return 16u;
        /* Match the native-qualified transport's separate reset pulses. Do
         * not infer held reset from a write or require USB0 assertion to latch. */
        LINNET_REG(0x60006004u)|=8u;
        LINNET_REG(0x60006004u)&=~8u;
        LINNET_REG(0x60006004u)|=0x00400000u;
        LINNET_REG(0x60006004u)&=~0x00400000u;
        if(LINNET_REG(0x60006004u)&modules)return 17u;
        LINNET_REG(0x70000020u)|=0x80000000u;
        uint32_t started=ln_time_us(),budget=2000000u;
        if(!ln_wait(&LINNET_REG(0x70000028u),0x80u,true,started,100000u,&budget))return 18u;
        LINNET_REG(0x70000028u)|=2u;
        started=ln_time_us();budget=20000000u;
        while(ln_time_us()-started<100000u)if(!budget--)return 19u;
        LINNET_REG(0x7000003cu)|=0x47au;
        if((LINNET_REG(0x7000003cu)&0x47au)!=0x47au)return 20u;
    }
    if((LINNET_REG(0x6000600cu)&modules)!=modules)return 7u;
    if(LINNET_REG(0x60006004u)&modules)return 8u;
    LINNET_REG(0xc5000148u)=0; /* ARC interrupt enable */
    LINNET_REG(0xc5000140u)&=~1u; /* RUN */
    if(LINNET_REG(0xc5000140u)&1u)return 9u;
    LINNET_REG(0xc50001b4u)=UINT32_MAX; /* ENDPTFLUSH */
    uint32_t started=ln_time_us(),budget=2000000u;
    if(!ln_wait(&LINNET_REG(0xc50001b4u),UINT32_MAX,false,started,20000u,&budget))return 10u;
    /* An endpoint may have crossed PRIME during the first flush. Repeat at
     * most once, as the established ARC owner does, without descriptor writes. */
    if(LINNET_REG(0xc50001b8u)){
        LINNET_REG(0xc50001b4u)=UINT32_MAX;
        started=ln_time_us();budget=2000000u;
        if(!ln_wait(&LINNET_REG(0xc50001b4u),UINT32_MAX,false,started,20000u,&budget)||
           LINNET_REG(0xc50001b8u))return 11u;
    }
    /* Fresh PHY setup retains controller_start's250ms stop interval; an
     * already accessible controller retains the established50ms stop.
     * No lease renewal occurs
     * in a wait; elapsed and instruction budgets both bound the whole stage. */
    started=ln_time_us();budget=20000000u;
    uint32_t stop_us=enabled==modules?50000u:250000u;
    while(ln_time_us()-started<stop_us)if(!budget--)return 12u;
    LINNET_REG(0xc5000140u)|=2u; /* RESET */
    started=ln_time_us();budget=2000000u;
    if(!ln_wait(&LINNET_REG(0xc5000140u),2u,false,started,100000u,&budget))return 13u;
    /* Keep module clocks untouched: USB0 gating breaks native loader/pin
     * detection. Only completed reset plus idle ARC grants a clock change. */
    return (!(LINNET_REG(0xc5000140u)&3u)&&
        !(LINNET_REG(0xc50001b0u)|LINNET_REG(0xc50001b4u)|LINNET_REG(0xc50001b8u))&&
        (LINNET_REG(0x6000600cu)&modules)==modules&&
        !(LINNET_REG(0x60006004u)&modules))?0u:14u;
}
#endif

static void ln_lcd_record_end(uint32_t started, uint32_t budget, uint32_t pairs)
{
#if !defined(LINNET_PROFILE_RELEASE)
    ln_lcd_trace[2] = ln_time_us() - started;
    ln_lcd_trace[3] = pairs;
    ln_lcd_trace[4] = budget;
    /* Read status before failure cleanup cancels the active controller block. */
    ln_lcd_trace[5] = LINNET_LCD_CONTROL;
    ln_lcd_trace[6] = LINNET_LCD_CONFIG;
    ln_lcd_trace[7] = LINNET_LCD_PORT;
#else
    (void)started;
    (void)budget;
    (void)pairs;
#endif
}

static bool ln_lcd_command(uint32_t command, uint32_t value,
                           uint32_t started, uint32_t *budget)
{
    LINNET_LCD_RECORD(0, 3u | (command << 16));
    if (!ln_lcd_wait(&LINNET_LCD_PORT, 0x80000000u, false, started, budget)) return false;
    LINNET_LCD_PORT = 0x80000000u | command;
    if (!ln_lcd_wait(&LINNET_LCD_PORT, 0x80000000u, false, started, budget)) return false;
    LINNET_LCD_PORT = 0x80000000u | value;
    return true;
}

/* Self-contained 5x7 uppercase glyphs: no UI, heap, storage or font pointer
 * is needed when the application itself has faulted. Rows are bit masks. */
static uint16_t ln_fault_pixel(const char lines[8][33],uint32_t x,uint32_t y)
{
    static const uint8_t glyphs[36][7]={
        {14,17,19,21,25,17,14},{4,12,4,4,4,4,14},{14,17,1,2,4,8,31},
        {30,1,1,14,1,1,30},{2,6,10,18,31,2,2},{31,16,16,30,1,1,30},
        {14,16,16,30,17,17,14},{31,1,2,4,8,8,8},{14,17,17,14,17,17,14},
        {14,17,17,15,1,1,14},{14,17,17,31,17,17,17},{30,17,17,30,17,17,30},
        {14,17,16,16,16,17,14},{30,17,17,17,17,17,30},{31,16,16,30,16,16,31},
        {31,16,16,30,16,16,16},{14,17,16,23,17,17,15},{17,17,17,31,17,17,17},
        {14,4,4,4,4,4,14},{7,2,2,2,2,18,12},{17,18,20,24,20,18,17},
        {16,16,16,16,16,16,31},{17,27,21,21,17,17,17},{17,25,21,19,17,17,17},
        {14,17,17,17,17,17,14},{30,17,17,30,16,16,16},{14,17,17,17,21,18,13},
        {30,17,17,30,20,18,17},{15,16,16,14,1,1,30},{31,4,4,4,4,4,4},
        {17,17,17,17,17,17,14},{17,17,17,17,17,10,4},{17,17,17,21,21,27,17},
        {17,17,10,4,10,17,17},{17,17,10,4,4,4,4},{31,1,2,4,8,16,31}};
    const uint16_t background=0x1800u;
    if(x<14u||x>=206u||y<8u||y>=168u)return background;
    x-=14u;y-=8u;uint32_t line=y/20u,row=(y%20u)/2u,column=x/6u,bit=x%6u;
    if(row>=7u||bit>=5u)return background;
    uint8_t c=(uint8_t)lines[line][column],mask=0;
    if(c>='0'&&c<='9')mask=glyphs[c-'0'][row];
    else if(c>='A'&&c<='Z')mask=glyphs[c-'A'+10u][row];
    else if(c=='+')mask=row==3u?14u:(row==2u||row==4u?4u:0u);
    else if(c==':')mask=row==2u||row==5u?4u:0u;
    return mask&(16u>>bit)?0xffffu:background;
}

static bool ln_lcd_draw(uint16_t color, const char (*fault_rows)[33])
{
    uint32_t started = ln_time_us(), budget = 1000000u;
    uint32_t pairs_written = 0;
    LINNET_LCD_RECORD(0, 0u);
    LINNET_LCD_RECORD(1, 0u);
    if (!ln_panel_ready) {
        LINNET_LCD_RECORD(0, 1u);
        LINNET_REG(0x6000600cu) |= 0x04000000u;
        LINNET_LCD_CONFIG = 0;
        LINNET_REG(0x60006004u) |= 0x04000000u;
        uint32_t reset_started = ln_time_us();
        for (uint32_t i = 0; ln_time_us() - reset_started < 1u; ++i)
            if (i == 99999u) { LINNET_LCD_RECORD(1, 3u); goto failed; }
        LINNET_REG(0x60006004u) &= ~0x04000000u;
        uint32_t delay_start = ln_time_us();
        LINNET_LCD_RECORD(0, 2u);
        for (uint32_t i = 0; ln_time_us() - delay_start < 1000u; ++i)
            if (i == 999999u) { LINNET_LCD_RECORD(1, 3u); goto failed; }
        static const uint16_t registers[8][2] = {
            {0xefu,0}, {1u,0}, {0x80u,1u}, {0x10u,0xcu},
            {0x18u,6u}, {0x7eu,4u}, {0x7eu,5u}, {0x7fu,1u}
        };
        for (uint32_t i = 0; i < 8u; ++i)
            if (!ln_lcd_command(registers[i][0], registers[i][1], started, &budget)) goto failed;
        /* PP5020 atomic GPIO alias packs mask in high byte, value in low. */
        LINNET_REG(0x6000d804u) = 0x0c0cu;
        LINNET_REG(0x6000d824u) = 0x0808u;
        LINNET_REG(0x70000084u) &= ~0x02000000u;
        LINNET_REG(0x6000600cu) |= 0x00020000u;
        LINNET_REG(0x7000a010u) = 0x80640000u;
        ln_panel_ready = true;
    }
    /* Program the full panel window once. The panel cursor continues across
     * bridge blocks; restarting it for every row adds 176 command/flush cycles.
     * PP5020 blocks have a 16-bit byte count, so 220x176 needs 148 + 28 rows. */
    if (!ln_lcd_command(0x12u, 0u, started, &budget) ||
        !ln_lcd_command(0x13u, LINNET_LCD_WIDTH - 1u, started, &budget) ||
        !ln_lcd_command(0x15u, LINNET_LCD_HEIGHT - 1u, started, &budget) ||
        !ln_lcd_command(0x16u, 0u, started, &budget)) goto failed;
    /* The old Photo panel consumes byte-swapped RGB565 on this bus. */
    uint16_t bus_color = (uint16_t)((color << 8) | (color >> 8));
    uint32_t pixel_pair = (uint32_t)bus_color | ((uint32_t)bus_color << 16);
    uint32_t rows_left = LINNET_LCD_HEIGHT;
    while (rows_left != 0u) {
        uint32_t rows = rows_left > 148u ? 148u : rows_left;
        uint32_t bytes = rows * LINNET_LCD_WIDTH * 2u;
        LINNET_LCD_CONTROL = 0x10000080u;
        LINNET_LCD_CONFIG = 0xc0010000u | (bytes - 1u);
        LINNET_LCD_CONTROL = 0x34000000u;
        LINNET_LCD_RECORD(0, 5u | ((rows_left == LINNET_LCD_HEIGHT ? 1u : 2u) << 8));
        for (uint32_t pair = 0; pair < bytes / 4u; ++pair) {
            /* Check the deadline even when FIFO is continuously ready, with
             * one timer read per 256 pairs rather than one per pixel write. */
            if ((pair & 255u) == 0u && ln_time_us() - started >= LINNET_LCD_FRAME_TIMEOUT_US) {
                LINNET_LCD_RECORD(1, 1u);
                goto failed;
            }
            if (!ln_lcd_wait(&LINNET_LCD_CONTROL, 0x01000000u, true, started, &budget)) goto failed;
            if(fault_rows){
                uint32_t pixel=pairs_written*2u;
                uint32_t row=pixel/LINNET_LCD_WIDTH,x=pixel%LINNET_LCD_WIDTH;
                uint16_t a=ln_fault_pixel(fault_rows,x,row);
                uint16_t b=ln_fault_pixel(fault_rows,x+1u,row);
                pixel_pair=(uint32_t)(uint16_t)((a<<8)|(a>>8)) |
                    ((uint32_t)(uint16_t)((b<<8)|(b>>8))<<16);
            }
            LINNET_LCD_DATA = pixel_pair;
            ++pairs_written;
        }
        LINNET_LCD_RECORD(0, 6u | ((rows_left == LINNET_LCD_HEIGHT ? 1u : 2u) << 8));
        if (!ln_lcd_wait(&LINNET_LCD_CONTROL, 0x04000000u, true, started, &budget)) goto failed;
        if (ln_time_us() - started >= LINNET_LCD_FRAME_TIMEOUT_US) {
            LINNET_LCD_RECORD(1, 1u);
            goto failed;
        }
        LINNET_LCD_CONFIG = 0;
        rows_left -= rows;
    }
    LINNET_LCD_RECORD(0, 7u);
    ln_lcd_record_end(started, budget, pairs_written);
    return true;
failed:
    ln_lcd_record_end(started, budget, pairs_written);
    LINNET_LCD_CONFIG = 0;
    ln_panel_ready = false;
    return false;
}

bool ln_lcd_fill(uint16_t color){return ln_lcd_draw(color,0);}
bool ln_lcd_fault(uint32_t reason,const uint8_t build_id[32])
{
    static const char hex[]="0123456789ABCDEF";
    char lines[8][33]={"LINNET STOPPED","CODE 00000000","BUILD 0000000000000000",
        "RESTARTING AUTOMATICALLY","IF THIS REPEATS:","HOLD MENU + CENTER TO RESTART",
        "THEN CENTER + PLAY FOR","DISK MODE AND CONNECT USB"};
    for(uint32_t i=0;i<8u;i++)lines[1][5u+i]=hex[(reason>>(28u-i*4u))&15u];
    for(uint32_t i=0;i<8u;i++){lines[2][6u+i*2u]=hex[build_id[i]>>4];lines[2][7u+i*2u]=hex[build_id[i]&15u];}
    return ln_lcd_draw(0x1800u,lines);
}

void ln_platform_quiesce(void)
{
    LINNET_REG(0x60004028u) = UINT32_MAX;
    LINNET_REG(0x60004128u) = UINT32_MAX;
    LINNET_REG(0x60004038u) = UINT32_MAX;
    LINNET_REG(0x60004138u) = UINT32_MAX;
    LINNET_REG(0x6000a008u) = 0;
    for (uint32_t channel = 0; channel < 4u; ++channel)
        LINNET_REG(0x6000b000u + channel * 32u) &= ~0xc0000000u;
}

bool ln_platform_dma_idle(void)
{
    uint32_t started = ln_time_us(), budget = 100000u;
    for (uint32_t channel = 0; channel < 4u; ++channel) {
        if (!ln_wait(&LINNET_REG(0x6000b004u + channel * 32u), 0x80000000u,
                     false, started, 100000u, &budget)) return false;
    }
    LINNET_REG(0x6000a000u) &= ~0x80000000u;
    return true;
}

#define LINNET_REG8(a) (*(volatile uint8_t *)(uintptr_t)(a))
static bool ln_codec_idle(void)
{
    uint32_t started = ln_time_us();
    for (uint32_t i = 0; i < 100000u; ++i) {
        if (!(LINNET_REG8(0x7000c01cu) & 0x40u)) return true;
        if (ln_time_us() - started >= 5000u) break;
    }
    return false;
}

static bool ln_codec_write(uint8_t reg, uint16_t value)
{
    if (!ln_codec_idle()) return false;
    LINNET_REG8(0x7000c004u) = 0x34u; /* WM8975 7-bit address 0x1a. */
    LINNET_REG8(0x7000c00cu) = (uint8_t)((reg << 1) | ((value >> 8) & 1u));
    LINNET_REG8(0x7000c010u) = (uint8_t)value;
    LINNET_REG8(0x7000c000u) = (uint8_t)((LINNET_REG8(0x7000c000u) & ~0x26u) | 2u);
    LINNET_REG8(0x7000c000u) |= 0x80u;
    return ln_codec_idle();
}

bool ln_platform_audio_idle(void)
{
    if (!ln_platform_dma_idle()) return false;
    /* Hold I2S device in reset so inherited FIFO contents cannot be clocked. */
    LINNET_REG(0x60006004u) |= 0x800u;
    LINNET_REG(0x6000600cu) &= ~0x800u;
    LINNET_REG(0x6000600cu) |= 0x1000u;
    LINNET_REG(0x60006004u) |= 0x1000u;
    __asm__ volatile("nop\n\tnop\n\tnop" ::: "memory");
    LINNET_REG(0x60006004u) &= ~0x1000u;
    LINNET_REG(0x600060a4u) = 0;
    LINNET_REG(0x600060a4u) = 0x80u;
    /* WM8975 software reset, DAC soft mute, both analog power domains off.
     * PP5020 exposes transaction completion; WM8975 writes have no readback. */
    return ln_codec_write(0x0fu, 0) && ln_codec_write(0x05u, 8u) &&
        ln_codec_write(0x1au, 0) && ln_codec_write(0x19u, 0);
}

/* Cooperative progress detector only; independent reset watchdog unqualified. */
void ln_watchdog_feed(void) { ln_last_progress = ln_time_us(); }
bool ln_watchdog_expired(void) { return ln_time_us() - ln_last_progress >= 500000u; }
