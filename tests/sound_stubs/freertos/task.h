#pragma once
#include "FreeRTOS.h"
typedef void *TaskHandle_t;
int xTaskNotifyWait(uint32_t, uint32_t, uint32_t *, uint32_t);
int xTaskCreate(void (*)(void *), const char *, unsigned, void *, unsigned, TaskHandle_t *);
void xTaskNotify(TaskHandle_t, uint32_t, int);
void vTaskDelay(unsigned);
