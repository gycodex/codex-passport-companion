#pragma once
#include "buddy_types.h"

bool buddy_alert_allowed(uint8_t mode, int64_t epoch_seconds, int32_t offset_seconds,
                         uint64_t received_ms, uint64_t now_ms);
