#include "linnet_boot.h"

static uint32_t read32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
        ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint16_t read16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static void write32(uint8_t *p, uint32_t value)
{
    unsigned i;
    for (i = 0; i < 4; ++i) p[i] = (uint8_t)(value >> (8u * i));
}

static int zeroes(const uint8_t *p, size_t length)
{
    size_t i;
    for (i = 0; i < length; ++i) if (p[i] != 0) return 0;
    return 1;
}

#define LN_CRC_ATTR
#define LN_CRC_TABLE_ATTR
#define LN_CRC_NAME crc32_sdram
#include "crc32.inc"
#undef LN_CRC_ATTR
#undef LN_CRC_TABLE_ATTR
#undef LN_CRC_NAME
#if defined(LINNET_IMAGE_BOOT) && defined(LINNET_PLATFORM_CORE) && defined(LINNET_STORAGE)
#include "sha256.h"
#define LN_CRC_ATTR __attribute__((section(".boot_hash.text"),noinline))
#define LN_CRC_TABLE_ATTR __attribute__((section(".boot_hash.rodata"),aligned(4)))
#define LN_CRC_NAME crc32_iram
#include "crc32.inc"
#undef LN_CRC_ATTR
#undef LN_CRC_TABLE_ATTR
#undef LN_CRC_NAME
#endif

uint32_t ln_crc32_progress(const uint8_t *bytes, size_t length,
    void (*progress)(void *context), void *context)
{
#if defined(LINNET_IMAGE_BOOT) && defined(LINNET_PLATFORM_CORE) && defined(LINNET_STORAGE)
    if (ln_sha256_boot_iram_active()) return crc32_iram(bytes,length,progress,context);
#endif
    return crc32_sdram(bytes,length,progress,context);
}

uint32_t ln_crc32(const uint8_t *bytes, size_t length)
{
    return ln_crc32_progress(bytes, length, NULL, NULL);
}

enum ln_image_result ln_image_validate_progress(const uint8_t *image, size_t length,
    const struct ln_image_policy *policy, struct ln_image_info *info,
    void (*progress)(void *context), void *context)
{
    uint32_t profile, payload, load, entry, offset;
    unsigned i;
    if (!image || !policy || !info) return LINNET_IMAGE_ARGUMENT;
    if (length < LINNET_IMAGE_HEADER_SIZE) return LINNET_IMAGE_TRUNCATED;
    if (image[0] != 'L' || image[1] != 'N' || image[2] != 'O' || image[3] != 'S' ||
        read16(image + 4) != 0 || read16(image + 6) != LINNET_IMAGE_HEADER_SIZE ||
        read32(image + 12) != 0 ||
        !zeroes(image + 68, 56)) return LINNET_IMAGE_FORMAT;
    if (ln_crc32(image, 124) != read32(image + 124)) return LINNET_IMAGE_CHECKSUM;
    if (read32(image + 8) != policy->target) return LINNET_IMAGE_TARGET;
    profile = read32(image + 16);
    if (profile > 2 || (policy->allowed_profiles & (1u << profile)) == 0)
        return LINNET_IMAGE_PROFILE;
    payload = read32(image + 20);
    load = read32(image + 24);
    entry = read32(image + 28);
    if (length - LINNET_IMAGE_HEADER_SIZE != payload) return LINNET_IMAGE_TRUNCATED;
    if (payload < 4 || policy->ram_size == 0 ||
        policy->ram_size - 1u > UINT32_MAX - policy->ram_start ||
        load < policy->ram_start || (load & 3u) != 0 || (entry & 3u) != 0)
        return LINNET_IMAGE_RANGE;
    offset = load - policy->ram_start;
    if (offset >= policy->ram_size || payload > policy->ram_size - offset ||
        entry < load || entry - load > payload - 4u) return LINNET_IMAGE_RANGE;
    if (ln_crc32_progress(image + LINNET_IMAGE_HEADER_SIZE, payload, progress, context) != read32(image + 32))
        return LINNET_IMAGE_CHECKSUM;
    info->profile = profile;
    info->payload_size = payload;
    info->load_address = load;
    info->entry_address = entry;
    for (i = 0; i < 32; ++i) info->build_id[i] = image[36 + i];
    return LINNET_IMAGE_OK;
}

enum ln_image_result ln_image_validate(const uint8_t *image, size_t length,
    const struct ln_image_policy *policy, struct ln_image_info *info)
{
    return ln_image_validate_progress(image, length, policy, info, NULL, NULL);
}

static int state_valid(const struct ln_boot_state *state)
{
    return state && (state->confirmed_slot <= 1 || state->confirmed_slot == LINNET_BOOT_NO_SLOT) &&
        (state->candidate_slot <= 1 || state->candidate_slot == LINNET_BOOT_NO_SLOT) &&
        (state->candidate_slot == LINNET_BOOT_NO_SLOT || state->candidate_slot != state->confirmed_slot) &&
        state->attempt_pending <= 1 && (!state->attempt_pending || state->candidate_slot <= 1);
}

void ln_boot_state_init(struct ln_boot_state *state, uint8_t confirmed_slot)
{
    if (!state) return;
    state->generation = 0;
    state->attempts = 0;
    state->confirmed_slot = confirmed_slot <= 1 ? confirmed_slot : LINNET_BOOT_NO_SLOT;
    state->candidate_slot = LINNET_BOOT_NO_SLOT;
    state->attempt_pending = 0;
}

int ln_boot_state_decode(struct ln_boot_state *state, const uint8_t *bytes, size_t length)
{
    struct ln_boot_state result;
    if (!state || !bytes || length != LINNET_BOOT_STATE_SIZE) return 0;
    if (read32(bytes) != UINT32_C(0x544f4f42) || read32(bytes + 4) != 0 ||
        !zeroes(bytes + 19, 9) || ln_crc32(bytes, 28) != read32(bytes + 28)) return 0;
    result.generation = read32(bytes + 8);
    result.attempts = read32(bytes + 12);
    result.confirmed_slot = bytes[16];
    result.candidate_slot = bytes[17];
    result.attempt_pending = bytes[18];
    if (!state_valid(&result)) return 0;
    *state = result;
    return 1;
}

int ln_boot_state_encode(const struct ln_boot_state *state, uint8_t *bytes, size_t length)
{
    unsigned i;
    if (!state_valid(state) || !bytes || length != LINNET_BOOT_STATE_SIZE) return 0;
    for (i = 0; i < LINNET_BOOT_STATE_SIZE; ++i) bytes[i] = 0;
    write32(bytes, UINT32_C(0x544f4f42));
    write32(bytes + 4, 0);
    write32(bytes + 8, state->generation);
    write32(bytes + 12, state->attempts);
    bytes[16] = state->confirmed_slot;
    bytes[17] = state->candidate_slot;
    bytes[18] = state->attempt_pending;
    write32(bytes + 28, ln_crc32(bytes, 28));
    return 1;
}

int ln_boot_after_reset(struct ln_boot_state *state)
{
    if (!state_valid(state)) return 0;
    if (state->attempt_pending) {
        state->candidate_slot = LINNET_BOOT_NO_SLOT;
        state->attempt_pending = 0;
        ++state->generation;
    }
    return 1;
}

int ln_boot_offer_candidate(struct ln_boot_state *state, uint8_t slot)
{
    if (!state_valid(state) || slot > 1 || slot == state->confirmed_slot ||
        state->attempt_pending) return 0;
    state->candidate_slot = slot;
    ++state->generation;
    return 1;
}

uint8_t ln_boot_select(const struct ln_boot_state *state, uint8_t valid_slots)
{
    if (!state_valid(state) || state->attempt_pending) return LINNET_BOOT_NO_SLOT;
    if (state->candidate_slot <= 1 && (valid_slots & (1u << state->candidate_slot)))
        return state->candidate_slot;
    if (state->confirmed_slot <= 1 && (valid_slots & (1u << state->confirmed_slot)))
        return state->confirmed_slot;
    return LINNET_BOOT_NO_SLOT;
}

int ln_boot_begin_attempt(struct ln_boot_state *state, uint8_t selected_slot)
{
    if (!state_valid(state) || selected_slot > 1 || state->attempt_pending ||
        (selected_slot != state->candidate_slot && selected_slot != state->confirmed_slot)) return 0;
    if (state->attempts != UINT32_MAX) ++state->attempts;
    state->attempt_pending = (uint8_t)(selected_slot == state->candidate_slot);
    ++state->generation;
    return 1;
}

int ln_boot_mark_healthy(struct ln_boot_state *state, uint8_t running_slot, uint32_t readiness)
{
    if (!state_valid(state) || running_slot > 1 ||
        (readiness & LINNET_BOOT_HEALTH_ALL) != LINNET_BOOT_HEALTH_ALL) return 0;
    if (state->attempt_pending && running_slot == state->candidate_slot) {
        state->confirmed_slot = running_slot;
        state->candidate_slot = LINNET_BOOT_NO_SLOT;
        state->attempt_pending = 0;
        ++state->generation;
        return 1;
    }
    return !state->attempt_pending && running_slot == state->confirmed_slot;
}

int ln_crash_encode(const struct ln_crash_record *record, uint8_t *bytes, size_t length)
{
    unsigned i;
    if (!record || !bytes || length != LINNET_CRASH_MAILBOX_SIZE) return 0;
    for (i = 0; i < LINNET_CRASH_MAILBOX_SIZE; ++i) bytes[i] = 0;
    write32(bytes, UINT32_C(0x48535243));
    bytes[4] = 0;
    bytes[6] = LINNET_CRASH_MAILBOX_SIZE;
    write32(bytes + 8, record->sequence);
    write32(bytes + 12, record->reason);
    for (i = 0; i < 16; ++i) write32(bytes + 16 + i * 4, record->registers[i]);
    write32(bytes + 80, record->cpsr);
    write32(bytes + 84, record->flags);
    for (i = 0; i < 32; ++i) bytes[88 + i] = record->build_id[i];
    write32(bytes + 120, record->boot_generation);
    write32(bytes + 124, record->active_service);
    write32(bytes + 128, record->last_event);
    write32(bytes + 140, ln_crc32(bytes, 140));
    return 1;
}

int ln_crash_decode(struct ln_crash_record *record, const uint8_t *bytes, size_t length)
{
    unsigned i;
    if (!record || !bytes || length != LINNET_CRASH_MAILBOX_SIZE) return 0;
    if (read32(bytes) != UINT32_C(0x48535243) || read16(bytes + 4) != 0 ||
        read16(bytes + 6) != LINNET_CRASH_MAILBOX_SIZE || !zeroes(bytes + 132, 8) ||
        ln_crc32(bytes, 140) != read32(bytes + 140)) return 0;
    record->sequence = read32(bytes + 8);
    record->reason = read32(bytes + 12);
    for (i = 0; i < 16; ++i) record->registers[i] = read32(bytes + 16 + i * 4);
    record->cpsr = read32(bytes + 80);
    record->flags = read32(bytes + 84);
    for (i = 0; i < 32; ++i) record->build_id[i] = bytes[88 + i];
    record->boot_generation = read32(bytes + 120);
    record->active_service = read32(bytes + 124);
    record->last_event = read32(bytes + 128);
    return 1;
}
