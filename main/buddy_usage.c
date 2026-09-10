#include "buddy_usage.h"

#include <stdio.h>
#include <string.h>

size_t buddy_usage_windows(const buddy_codex_usage_t *usage,
                           buddy_usage_window_t windows[2])
{
    size_t count = 0;
    memset(windows, 0, sizeof(*windows) * 2U);
    if (!usage->available) return 0;
    const unsigned durations[] = {usage->primary_window_minutes,
                                  usage->secondary_window_minutes};
    const unsigned used[] = {usage->primary_used_percent,
                             usage->secondary_used_percent};
    const uint64_t resets[] = {usage->primary_resets_at,
                               usage->secondary_resets_at};
    for (size_t i = 0; i < 2U; ++i) {
        unsigned minutes = durations[i];
        if (minutes == 0U) continue;
        buddy_usage_window_t *window = &windows[count++];
        unsigned amount = minutes;
        const char *unit = "min";
        if (minutes % 1440U == 0U) {
            amount = minutes / 1440U;
            unit = amount == 1U ? "day" : "days";
        } else if (minutes % 60U == 0U) {
            amount = minutes / 60U;
            unit = amount == 1U ? "hour" : "hours";
        }
        snprintf(window->label, sizeof(window->label), "%u %s", amount, unit);
        window->remaining = used[i] > 100U ? 0U : 100U - used[i];
        window->resets_at = resets[i];
    }
    return count;
}
