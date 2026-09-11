#include <assert.h>
#include <setjmp.h>
#include <string.h>
#include "../main/buddy_sound.c"

static jmp_buf finished;
static bool recording, fail_write;
static unsigned waits, reads, cues, volume, captures;

int64_t esp_timer_get_time(void) { return 3000000; }
bool buddy_voice_recording(void) { return recording; }
void buddy_voice_stop(void) { recording = false; }
void buddy_voice_capture(const int16_t *pcm)
{
    (void)pcm;
    assert(volume == 0 && cues == 1 && reads == 6);
    ++captures;
    /* Simulate the user stopping, or expiry/disconnect, with no notification. */
    recording = false;
}
esp_err_t bsp_audio_init(void) { return ESP_OK; }
esp_err_t bsp_audio_set_format(unsigned rate, unsigned bits, unsigned channels)
{
    assert(rate == 16000 && bits == 16 && channels == 1);
    return ESP_OK;
}
esp_err_t bsp_audio_read(void *pcm, size_t size)
{
    assert(volume == 0 && cues == 1);
    ++reads;
    memset(pcm, 0, size);
    return ESP_OK;
}
esp_err_t bsp_audio_write(const void *pcm, size_t size)
{
    (void)pcm;
    assert(volume == 80 && size <= 320);
    return fail_write ? -1 : ESP_OK;
}
void bsp_audio_set_volume(uint8_t value)
{
    volume = value;
    if (value == 80) ++cues;
}
void vTaskDelay(unsigned ticks) { assert(ticks == 100); }
int xTaskNotifyWait(uint32_t clear, uint32_t exit_bits, uint32_t *pending, uint32_t timeout)
{
    (void)clear; (void)exit_bits;
    if (waits == 2 || (fail_write && waits == 1)) longjmp(finished, 1);
    /* The stop transition must not block waiting for an unrelated alert. */
    assert(timeout == 0);
    *pending = waits++ == 0 ? SOUND_CAPTURE : 0;
    return 1;
}
int xTaskCreate(void (*entry)(void *), const char *name, unsigned stack,
                void *context, unsigned priority, TaskHandle_t *handle)
{
    (void)entry; (void)name; (void)stack; (void)context; (void)priority;
    *handle = (void *)1;
    return pdPASS;
}
void xTaskNotify(TaskHandle_t handle, uint32_t bits, int mode)
{
    (void)handle; (void)bits; (void)mode;
}
int main(void)
{
    recording = true;
    if (setjmp(finished) == 0) sound_worker(NULL);
    assert(captures == 1 && cues == 2 && buddy_sound_play_count() == 2);
    assert(volume == 0 && !recording);

    waits = reads = cues = captures = 0;
    recording = fail_write = true;
    if (setjmp(finished) == 0) sound_worker(NULL);
    assert(captures == 0 && reads == 0 && !recording && volume == 0);
    assert(buddy_sound_stage() == 100);
    return 0;
}
