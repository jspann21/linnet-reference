#pragma once
#include <stdbool.h>
#include <stdint.h>
/* Controller handshake; offsets are ATA taskfile register offsets. */
bool ln_s5l_ata_read(unsigned offset,uint16_t *value);
bool ln_s5l_ata_write(unsigned offset,uint16_t value);
