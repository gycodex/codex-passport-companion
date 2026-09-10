#include "buddy_voice.h"
#include "buddy_adpcm.h"
#include <stdio.h>
#include <string.h>
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "mbedtls/base64.h"

/* 320 ms of independently decodable compressed frames, only 2608 bytes of RAM. */
#define FRAME_BYTES (3 + BUDDY_VOICE_SAMPLES / 2)
static uint8_t s_pcm[16][FRAME_BYTES];
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static unsigned s_head, s_count, s_session, s_sequence, s_dropped, s_peak;
static bool s_recording;
static int64_t s_poll_us, s_start_us;

static bool ready(int64_t now) { return s_poll_us != 0 && now - s_poll_us < 2000000; }
static void expire(int64_t now)
{
    if (!ready(now) || now - s_start_us >= 120000000) s_recording = false;
    if (!ready(now)) { s_count = 0; s_peak = 0; }
}
bool buddy_voice_toggle(void)
{
    int64_t now = esp_timer_get_time();
    portENTER_CRITICAL(&s_lock);
    expire(now);
    if (s_recording) s_recording = false;
    else if (ready(now) && s_count == 0) {
        s_recording = true;
        ++s_session;
        s_sequence = s_dropped = s_head = s_peak = 0;
        s_start_us = now;
    }
    bool active = s_recording;
    portEXIT_CRITICAL(&s_lock);
    return active;
}
void buddy_voice_stop(void)
{
    portENTER_CRITICAL(&s_lock);
    s_recording = false;
    portEXIT_CRITICAL(&s_lock);
}
void buddy_voice_disconnect(void)
{
    portENTER_CRITICAL(&s_lock);
    s_recording = false;
    s_poll_us = 0;
    s_count = s_peak = 0;
    memset(s_pcm, 0, sizeof(s_pcm));
    portEXIT_CRITICAL(&s_lock);
}
void buddy_voice_status(buddy_voice_status_t *status)
{
    int64_t now = esp_timer_get_time();
    portENTER_CRITICAL(&s_lock);
    expire(now);
    *status = (buddy_voice_status_t){ready(now), s_recording,
        s_recording ? (unsigned)((now - s_start_us) / 1000000) : 0, s_peak};
    portEXIT_CRITICAL(&s_lock);
}
bool buddy_voice_recording(void)
{
    buddy_voice_status_t status;
    buddy_voice_status(&status);
    return status.recording;
}
void buddy_voice_capture(const int16_t *pcm)
{
    /* Only the audio worker owns encoder state. Every frame carries a snapshot. */
    static buddy_adpcm_state_t codec;
    static unsigned codec_session;
    unsigned peak = 0, session;
    portENTER_CRITICAL(&s_lock);
    session = s_session;
    portEXIT_CRITICAL(&s_lock);
    if (codec_session != session) { codec = (buddy_adpcm_state_t){0}; codec_session = session; }
    uint8_t encoded[FRAME_BYTES];
    encoded[0] = (uint8_t)codec.predictor;
    encoded[1] = (uint8_t)((uint16_t)codec.predictor >> 8);
    encoded[2] = (uint8_t)codec.step_index;
    buddy_adpcm_encode(&codec, pcm, BUDDY_VOICE_SAMPLES, encoded + 3);
    for (unsigned i = 0; i < BUDDY_VOICE_SAMPLES; ++i) {
        unsigned amplitude = pcm[i] < 0 ? -(int)pcm[i] : pcm[i];
        if (amplitude > peak) peak = amplitude;
    }
    portENTER_CRITICAL(&s_lock);
    expire(esp_timer_get_time());
    if (s_recording && session == s_session) {
        if (s_count == 16) { s_head = (s_head + 1) % 16; --s_count; ++s_dropped; }
        memcpy(s_pcm[(s_head + s_count) % 16], encoded, FRAME_BYTES);
        ++s_count;
        ++s_sequence;
        s_peak = peak;
    }
    portEXIT_CRITICAL(&s_lock);
}
size_t buddy_voice_poll(char *reply, size_t capacity)
{
    uint8_t pcm[8 * FRAME_BYTES];
    unsigned count, session, sequence, pending, peak, dropped;
    bool recording;
    portENTER_CRITICAL(&s_lock);
    expire(esp_timer_get_time());
    s_poll_us = esp_timer_get_time();
    count = s_count > 8 ? 8 : s_count;
    sequence = s_sequence - s_count;
    for (unsigned i = 0; i < count; ++i) {
        memcpy(pcm + i * FRAME_BYTES, s_pcm[s_head], sizeof(s_pcm[0]));
        memset(s_pcm[s_head], 0, sizeof(s_pcm[0]));
        s_head = (s_head + 1) % 16;
    }
    s_count -= count;
    pending = s_count; session = s_session; recording = s_recording;
    peak = s_peak; dropped = s_dropped;
    portEXIT_CRITICAL(&s_lock);
    int n = snprintf(reply, capacity,
        "{\"voice\":1,\"session\":%u,\"recording\":%s,\"sequence\":%u,\"pending\":%u,\"peak\":%u,\"dropped\":%u,\"adpcm\":\"",
        session, recording ? "true" : "false", sequence, pending, peak, dropped);
    if (n < 0 || (size_t)n + 3 >= capacity) return 0;
    size_t encoded = 0;
    int err = mbedtls_base64_encode((unsigned char *)reply + n, capacity - n - 3,
                                  &encoded, pcm, count * FRAME_BYTES);
    memset(pcm, 0, sizeof(pcm));
    if (err) return 0;
    memcpy(reply + n + encoded, "\"}", 3);
    return (size_t)n + encoded + 2;
}
