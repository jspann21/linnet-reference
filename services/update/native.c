/* Targets without an audited firmware-partition writer reject maintenance.
 * Ordinary A/B OS updates remain portable in update.c. */
#include "services/update/native.h"
int ln_native_begin(uint32_t length,const uint8_t sha[32]){(void)length;(void)sha;return 0;}
int ln_native_write(uint32_t offset,const uint8_t *data,uint32_t length){(void)offset;(void)data;(void)length;return 0;}
int ln_native_apply(void){return 0;}
void ln_native_status(uint32_t words[16]){for(unsigned i=0;i<16;++i)words[i]=0;words[0]=0x32424e4cu;words[1]=11;words[2]=12;}
