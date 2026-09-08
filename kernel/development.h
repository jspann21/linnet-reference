#ifndef LINNET_DEVELOPMENT_H
#define LINNET_DEVELOPMENT_H
#include <stdint.h>
int ln_development_init(void);
void ln_development_health(uint32_t flags);
void ln_development_poll(void);
#endif
