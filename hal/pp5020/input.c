#include "hal/pp5020/input.h"
#include "hal/pp5020/core.h"
#include "hal/pp5020/platform.h"
#define LINNET_MMIO(a) (*(volatile uint32_t *)(uintptr_t)(a))
static struct ln_input_state ln_input;
static int32_t ln_last_wheel = -1;
static bool ln_input_ready;

static void ln_switch_rearm(uint32_t sample)
{
    /* Level interrupt armed opposite the current state catches either edge. */
    LINNET_MMIO(0x6000d060u) = (LINNET_MMIO(0x6000d060u) & ~0xa0u) | (~sample & 0xa0u);
    LINNET_MMIO(0x6000d070u) = 0xa0u;
    LINNET_MMIO(0x6000d050u) |= 0xa0u;
}
bool ln_input_init(void)
{
    LINNET_MMIO(0x6000600cu) |= 0x10000u;
    LINNET_MMIO(0x60006004u) |= 0x10000u;
    if (!ln_core_delay_us(5u)) return false;
    LINNET_MMIO(0x60006004u) &= ~0x10000u;
    LINNET_MMIO(0x70000010u) |= 0x40000u;
    LINNET_MMIO(0x7000c100u) = 0xc00a1f00u;
    LINNET_MMIO(0x7000c104u) = 0x01000000u;
    LINNET_MMIO(0x7000c100u) &= ~0x60000000u;
    LINNET_MMIO(0x7000c104u) |= 0x04000000u;
    LINNET_MMIO(0x7000c100u) |= 0x60000000u;
    LINNET_MMIO(0x6000d000u) |= 0xa0u;
    LINNET_MMIO(0x6000d010u) &= ~0xa0u;
    uint32_t pins = LINNET_MMIO(0x6000d030u);
    ln_input.hold = !(pins & 0x20u);
    ln_input.headphones = (pins & 0x80u) != 0;
    ln_input.buttons = 0;
    ln_input.touched = 0;
    ln_input.wheel_delta = 0;
    ln_input.timestamp_us = ln_time_us();
    ln_last_wheel = -1;
    ln_switch_rearm(pins);
    ln_input_ready = true;
    ln_core_input_rearm();
    return true;
}
bool ln_input_poll(struct ln_input_state *out)
{
    if (!ln_input_ready || !out) return false;
    struct ln_input_state next = ln_input;
    next.wheel_delta = 0;
    uint32_t pins = LINNET_MMIO(0x6000d030u);
    next.hold = !(pins & 0x20u);
    next.headphones = (pins & 0x80u) != 0;
    if (LINNET_MMIO(0x7000c104u) & 0x04000000u) {
        /* The established Photo handler gives the optical bus 50 us settle. */
        if (!ln_core_delay_us(50u)) return false;
        uint32_t packet = LINNET_MMIO(0x7000c140u);
        if ((packet & 0x800000ffu) == 0x8000001au &&
            (!(packet & 0x40000000u) || ((packet >> 16) & 0x7fu) < 96u)) {
            ++next.packets;
            next.buttons = (packet >> 8) & 31u;
            next.touched = (packet & 0x40000000u) != 0;
            next.wheel_position = (uint8_t)((packet >> 16) & 0x7fu);
            if (next.touched && ln_last_wheel >= 0) {
                int32_t delta = (int32_t)next.wheel_position - ln_last_wheel;
                if (delta > 48) delta -= 96;
                if (delta < -48) delta += 96;
                next.wheel_delta = delta;
            }
            ln_last_wheel = next.touched ? next.wheel_position : -1;
        } else if ((packet & 0x800000ffu) != 0x8000003au && packet != UINT32_MAX) {
            ++next.invalid_packets;
            next.buttons = 0;
            next.touched = 0;
            ln_last_wheel = -1;
        }
        LINNET_MMIO(0x7000c104u) |= 0x0c000000u;
        LINNET_MMIO(0x7000c100u) = 0x400a1f00u;
    }
    if (next.hold || next.hold != ln_input.hold) {
        next.buttons = 0;
        next.wheel_delta = 0;
        next.touched = 0;
        ln_last_wheel = -1;
    }
    bool changed = next.buttons != ln_input.buttons || next.wheel_delta ||
        next.touched != ln_input.touched || next.hold != ln_input.hold ||
        next.headphones != ln_input.headphones;
    next.timestamp_us = ln_time_us();
    ln_input = next;
    *out = next;
    ln_switch_rearm(pins);
    ln_core_input_rearm();
    return changed;
}
void ln_input_snapshot(struct ln_input_state *out) { if (out) *out = ln_input; }
