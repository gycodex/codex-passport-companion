#pragma once
#include "esp_err.h"
#include "buddy_pair_gate.h"

#define BUDDY_DISCOVERY_PORT 8764
esp_err_t buddy_lan_pair_start(void);
/* Called only by the single LAN server worker, before normal authentication. */
void buddy_lan_pair_serve(int client, const char *commit, const uint8_t key[32]);
void buddy_lan_pair_snapshot(buddy_pair_gate_t *snapshot);
void buddy_lan_pair_decide(uint32_t observed_id, bool approve);
