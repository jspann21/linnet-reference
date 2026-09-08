#ifndef LINNET_NATIVE_UPDATE_H
#define LINNET_NATIVE_UPDATE_H
#include <stdint.h>
#define LINNET_NATIVE_PACKAGE_BYTES (2560u+131072u)
int ln_native_begin(uint32_t length,const uint8_t sha[32]);
int ln_native_write(uint32_t offset,const uint8_t *data,uint32_t length);
int ln_native_apply(void);
void ln_native_status(uint32_t words[16]);
#endif
