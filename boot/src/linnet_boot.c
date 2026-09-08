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

uint32_t ln_crc32_progress(const uint8_t *bytes, size_t length,
    void (*progress)(void *context), void *context)
{
    /* Host-generated reflected ISO-HDLC byte table. One lookup per byte;
     * complete coverage and the existing 4096-byte progress boundary remain. */
    static const uint32_t byte_table[256] = {
        0x00000000u, 0x77073096u, 0xee0e612cu, 0x990951bau, 0x076dc419u, 0x706af48fu, 0xe963a535u, 0x9e6495a3u,
        0x0edb8832u, 0x79dcb8a4u, 0xe0d5e91eu, 0x97d2d988u, 0x09b64c2bu, 0x7eb17cbdu, 0xe7b82d07u, 0x90bf1d91u,
        0x1db71064u, 0x6ab020f2u, 0xf3b97148u, 0x84be41deu, 0x1adad47du, 0x6ddde4ebu, 0xf4d4b551u, 0x83d385c7u,
        0x136c9856u, 0x646ba8c0u, 0xfd62f97au, 0x8a65c9ecu, 0x14015c4fu, 0x63066cd9u, 0xfa0f3d63u, 0x8d080df5u,
        0x3b6e20c8u, 0x4c69105eu, 0xd56041e4u, 0xa2677172u, 0x3c03e4d1u, 0x4b04d447u, 0xd20d85fdu, 0xa50ab56bu,
        0x35b5a8fau, 0x42b2986cu, 0xdbbbc9d6u, 0xacbcf940u, 0x32d86ce3u, 0x45df5c75u, 0xdcd60dcfu, 0xabd13d59u,
        0x26d930acu, 0x51de003au, 0xc8d75180u, 0xbfd06116u, 0x21b4f4b5u, 0x56b3c423u, 0xcfba9599u, 0xb8bda50fu,
        0x2802b89eu, 0x5f058808u, 0xc60cd9b2u, 0xb10be924u, 0x2f6f7c87u, 0x58684c11u, 0xc1611dabu, 0xb6662d3du,
        0x76dc4190u, 0x01db7106u, 0x98d220bcu, 0xefd5102au, 0x71b18589u, 0x06b6b51fu, 0x9fbfe4a5u, 0xe8b8d433u,
        0x7807c9a2u, 0x0f00f934u, 0x9609a88eu, 0xe10e9818u, 0x7f6a0dbbu, 0x086d3d2du, 0x91646c97u, 0xe6635c01u,
        0x6b6b51f4u, 0x1c6c6162u, 0x856530d8u, 0xf262004eu, 0x6c0695edu, 0x1b01a57bu, 0x8208f4c1u, 0xf50fc457u,
        0x65b0d9c6u, 0x12b7e950u, 0x8bbeb8eau, 0xfcb9887cu, 0x62dd1ddfu, 0x15da2d49u, 0x8cd37cf3u, 0xfbd44c65u,
        0x4db26158u, 0x3ab551ceu, 0xa3bc0074u, 0xd4bb30e2u, 0x4adfa541u, 0x3dd895d7u, 0xa4d1c46du, 0xd3d6f4fbu,
        0x4369e96au, 0x346ed9fcu, 0xad678846u, 0xda60b8d0u, 0x44042d73u, 0x33031de5u, 0xaa0a4c5fu, 0xdd0d7cc9u,
        0x5005713cu, 0x270241aau, 0xbe0b1010u, 0xc90c2086u, 0x5768b525u, 0x206f85b3u, 0xb966d409u, 0xce61e49fu,
        0x5edef90eu, 0x29d9c998u, 0xb0d09822u, 0xc7d7a8b4u, 0x59b33d17u, 0x2eb40d81u, 0xb7bd5c3bu, 0xc0ba6cadu,
        0xedb88320u, 0x9abfb3b6u, 0x03b6e20cu, 0x74b1d29au, 0xead54739u, 0x9dd277afu, 0x04db2615u, 0x73dc1683u,
        0xe3630b12u, 0x94643b84u, 0x0d6d6a3eu, 0x7a6a5aa8u, 0xe40ecf0bu, 0x9309ff9du, 0x0a00ae27u, 0x7d079eb1u,
        0xf00f9344u, 0x8708a3d2u, 0x1e01f268u, 0x6906c2feu, 0xf762575du, 0x806567cbu, 0x196c3671u, 0x6e6b06e7u,
        0xfed41b76u, 0x89d32be0u, 0x10da7a5au, 0x67dd4accu, 0xf9b9df6fu, 0x8ebeeff9u, 0x17b7be43u, 0x60b08ed5u,
        0xd6d6a3e8u, 0xa1d1937eu, 0x38d8c2c4u, 0x4fdff252u, 0xd1bb67f1u, 0xa6bc5767u, 0x3fb506ddu, 0x48b2364bu,
        0xd80d2bdau, 0xaf0a1b4cu, 0x36034af6u, 0x41047a60u, 0xdf60efc3u, 0xa867df55u, 0x316e8eefu, 0x4669be79u,
        0xcb61b38cu, 0xbc66831au, 0x256fd2a0u, 0x5268e236u, 0xcc0c7795u, 0xbb0b4703u, 0x220216b9u, 0x5505262fu,
        0xc5ba3bbeu, 0xb2bd0b28u, 0x2bb45a92u, 0x5cb36a04u, 0xc2d7ffa7u, 0xb5d0cf31u, 0x2cd99e8bu, 0x5bdeae1du,
        0x9b64c2b0u, 0xec63f226u, 0x756aa39cu, 0x026d930au, 0x9c0906a9u, 0xeb0e363fu, 0x72076785u, 0x05005713u,
        0x95bf4a82u, 0xe2b87a14u, 0x7bb12baeu, 0x0cb61b38u, 0x92d28e9bu, 0xe5d5be0du, 0x7cdcefb7u, 0x0bdbdf21u,
        0x86d3d2d4u, 0xf1d4e242u, 0x68ddb3f8u, 0x1fda836eu, 0x81be16cdu, 0xf6b9265bu, 0x6fb077e1u, 0x18b74777u,
        0x88085ae6u, 0xff0f6a70u, 0x66063bcau, 0x11010b5cu, 0x8f659effu, 0xf862ae69u, 0x616bffd3u, 0x166ccf45u,
        0xa00ae278u, 0xd70dd2eeu, 0x4e048354u, 0x3903b3c2u, 0xa7672661u, 0xd06016f7u, 0x4969474du, 0x3e6e77dbu,
        0xaed16a4au, 0xd9d65adcu, 0x40df0b66u, 0x37d83bf0u, 0xa9bcae53u, 0xdebb9ec5u, 0x47b2cf7fu, 0x30b5ffe9u,
        0xbdbdf21cu, 0xcabac28au, 0x53b39330u, 0x24b4a3a6u, 0xbad03605u, 0xcdd70693u, 0x54de5729u, 0x23d967bfu,
        0xb3667a2eu, 0xc4614ab8u, 0x5d681b02u, 0x2a6f2b94u, 0xb40bbe37u, 0xc30c8ea1u, 0x5a05df1bu, 0x2d02ef8du
    };
    uint32_t crc = UINT32_MAX;
    size_t i=0;
    for (; length-i >= 8u; i+=8u) {
        crc = (crc >> 8) ^ byte_table[(crc ^ bytes[i]) & 255u];
        crc = (crc >> 8) ^ byte_table[(crc ^ bytes[i+1u]) & 255u];
        crc = (crc >> 8) ^ byte_table[(crc ^ bytes[i+2u]) & 255u];
        crc = (crc >> 8) ^ byte_table[(crc ^ bytes[i+3u]) & 255u];
        crc = (crc >> 8) ^ byte_table[(crc ^ bytes[i+4u]) & 255u];
        crc = (crc >> 8) ^ byte_table[(crc ^ bytes[i+5u]) & 255u];
        crc = (crc >> 8) ^ byte_table[(crc ^ bytes[i+6u]) & 255u];
        crc = (crc >> 8) ^ byte_table[(crc ^ bytes[i+7u]) & 255u];
        if (progress && (i & 4095u) == 4088u) progress(context);
    }
    for (; i<length; ++i)
        crc = (crc >> 8) ^ byte_table[(crc ^ bytes[i]) & 255u];
    return crc ^ UINT32_MAX;
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
    if (image[0] != 'L' || image[1] != 'O' || image[2] != 'S' || image[3] != '1' ||
        read16(image + 4) != 1 || read16(image + 6) != LINNET_IMAGE_HEADER_SIZE ||
        !zeroes(image + 68, 56)) return LINNET_IMAGE_FORMAT;
    if (ln_crc32(image, 124) != read32(image + 124)) return LINNET_IMAGE_CHECKSUM;
    if (read32(image + 8) != policy->target) return LINNET_IMAGE_TARGET;
    if (read32(image + 12) != policy->abi) return LINNET_IMAGE_ABI;
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
    if (read32(bytes) != UINT32_C(0x3153424c) || read32(bytes + 4) != 1 ||
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
    write32(bytes, UINT32_C(0x3153424c));
    write32(bytes + 4, 1);
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
    write32(bytes, UINT32_C(0x3143524c));
    bytes[4] = 1;
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
    if (read32(bytes) != UINT32_C(0x3143524c) || read16(bytes + 4) != 1 ||
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
