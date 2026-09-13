#pragma once
#include <stdbool.h>
#include <stdint.h>

/* Caller owns synchronization; independent of sockets, crypto and LVGL. */
typedef struct {
    uint32_t id;
    uint32_t code;
    uint64_t deadline_ms;
    bool approved;
    bool rejected;
} buddy_pair_gate_t;

bool buddy_pair_gate_live(const buddy_pair_gate_t *gate, uint64_t now_ms);
bool buddy_pair_gate_decide(buddy_pair_gate_t *gate, uint32_t observed_id,
                           bool approve, uint64_t now_ms);
