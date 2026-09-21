#ifndef LINNET_M25_COPROCESSOR_H
#define LINNET_M25_COPROCESSOR_H
#include <stdbool.h>
#include <stdint.h>
/* Development qualification of the vendor media runtime. Automatic rollback
 * uses a bounds- and checksum-verified image in the device's own NOR. */
bool ln_m25_coprocessor_begin(uint32_t operation);
bool ln_m25_coprocessor_control(uint32_t command);
#if !defined(LINNET_PROFILE_RELEASE)
bool ln_m25_coprocessor_fault(uint32_t mode);
#endif
bool ln_m25_coprocessor_owned(void);
bool ln_m25_coprocessor_step(void);
uint32_t ln_m25_coprocessor_snapshot(uint32_t output[32]);
uint32_t ln_m25_coprocessor_channel(uint32_t slot,uint32_t output[32]);
bool ln_m25_coprocessor_open(const char *path,uint8_t options);
bool ln_m25_coprocessor_active(void);
void ln_m25_coprocessor_stop(void);
void ln_m25_coprocessor_pause(bool paused);
bool ln_m25_coprocessor_paused(void);
bool ln_m25_coprocessor_seek(uint32_t ms);
uint32_t ln_m25_coprocessor_position(void);
uint32_t ln_m25_coprocessor_duration(void);
uint32_t ln_m25_coprocessor_revision(void);
uint32_t ln_m25_coprocessor_error(void);
#endif
