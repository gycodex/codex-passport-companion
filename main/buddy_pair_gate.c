#include "buddy_pair_gate.h"

bool buddy_pair_gate_live(const buddy_pair_gate_t *gate, uint64_t now_ms)
{
    return gate && gate->id != 0 && !gate->rejected && now_ms < gate->deadline_ms;
}

bool buddy_pair_gate_decide(buddy_pair_gate_t *gate, uint32_t observed_id,
                           bool approve, uint64_t now_ms)
{
    if (!buddy_pair_gate_live(gate, now_ms) || gate->id != observed_id || gate->approved) return false;
    gate->approved = approve;
    gate->rejected = !approve;
    return true;
}
