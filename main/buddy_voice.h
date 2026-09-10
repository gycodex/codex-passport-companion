#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define BUDDY_VOICE_SAMPLES 320
typedef struct {
    bool ready, recording;
    unsigned seconds, peak;
} buddy_voice_status_t;

/* Only physical application actions may start recording. Poll grants a 2 s lease. */
bool buddy_voice_toggle(void);
void buddy_voice_disconnect(void);
void buddy_voice_stop(void);
bool buddy_voice_recording(void);
void buddy_voice_capture(const int16_t *pcm);
void buddy_voice_status(buddy_voice_status_t *status);
size_t buddy_voice_poll(char *reply, size_t capacity);
