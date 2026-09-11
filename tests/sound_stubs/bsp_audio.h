#pragma once
#include <stddef.h>
#include <stdint.h>
typedef int esp_err_t;
#define ESP_OK 0
esp_err_t bsp_audio_init(void);
esp_err_t bsp_audio_set_format(unsigned, unsigned, unsigned);
esp_err_t bsp_audio_read(void *, size_t);
esp_err_t bsp_audio_write(const void *, size_t);
void bsp_audio_set_volume(uint8_t);
