#include "buddy_lan.h"
#include <stdio.h>
#include <string.h>
#include <stdatomic.h>
#include <sys/time.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_timer.h"
#include <unistd.h>
#include <stdlib.h>
#include "esp_bt.h"
#include "esp_log.h"
#include "nvs.h"
#include "lwip/sockets.h"
#include "mbedtls/gcm.h"
#include "mbedtls/md.h"
#include "cJSON.h"
#include "esp_http_server.h"

typedef struct {
    uint32_t magic;
    char ssid[33];
    char password[64];
    uint8_t key[32];
} lan_config_t;
typedef struct {
    char line[2*(BUDDY_LAN_PAYLOAD_MAX+16)+11];
    uint8_t ciphertext[BUDDY_LAN_PAYLOAD_MAX+16];
    uint8_t plaintext[BUDDY_LAN_PAYLOAD_MAX+1];
} lan_buffers_t;
static lan_buffers_t *s_buffers;
static lan_config_t s_config;
static atomic_bool s_up, s_authenticated;
static atomic_uint s_generation;
static portMUX_TYPE s_ip_lock = portMUX_INITIALIZER_UNLOCKED;
static char s_ip[16];
static buddy_lan_receive_t s_receive;
static bool s_loaded, s_configured;
static const char *TAG = "buddy_lan";
static bool s_setup;
static char s_setup_password[13], s_setup_token[33];
static atomic_bool s_setup_saved, s_setup_exit;

bool buddy_lan_setup_active(void) { return s_setup; }
void buddy_lan_setup_password(char out[13]) { memcpy(out, s_setup_password, 13); }
bool buddy_lan_setup_requested(void)
{
    nvs_handle_t nvs;
    uint8_t requested = 0;
    if (nvs_open("passport_lan", NVS_READWRITE, &nvs) == ESP_OK) {
        nvs_get_u8(nvs, "setup", &requested);
        if (requested) {
            if (nvs_erase_key(nvs, "setup") != ESP_OK || nvs_commit(nvs) != ESP_OK) requested = 0;
        }
        nvs_close(nvs);
    }
    return requested == 1;
}
esp_err_t buddy_lan_request_setup(void)
{
    nvs_handle_t nvs;
    esp_err_t err = nvs_open("passport_lan", NVS_READWRITE, &nvs);
    if (err != ESP_OK) return err;
    err = nvs_set_u8(nvs, "setup", 1);
    if (err == ESP_OK) err = nvs_commit(nvs);
    nvs_close(nvs);
    return err;
}

static int unhex(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}
static bool decode(const char *text, uint8_t *bytes, size_t count)
{
    for (size_t i = 0; i < count; ++i) {
        int a = unhex(text[2*i]), b = unhex(text[2*i+1]);
        if (a < 0 || b < 0) return false;
        bytes[i] = (uint8_t)((a << 4) | b);
    }
    return true;
}
static void encode(const uint8_t *bytes, char *text, size_t count)
{
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < count; ++i) {
        text[2*i] = hex[bytes[i] >> 4]; text[2*i+1] = hex[bytes[i] & 15];
    }
    text[2*count] = 0;
}
static cJSON *parse_flat_object(const char *text)
{
    /* Provisioning and hello objects contain scalars only; bound parser recursion. */
    unsigned depth = 0;
    bool quoted = false, escaped = false;
    for (const char *p=text; *p; ++p) {
        if (quoted) {
            if (escaped) escaped=false;
            else if (*p=='\\') escaped=true;
            else if (*p=='"') quoted=false;
        } else if (*p=='"') quoted=true;
        else if (*p=='[' || *p==']') return NULL;
        else if (*p=='{' && ++depth > 1) return NULL;
        else if (*p=='}') { if (depth==0) return NULL; --depth; }
    }
    if (depth || quoted) return NULL;
    cJSON *value = cJSON_ParseWithOpts(text, NULL, true);
    if (!cJSON_IsObject(value)) { cJSON_Delete(value); return NULL; }
    return value;
}
bool buddy_lan_configured(void)
{
    if (s_loaded) return s_configured;
    nvs_handle_t nvs;
    size_t size = sizeof(s_config);
    if (nvs_open("passport_lan", NVS_READONLY, &nvs) == ESP_OK) {
        s_configured = nvs_get_blob(nvs, "config", &s_config, &size) == ESP_OK &&
            size == sizeof(s_config) && s_config.magic == 0x4c414e31 &&
            s_config.ssid[0] && memchr(s_config.ssid, 0, sizeof(s_config.ssid)) &&
            memchr(s_config.password, 0, sizeof(s_config.password));
        nvs_close(nvs);
    }
    s_loaded = true;
    return s_configured;
}
esp_err_t buddy_lan_forget(void)
{
    nvs_handle_t nvs;
    esp_err_t err = nvs_open("passport_lan", NVS_READWRITE, &nvs);
    if (err != ESP_OK) return err;
    err = nvs_erase_all(nvs);
    if (err == ESP_OK) err = nvs_commit(nvs);
    nvs_close(nvs);
    return err;
}
bool buddy_lan_connected(void) { return atomic_load(&s_authenticated) && atomic_load(&s_up); }
uint32_t buddy_lan_generation(void) { return atomic_load(&s_generation); }
void buddy_lan_ip(char out[16])
{
    taskENTER_CRITICAL(&s_ip_lock);
    memcpy(out, s_ip, 16);
    taskEXIT_CRITICAL(&s_ip_lock);
}
static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) esp_wifi_connect();
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        atomic_store(&s_up, false);
        atomic_store(&s_authenticated, false);
        atomic_fetch_add(&s_generation, 1);
        taskENTER_CRITICAL(&s_ip_lock); s_ip[0] = 0; taskEXIT_CRITICAL(&s_ip_lock);
        esp_wifi_connect();
    }
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = data;
        taskENTER_CRITICAL(&s_ip_lock);
        snprintf(s_ip, sizeof(s_ip), IPSTR, IP2STR(&event->ip_info.ip));
        taskEXIT_CRITICAL(&s_ip_lock);
        atomic_store(&s_up, true);
    }
}
static bool send_all(int socket, const char *data, size_t length)
{
    while (length) {
        int n = send(socket, data, length, 0);
        if (n <= 0) return false;
        data += n; length -= (size_t)n;
    }
    return true;
}
static int read_line(int socket, char *line, size_t size)
{
    /* One request at a time; finite socket timeout also bounds slow clients. */
    int64_t deadline = esp_timer_get_time() + 35000000LL;
    for (size_t n = 0; n + 1 < size; ++n) {
        if (esp_timer_get_time() > deadline || !atomic_load(&s_up)) return -1;
        if (recv(socket, &line[n], 1, 0) != 1) return -1;
        if (line[n] == '\n') { line[n] = 0; return (int)n; }
    }
    return -1;
}
static void make_nonce(const uint8_t base[12], uint32_t sequence, uint8_t out[12])
{
    memcpy(out, base, 12);
    for (unsigned i = 0; i < 4; ++i) out[11-i] ^= (uint8_t)(sequence >> (8*i));
}
static bool handshake_digest(const uint8_t key[32], const uint8_t client[12], const uint8_t server[12], char domain,
                             uint8_t out[32])
{
    uint8_t message[35];
    memcpy(message, "FAP-LAN-1:", 10); message[10] = (uint8_t)domain;
    memcpy(message+11, client, 12); memcpy(message+23, server, 12);
    return mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
                           key, 32, message, sizeof(message), out) == 0;
}
static bool crypto_self_test(void)
{
    /* Cross-language vector generated by Python cryptography.AESGCM. */
    uint8_t key[32], base[12], nonce[12], expected[21], plain[5];
    for (unsigned i=0; i<32; ++i) key[i]=(uint8_t)i;
    for (unsigned i=0; i<12; ++i) base[i]=(uint8_t)i;
    decode("cebda52c6011065b2f86f259d272c2311c3b6e7e8c", expected, 21);
    make_nonce(base, 1, nonce);
    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    bool ok = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, key, 256) == 0 &&
        mbedtls_gcm_auth_decrypt(&gcm, 5, nonce, 12, (const uint8_t *)"FAP-LAN-1:C", 11,
            expected+5, 16, expected, plain) == 0 && memcmp(plain, "hello", 5) == 0;
    expected[20] ^= 1;
    ok = ok && mbedtls_gcm_auth_decrypt(&gcm, 5, nonce, 12, (const uint8_t *)"FAP-LAN-1:C", 11,
            expected+5, 16, expected, plain) != 0;
    mbedtls_gcm_free(&gcm);
    uint8_t hmac_value[32], hmac_expected[32];
    decode("818e94f2164c1bc85efba942ea41ba527dbe183671c6b77d7f8fc0e497f7596e", hmac_expected, 32);
    ok = ok && handshake_digest(key, base, base, 'H', hmac_value) &&
         memcmp(hmac_value, hmac_expected, 32) == 0;
    decode("d8c70527edcc132935661e5cede13ceceafeaf3f5e96a66fb4f60e78fb7c50c6", hmac_expected, 32);
    ok = ok && handshake_digest(key, base, base, 'N', hmac_value) &&
         memcmp(hmac_value, hmac_expected, 32) == 0;
    return ok;
}
static void serve(int client, lan_buffers_t *buffers)
{
    uint8_t challenge[12], nonce[12], tag[16], client_nonce[12], server_nonce[12], digest[32];
    char hello[160], hex[25], auth[65];
    uint32_t generation = atomic_fetch_add(&s_generation, 1) + 1;
    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    if (mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, s_config.key, 256) != 0) goto done;
    int hello_size = read_line(client, buffers->line, sizeof(buffers->line));
    if (hello_size <= 0 || hello_size > 96) goto done;
    cJSON *request = parse_flat_object(buffers->line);
    const cJSON *version = cJSON_GetObjectItemCaseSensitive(request, "v");
    const cJSON *client_value = cJSON_GetObjectItemCaseSensitive(request, "client_nonce");
    bool valid = cJSON_IsNumber(version) && version->valuedouble == 1 &&
        cJSON_IsString(client_value) && strlen(client_value->valuestring) == 24 &&
        decode(client_value->valuestring, client_nonce, 12);
    cJSON_Delete(request);
    if (!valid) goto done;
    esp_fill_random(server_nonce, sizeof(server_nonce));
    encode(server_nonce, hex, sizeof(server_nonce));
    if (!handshake_digest(s_config.key, client_nonce, server_nonce, 'H', digest)) goto done;
    encode(digest, auth, 32);
    if (!handshake_digest(s_config.key, client_nonce, server_nonce, 'N', digest)) goto done;
    memcpy(challenge, digest, 12);
    int length = snprintf(hello, sizeof(hello), "{\"v\":1,\"nonce\":\"%s\",\"auth\":\"%s\"}\n", hex, auth);
    if (!send_all(client, hello, (size_t)length)) goto done;
    for (uint32_t sequence = 1; sequence < 0x80000000U; ++sequence) {
        int n = read_line(client, buffers->line, sizeof(buffers->line));
        if (generation != atomic_load(&s_generation)) break;
        uint8_t seq_bytes[4];
        if (n < 41 || buffers->line[8] != ':' || ((n-9) & 1) || !decode(buffers->line, seq_bytes, 4)) break;
        uint32_t received = ((uint32_t)seq_bytes[0]<<24) | ((uint32_t)seq_bytes[1]<<16) |
                            ((uint32_t)seq_bytes[2]<<8) | seq_bytes[3];
        size_t size = (size_t)(n-9)/2;
        if (received != sequence || size > sizeof(buffers->ciphertext) || !decode(buffers->line+9, buffers->ciphertext, size)) break;
        make_nonce(challenge, sequence, nonce);
        if (mbedtls_gcm_auth_decrypt(&gcm, size-16, nonce, 12,
                (const uint8_t *)"FAP-LAN-1:C", 11, buffers->ciphertext+size-16, 16,
                buffers->ciphertext, buffers->plaintext) != 0) break;
        buffers->plaintext[size-16] = 0;
        atomic_store(&s_authenticated, true);
        if (sequence == 1) {
            struct timeval timeout = {.tv_sec=35};
            setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        }
        bool accepted = s_receive((const char *)buffers->plaintext, size-16, generation);
        const char *reply = accepted ? "{\"ok\":true}" : "{\"ok\":false}";
        size_t reply_size = strlen(reply);
        make_nonce(challenge, sequence | 0x80000000U, nonce);
        if (mbedtls_gcm_crypt_and_tag(&gcm, MBEDTLS_GCM_ENCRYPT, reply_size, nonce, 12,
                (const uint8_t *)"FAP-LAN-1:S", 11, (const uint8_t *)reply, buffers->ciphertext, 16, tag) != 0) break;
        memcpy(buffers->ciphertext+reply_size, tag, 16);
        snprintf(buffers->line, 10, "%08lx:", (unsigned long)sequence);
        encode(buffers->ciphertext, buffers->line+9, reply_size+16);
        size_t wire_size = 9 + 2*(reply_size+16);
        buffers->line[wire_size++] = '\n';
        if (!send_all(client, buffers->line, wire_size)) break;
    }
done:
    atomic_store(&s_authenticated, false);
    mbedtls_gcm_free(&gcm);
    memset(buffers->plaintext, 0, sizeof(buffers->plaintext));
}
static void server_task(void *arg)
{
    (void)arg;
    for (;;) {
        if (!atomic_load(&s_up)) { vTaskDelay(pdMS_TO_TICKS(1000)); continue; }
        int listener = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
        if (listener < 0) { vTaskDelay(pdMS_TO_TICKS(1000)); continue; }
        struct sockaddr_in address = {.sin_family=AF_INET, .sin_port=htons(BUDDY_LAN_PORT),
                                      .sin_addr.s_addr=htonl(INADDR_ANY)};
        int reuse = 1; setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
        struct timeval timeout = {.tv_sec=2};
        setsockopt(listener, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        if (bind(listener, (struct sockaddr *)&address, sizeof(address)) == 0 && listen(listener, 1) == 0) {
            while (atomic_load(&s_up)) {
                int client = accept(listener, NULL, NULL);
                if (client < 0) { vTaskDelay(pdMS_TO_TICKS(100)); continue; }
                timeout.tv_sec = 5;
                setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
                timeout.tv_sec = 3;
                setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
                serve(client, s_buffers); shutdown(client, SHUT_RDWR); close(client);
                vTaskDelay(pdMS_TO_TICKS(250));
            }
        }
        close(listener);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
esp_err_t buddy_lan_start(buddy_lan_receive_t receive)
{
    if (!buddy_lan_configured() || !receive || !crypto_self_test()) return ESP_ERR_INVALID_STATE;
    s_receive = receive;
    /* The boot-selected LAN mode never starts BLE. Release its reserved RAM. */
    (void)esp_bt_controller_mem_release(ESP_BT_MODE_BLE);
    s_buffers = calloc(1, sizeof(*s_buffers));
    if (!s_buffers) return ESP_ERR_NO_MEM;
    esp_err_t err = esp_netif_init();
    if (err != ESP_OK) return err;
    err = esp_event_loop_create_default();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) return err;
    if (!esp_netif_create_default_wifi_sta()) return ESP_ERR_NO_MEM;
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    err = esp_wifi_init(&init); if (err != ESP_OK) return err;
    err = esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL);
    if (err != ESP_OK) return err;
    err = esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL);
    if (err != ESP_OK) return err;
    wifi_config_t config = {0};
    memcpy(config.sta.ssid, s_config.ssid, strlen(s_config.ssid));
    memcpy(config.sta.password, s_config.password, strlen(s_config.password));
    config.sta.threshold.authmode = s_config.password[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    err = esp_wifi_set_storage(WIFI_STORAGE_RAM);
    if (err == ESP_OK) err = esp_wifi_set_mode(WIFI_MODE_STA);
    if (err == ESP_OK) err = esp_wifi_set_config(WIFI_IF_STA, &config);
    memset(&config, 0, sizeof(config));
    if (err == ESP_OK) err = esp_wifi_start();
    if (err != ESP_OK) return err;
    if (xTaskCreate(server_task, "lan_server", 8192, NULL, 3, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    ESP_LOGI(TAG, "LAN transport started");
    return ESP_OK;
}
bool buddy_lan_usb_command(const char *line)
{
    if (strcmp(line, "FAP_LAN_SETUP_V1") == 0) {
        esp_err_t err = buddy_lan_request_setup();
        printf("FAP_LAN {\"saved\":%s}\n", err == ESP_OK ? "true" : "false");
        fflush(stdout);
        if (err == ESP_OK) { vTaskDelay(pdMS_TO_TICKS(500)); esp_restart(); }
        return true;
    }
    if (strcmp(line, "FAP_LAN_EXIT_SETUP_V1") == 0 && s_setup) {
        atomic_store(&s_setup_exit, true);
        printf("FAP_LAN {\"saved\":true}\n");
        return true;
    }
    if (strcmp(line, "FAP_LAN_STATUS_V1") == 0) {
        char ip[16]; buddy_lan_ip(ip);
        printf("FAP_LAN {\"configured\":%s,\"ip\":\"%s\",\"port\":%u,\"connected\":%s,\"crypto_ok\":%s,\"setup\":%s,\"heap\":%lu}\n",
               buddy_lan_configured() ? "true" : "false", ip, BUDDY_LAN_PORT,
               buddy_lan_connected() ? "true" : "false", crypto_self_test() ? "true" : "false",
               s_setup ? "true" : "false", (unsigned long)esp_get_free_heap_size());
        return true;
    }
    if (strncmp(line, "FAP_LAN_CONFIG_V1 ", 18) != 0) return false;
    if (s_setup) { printf("FAP_LAN {\"saved\":false}\n"); return true; }
    cJSON *json = parse_flat_object(line+18);
    const cJSON *disable = cJSON_GetObjectItemCaseSensitive(json, "disable");
    esp_err_t err = ESP_ERR_INVALID_ARG;
    if (cJSON_IsTrue(disable)) {
        err = buddy_lan_forget();
    } else {
        const cJSON *ssid = cJSON_GetObjectItemCaseSensitive(json, "ssid");
        const cJSON *password = cJSON_GetObjectItemCaseSensitive(json, "password");
        const cJSON *key = cJSON_GetObjectItemCaseSensitive(json, "key");
        lan_config_t config = {.magic=0x4c414e31};
        if (cJSON_IsString(ssid) && cJSON_IsString(password) && cJSON_IsString(key) &&
            strlen(ssid->valuestring) > 0 && strlen(ssid->valuestring) <= 32 &&
            (strlen(password->valuestring) == 0 || strlen(password->valuestring) >= 8) &&
            strlen(password->valuestring) <= 63 &&
            strlen(key->valuestring) == 64 && decode(key->valuestring, config.key, 32)) {
            strcpy(config.ssid, ssid->valuestring); strcpy(config.password, password->valuestring);
            nvs_handle_t nvs;
            err = nvs_open("passport_lan", NVS_READWRITE, &nvs);
            if (err == ESP_OK) {
                err = nvs_set_blob(nvs, "config", &config, sizeof(config));
                if (err == ESP_OK) err = nvs_commit(nvs);
                nvs_close(nvs);
            }
        }
        memset(&config, 0, sizeof(config));
    }
    cJSON_Delete(json);
    printf("FAP_LAN {\"saved\":%s}\n", err == ESP_OK ? "true" : "false");
    fflush(stdout);
    if (err == ESP_OK) { vTaskDelay(pdMS_TO_TICKS(500)); esp_restart(); }
    return true;
}

/* Setup is a separate boot mode: no BLE, LAN listener or router association.
 * Only the WPA2-protected device hotspot exposes these HTTP endpoints. */
extern const char portal_start[] asm("_binary_lan_setup_html_start");
extern const char portal_end[] asm("_binary_lan_setup_html_end");

static bool portal_authorized(httpd_req_t *req)
{
    char token[33];
    return httpd_req_get_hdr_value_str(req, "X-Passport-Token", token, sizeof(token)) == ESP_OK &&
           strcmp(token, s_setup_token) == 0;
}
static esp_err_t portal_json(httpd_req_t *req, const char *body)
{
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    httpd_resp_set_hdr(req, "X-Content-Type-Options", "nosniff");
    return httpd_resp_sendstr(req, body);
}
static esp_err_t portal_index(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    httpd_resp_set_hdr(req, "X-Frame-Options", "DENY");
    httpd_resp_set_hdr(req, "Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'");
    return httpd_resp_send(req, portal_start, portal_end - portal_start - 1);
}
static esp_err_t portal_session(httpd_req_t *req)
{
    char result[64];
    snprintf(result, sizeof(result), "{\"token\":\"%s\"}", s_setup_token);
    return portal_json(req, result);
}
static esp_err_t portal_scan(httpd_req_t *req)
{
    if (!portal_authorized(req)) return httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "Open the setup page first");
    wifi_scan_config_t scan = {.show_hidden=false};
    if (esp_wifi_scan_start(&scan, true) != ESP_OK)
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Scan unavailable; enter SSID manually");
    uint16_t count = 12;
    wifi_ap_record_t *records = calloc(count, sizeof(*records));
    if (!records) { esp_wifi_clear_ap_list(); return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Low memory"); }
    esp_err_t err = esp_wifi_scan_get_ap_records(&count, records);
    cJSON *list = cJSON_CreateArray();
    if (err == ESP_OK && list) {
        for (unsigned i=0; i<count; ++i) {
            records[i].ssid[32] = 0;
            cJSON *entry = cJSON_CreateObject();
            if (!entry) break;
            cJSON_AddStringToObject(entry, "ssid", (char *)records[i].ssid);
            cJSON_AddNumberToObject(entry, "rssi", records[i].rssi);
            cJSON_AddBoolToObject(entry, "open", records[i].authmode == WIFI_AUTH_OPEN);
            cJSON_AddItemToArray(list, entry);
        }
    }
    free(records);
    char *body = list && err == ESP_OK ? cJSON_PrintUnformatted(list) : NULL;
    cJSON_Delete(list);
    esp_err_t sent = body ? portal_json(req, body) : httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Scan failed");
    free(body);
    return sent;
}
static esp_err_t portal_save(httpd_req_t *req)
{
    if (!portal_authorized(req)) return httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "Invalid setup session");
    char body[512];
    if (req->content_len == 0 || req->content_len >= sizeof(body))
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid form size");
    size_t used = 0;
    while (used < req->content_len) {
        int n = httpd_req_recv(req, body+used, req->content_len-used);
        if (n <= 0) { memset(body, 0, sizeof(body)); return ESP_FAIL; }
        used += n;
    }
    body[used] = 0;
    cJSON *json = parse_flat_object(body);
    const cJSON *ssid = cJSON_GetObjectItemCaseSensitive(json, "ssid");
    const cJSON *pass = cJSON_GetObjectItemCaseSensitive(json, "password");
    lan_config_t config = {.magic=0x4c414e31};
    bool valid = cJSON_IsString(ssid) && cJSON_IsString(pass) &&
        strlen(ssid->valuestring) > 0 && strlen(ssid->valuestring) <= 32 &&
        (strlen(pass->valuestring) == 0 || strlen(pass->valuestring) >= 8) && strlen(pass->valuestring) <= 63;
    esp_err_t err = ESP_ERR_INVALID_ARG;
    if (valid) {
        strcpy(config.ssid, ssid->valuestring);
        strcpy(config.password, pass->valuestring);
        memcpy(config.key, s_config.key, sizeof(config.key));
        nvs_handle_t nvs;
        err = nvs_open("passport_lan", NVS_READWRITE, &nvs);
        if (err == ESP_OK) {
            err = nvs_set_blob(nvs, "config", &config, sizeof(config));
            if (err == ESP_OK) err = nvs_commit(nvs);
            nvs_close(nvs);
        }
    }
    cJSON_Delete(json);
    memset(body, 0, sizeof(body)); memset(&config, 0, sizeof(config));
    if (err != ESP_OK) return httpd_resp_send_err(req, valid ? HTTPD_500_INTERNAL_SERVER_ERROR : HTTPD_400_BAD_REQUEST,
                                                "Not saved; check SSID and password length");
    atomic_store(&s_setup_saved, true);
    return portal_json(req, "{\"saved\":true}");
}
static esp_err_t portal_key(httpd_req_t *req)
{
    if (!portal_authorized(req) || !atomic_load(&s_setup_saved))
        return httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "Save network first");
    char key[65], body[100];
    encode(s_config.key, key, 32);
    snprintf(body, sizeof(body), "{\"key\":\"%s\",\"port\":8765}", key);
    esp_err_t err = portal_json(req, body);
    memset(key, 0, sizeof(key)); memset(body, 0, sizeof(body));
    return err;
}
static esp_err_t portal_restart(httpd_req_t *req)
{
    if (!portal_authorized(req)) return httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "Invalid setup session");
    esp_err_t err = portal_json(req, "{\"restarting\":true}");
    atomic_store(&s_setup_exit, true);
    return err;
}
static void setup_timeout_task(void *arg)
{
    (void)arg;
    for (unsigned i=0; i<600 && !atomic_load(&s_setup_exit); ++i) vTaskDelay(pdMS_TO_TICKS(1000));
    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_restart();
}
esp_err_t buddy_lan_start_setup(void)
{
    (void)buddy_lan_configured();
    (void)esp_bt_controller_mem_release(ESP_BT_MODE_BLE);
    esp_err_t err = esp_netif_init();
    if (err != ESP_OK) return err;
    err = esp_event_loop_create_default();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) return err;
    if (!esp_netif_create_default_wifi_ap() || !esp_netif_create_default_wifi_sta()) return ESP_ERR_NO_MEM;
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    err = esp_wifi_init(&init); if (err != ESP_OK) return err;
    /* Enable RF entropy before generating secrets. STA has no connect handler;
     * it does not associate with any network during this brief initialization. */
    err = esp_wifi_set_storage(WIFI_STORAGE_RAM);
    if (err == ESP_OK) err = esp_wifi_set_mode(WIFI_MODE_STA);
    if (err == ESP_OK) err = esp_wifi_start();
    if (err != ESP_OK) return err;
    uint8_t random[16];
    esp_fill_random(random, sizeof(random)); encode(random, s_setup_token, 16);
    esp_fill_random(random, 6); encode(random, s_setup_password, 6);
    if (!s_configured) esp_fill_random(s_config.key, sizeof(s_config.key));
    err = esp_wifi_stop(); if (err != ESP_OK) return err;
    wifi_config_t ap = {.ap={.ssid="Passport Setup", .ssid_len=14, .channel=1,
                            .authmode=WIFI_AUTH_WPA2_PSK, .max_connection=2}};
    memcpy(ap.ap.password, s_setup_password, 12);
    err = esp_wifi_set_storage(WIFI_STORAGE_RAM);
    if (err == ESP_OK) err = esp_wifi_set_mode(WIFI_MODE_APSTA);
    if (err == ESP_OK) err = esp_wifi_set_config(WIFI_IF_AP, &ap);
    if (err == ESP_OK) err = esp_wifi_start();
    if (err != ESP_OK) return err;
    httpd_config_t http = HTTPD_DEFAULT_CONFIG();
    http.stack_size = 6144;
    http.max_open_sockets = 2;
    http.lru_purge_enable = true;
    http.recv_wait_timeout = 5;
    http.send_wait_timeout = 5;
    httpd_handle_t server = NULL;
    err = httpd_start(&server, &http); if (err != ESP_OK) return err;
    const httpd_uri_t routes[] = {
        {.uri="/", .method=HTTP_GET, .handler=portal_index},
        {.uri="/session", .method=HTTP_GET, .handler=portal_session},
        {.uri="/scan", .method=HTTP_GET, .handler=portal_scan},
        {.uri="/save", .method=HTTP_POST, .handler=portal_save},
        {.uri="/key", .method=HTTP_GET, .handler=portal_key},
        {.uri="/restart", .method=HTTP_POST, .handler=portal_restart},
    };
    for (unsigned i=0; i<sizeof(routes)/sizeof(routes[0]); ++i) {
        err = httpd_register_uri_handler(server, &routes[i]);
        if (err != ESP_OK) return err;
    }
    if (xTaskCreate(setup_timeout_task, "setup_timeout", 2048, NULL, 2, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    s_setup = true;
    ESP_LOGI(TAG, "Setup hotspot ready; closes after 10 minutes");
    return ESP_OK;
}
