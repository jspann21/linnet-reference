#ifndef LINNET_HAL_INPUT_H
#define LINNET_HAL_INPUT_H
#include <stdbool.h>
#include <stdint.h>
#define LINNET_BUTTON_SELECT 1u
#define LINNET_BUTTON_RIGHT 2u
#define LINNET_BUTTON_LEFT 4u
#define LINNET_BUTTON_PLAY 8u
#define LINNET_BUTTON_MENU 16u
struct ln_input_state {
    uint32_t buttons, timestamp_us, packets, invalid_packets;
    int32_t wheel_delta;
    uint8_t wheel_position, touched, hold, headphones;
};
bool ln_input_init(void);
bool ln_input_poll(struct ln_input_state *out);
void ln_input_snapshot(struct ln_input_state *out);
#if defined(LINNET_IMAGE_OS) && defined(LINNET_TARGET_CLASSIC6G_N25)
bool ln_input_irq(void);
#endif
#if !defined(LINNET_PROFILE_RELEASE)
void ln_input_diagnostics(uint32_t output[16]);
#endif
#endif
