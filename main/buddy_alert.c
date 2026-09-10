#include "buddy_alert.h"

bool buddy_alert_allowed(uint8_t mode, int64_t epoch_seconds, int32_t offset_seconds,
                         uint64_t received_ms, uint64_t now_ms)
{
    if (mode == BUDDY_SOUND_ON) return true;
    if (mode != BUDDY_SOUND_AUTO || epoch_seconds <= 0) return false;
    uint64_t elapsed = now_ms >= received_ms ? (now_ms - received_ms) / 1000U : 0U;
    int64_t local = epoch_seconds % 86400 + offset_seconds + (int64_t)(elapsed % 86400U);
    unsigned hour = (unsigned)((local % 86400 + 86400) % 86400) / 3600U;
    return hour >= 8U && hour < 22U;
}
