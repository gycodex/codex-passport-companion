#include "buddy_adpcm.h"
#include <assert.h>
#include <string.h>

int main(void)
{
    /* Standard IMA reference vector (low nibble first on this wire). */
    const uint8_t encoded[] = {0x77, 0xff, 0x21, 0x43};
    const int16_t expected[] = {11, 41, -22, -158, -100, -12, 101, 233};
    int16_t decoded[8];
    uint8_t roundtrip[4];
    buddy_adpcm_state_t state = {0};
    buddy_adpcm_decode(&state, encoded, sizeof(encoded), decoded);
    assert(memcmp(decoded, expected, sizeof(expected)) == 0);
    state = (buddy_adpcm_state_t){0};
    buddy_adpcm_encode(&state, expected, 8, roundtrip);
    assert(memcmp(roundtrip, encoded, sizeof(encoded)) == 0);
    /* Extremes remain saturated, and the step index never escapes its table. */
    for (unsigned i = 0; i < 1000; ++i) {
        const int16_t extremes[2] = {-32768, 32767};
        buddy_adpcm_encode(&state, extremes, 2, roundtrip);
        assert(state.step_index >= 0 && state.step_index <= 88);
    }
    return 0;
}
