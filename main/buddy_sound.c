#include "buddy_sound.h"
#include "buddy_voice.h"
#include "esp_timer.h"

#include <stdint.h>
#include <stdbool.h>
#include <stdatomic.h>
#include "bsp_audio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

enum { SOUND_CONNECTED = 1U, SOUND_COMPLETED = 2U, SOUND_CAPTURE = 4U };
static TaskHandle_t s_worker;
static atomic_uint s_stage;
static atomic_uint s_play_count;
uint32_t buddy_sound_stage(void) { return atomic_load(&s_stage); }
uint32_t buddy_sound_play_count(void) { return atomic_load(&s_play_count); }
static const char *TAG = "buddy_sound";

static esp_err_t tone(unsigned frequency, unsigned frames)
{
    static const int16_t wave[16] = {0, 3827, 7071, 9239, 10000, 9239, 7071, 3827,
                                    0, -3827, -7071, -9239, -10000, -9239, -7071, -3827};
    int16_t pcm[160];
    uint32_t phase = 0;
    uint32_t step = frequency * 65536U / 16000U;
    for (unsigned start = 0; start < frames; start += 160U) {
        unsigned count = frames - start < 160U ? frames - start : 160U;
        for (unsigned i = 0; i < count; ++i) {
            unsigned sample = start + i;
            unsigned envelope = sample < 160U ? sample : 160U;
            if (frames - sample < envelope) envelope = frames - sample;
            pcm[i] = frequency == 0U ? 0 : (int16_t)(wave[(phase >> 12) & 15U] * (int)envelope / 160);
            phase += step;
        }
        esp_err_t err = bsp_audio_write(pcm, count * sizeof(pcm[0]));
        if (err != ESP_OK) return err;
    }
    return ESP_OK;
}

static esp_err_t voice_cue(bool starting)
{
    bsp_audio_set_volume(80);
    esp_err_t err = tone(starting ? 1040 : 660, 1280);
    /* Flush the 90 ms TX DMA queue before muting. RX is drained separately
     * before capture so the start cue cannot enter the dictated audio. */
    if (err == ESP_OK) err = tone(0, 1600);
    vTaskDelay(pdMS_TO_TICKS(100));
    bsp_audio_set_volume(0);
    if (err == ESP_OK) {
        atomic_fetch_add(&s_play_count, 1);
        ESP_LOGI(TAG, "Voice %s chime played", starting ? "start" : "stop");
    }
    return err;
}

static void sound_worker(void *context)
{
    (void)context;
    bool initialized = false;
    bool failed = false;
    bool capturing = false;
    int64_t last_completion = -2000000;
    for (;;) {
        uint32_t pending = 0;
        (void)xTaskNotifyWait(0, UINT32_MAX, &pending,
                              (capturing || buddy_voice_recording()) ? 0 : portMAX_DELAY);
        if (failed) { buddy_voice_stop(); continue; }
        esp_err_t err = ESP_OK;
        if (!initialized) {
            atomic_store(&s_stage, 1);
            err = bsp_audio_init();
            atomic_store(&s_stage, 2);
            if (err == ESP_OK) err = bsp_audio_set_format(16000, 16, 1);
            initialized = err == ESP_OK;
        }
        if (err == ESP_OK && buddy_voice_recording()) {
            int16_t pcm[BUDDY_VOICE_SAMPLES];
            if (!capturing) {
                err = voice_cue(true);
                /* Drain old RX DMA samples before beginning this physical-button take. */
                for (unsigned i = 0; i < 5 && err == ESP_OK; ++i) err = bsp_audio_read(pcm, sizeof(pcm));
                capturing = true;
            }
            if (err == ESP_OK) err = bsp_audio_read(pcm, sizeof(pcm));
            if (err == ESP_OK) buddy_voice_capture(pcm);
            else buddy_voice_stop();
            if (err == ESP_OK) continue;
        }
        if (capturing && err == ESP_OK) err = voice_cue(false);
        capturing = false;
        if (err == ESP_OK && !(pending & (SOUND_CONNECTED | SOUND_COMPLETED))) continue;
        if ((pending & SOUND_COMPLETED) && esp_timer_get_time() - last_completion < 2000000) continue;
        if (pending & SOUND_COMPLETED) last_completion = esp_timer_get_time();
        if (err == ESP_OK) {
            atomic_store(&s_stage, 3);
            /* Codec volume is a -50..0 dB curve, not linear amplitude.
             * 25 was almost inaudible with the already attenuated PCM. */
            bsp_audio_set_volume(80);
            atomic_store(&s_stage, 4);
            if (pending & SOUND_COMPLETED) {
                err = tone(660, 1280);
                if (err == ESP_OK) err = tone(0, 320);
                if (err == ESP_OK) err = tone(880, 1280);
            } else {
                err = tone(880, 1600); /* One 100 ms connection note. */
            }
            /* Drain the DMA tail before muting to avoid a clipped last note. */
            if (err == ESP_OK) err = tone(0, 1600);
            vTaskDelay(pdMS_TO_TICKS(100));
            bsp_audio_set_volume(0);
        }
        if (err != ESP_OK) {
            atomic_store(&s_stage, 100);
            failed = true;
            ESP_LOGW(TAG, "Audio unavailable: %s", esp_err_to_name(err));
        } else {
            atomic_store(&s_stage, 5);
            atomic_fetch_add(&s_play_count, 1);
            ESP_LOGI(TAG, "%s chime played", (pending & SOUND_COMPLETED) ? "Completion" : "Connection");
        }

    }
}

static void notify_sound(uint32_t kind)
{
    if (s_worker == NULL && xTaskCreate(sound_worker, "buddy_sound", 6144, NULL,
                                       3, &s_worker) != pdPASS) {
        ESP_LOGW(TAG, "Unable to allocate audio worker");
        buddy_voice_stop();
        return;
    }
    xTaskNotify(s_worker, kind, eSetBits);
}

void buddy_sound_voice_wake(void) { notify_sound(SOUND_CAPTURE); }
void buddy_sound_notify(void) { notify_sound(SOUND_COMPLETED); }
void buddy_sound_notify_connected(void) { notify_sound(SOUND_CONNECTED); }
