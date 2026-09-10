#pragma once

#include "buddy_types.h"

typedef struct {
    char label[32];
    unsigned remaining;
    uint64_t resets_at;
} buddy_usage_window_t;

/* Compact only the windows actually reported by the service. */
size_t buddy_usage_windows(const buddy_codex_usage_t *usage,
                           buddy_usage_window_t windows[2]);
