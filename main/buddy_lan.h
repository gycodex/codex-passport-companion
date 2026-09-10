#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

#define BUDDY_LAN_PORT 8765
#define BUDDY_LAN_PAYLOAD_MAX 2048
typedef bool (*buddy_lan_receive_t)(const char *, size_t, uint32_t);
bool buddy_lan_configured(void);
esp_err_t buddy_lan_start(buddy_lan_receive_t receive);
bool buddy_lan_connected(void);
uint32_t buddy_lan_generation(void);
void buddy_lan_ip(char out[16]);
/* Physical USB only. Never expose provisioning on the network transport. */
bool buddy_lan_usb_command(const char *line);
esp_err_t buddy_lan_forget(void);
bool buddy_lan_setup_requested(void);
esp_err_t buddy_lan_request_setup(void);
esp_err_t buddy_lan_start_setup(void);
bool buddy_lan_setup_active(void);
void buddy_lan_setup_password(char out[13]);
