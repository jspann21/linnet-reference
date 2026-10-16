/* Host execution experiment: reject an incompatible target structure ABI. */
#include <stddef.h>
#include "services/audio/aac/aac.h"
_Static_assert(sizeof(void *)==4,"ARM pointer ABI");
_Static_assert(sizeof(struct ln_aac)==110672,"decoder extent");
_Static_assert(offsetof(struct ln_aac,input)==98304,"packet offset");
_Static_assert(offsetof(struct ln_aac,pcm)==106496,"PCM offset");
_Static_assert(offsetof(struct ln_aac,pcm_cursor)==110648,"cursor offset");
