#include <assert.h>
#include <string.h>
#include "buddy_voice.h"
static int64_t now = 1;
int64_t esp_timer_get_time(void) { return now; }
/* Only framing/capacity is exercised here; codec has its own reference tests. */
int mbedtls_base64_encode(unsigned char *out, size_t cap, size_t *written,
                         const unsigned char *in, size_t size)
{
    (void)in;
    *written = 4 * ((size + 2) / 3);
    if (*written > cap) return -1;
    memset(out, 'A', *written);
    return 0;
}
int main(void)
{
    char reply[2048];
    buddy_voice_poll(reply, sizeof(reply));
    assert(buddy_voice_toggle());
    now += 3000000;
    assert(buddy_voice_recording());
    buddy_voice_poll(reply, sizeof(reply));
    now += 4999999;
    assert(buddy_voice_recording());
    ++now;
    assert(!buddy_voice_recording());
    buddy_voice_poll(reply, sizeof(reply));
    assert(strstr(reply, "\"stop_reason\":2"));
    assert(buddy_voice_toggle());
    int16_t pcm[BUDDY_VOICE_SAMPLES];
    for (unsigned i = 0; i < BUDDY_VOICE_SAMPLES; ++i) pcm[i] = 32767;
    for (unsigned i = 0; i < 8; ++i) buddy_voice_capture(pcm);
    size_t size = buddy_voice_poll(reply, sizeof(reply));
    assert(size > 1700 && size < sizeof(reply));
    assert(strstr(reply, "\"clipped\":2560"));
    assert(strstr(reply, "\"samples\":2560"));
    assert(!buddy_voice_toggle());
    buddy_voice_poll(reply, sizeof(reply));
    assert(strstr(reply, "\"stop_reason\":1"));
    now += 2000000;
    assert(!buddy_voice_toggle());
    buddy_voice_poll(reply, sizeof(reply));
    assert(buddy_voice_toggle());
    buddy_voice_disconnect();
    assert(!buddy_voice_recording());
    return 0;
}
