/* Adapted from https://github.com/xiabill/ai-passport (MIT).
 * Copyright (c) 2026 FoloToy; see third_party/xiabill-ai-passport-LICENSE. */
#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// IMA ADPCM (DVI4) 4-bit encoder/decoder. CPU cost is negligible on ESP32-C3.
typedef struct {
    int16_t predictor;
    int8_t step_index;
} buddy_adpcm_state_t;

// Encodes `count` samples (`count` must be even) into count/2 bytes.
// Snapshot `state` *before* the call; that snapshot is the audio packet header.
void buddy_adpcm_encode(buddy_adpcm_state_t *state, const int16_t *pcm, int count,
                       uint8_t *out);

// Decodes `nbytes` ADPCM bytes into nbytes*2 PCM samples. Used by host tests
// and kept next to the encoder so both sides share one step table.
void buddy_adpcm_decode(buddy_adpcm_state_t *state, const uint8_t *in, int nbytes,
                       int16_t *pcm);

#ifdef __cplusplus
}
#endif
