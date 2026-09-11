#pragma once
#include <stdint.h>
uint32_t buddy_sound_stage(void);
uint32_t buddy_sound_play_count(void);

/* Called only from the application task; audio runs on its own bounded worker. */
void buddy_sound_notify(void);
void buddy_sound_voice_wake(void);
void buddy_sound_notify_connected(void);
