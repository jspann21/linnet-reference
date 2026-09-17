#ifndef LINNET_PP5020_TARGET_H
#define LINNET_PP5020_TARGET_H
#include <stdbool.h>
#include <stdint.h>

/* Small board-policy surface implemented by each target. */
bool ln_target_battery_charging(void);

void ln_target_input_prepare(void);

/* A target may fill older IDENTIFY fields that predate the ATA media/rotation
 * words.  Implementations must match an exact device identity and leave
 * unrecognized devices unchanged. */
void ln_target_ata_classify(const char *model,uint32_t *media_kind,uint32_t *rotation_rpm);

#endif
