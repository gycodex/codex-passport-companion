#include "buddy_ui.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

#include "buddy_i4.h"
#include "buddy_usage.h"
#include "buddy_font_zh.h"
#include "buddy_sprite.h"
#include "buddy_text_layout.h"
#include "lvgl.h"

#define UI_W 240
#define UI_H 320
#define COL_BG lv_color_hex(0x080A0C)
#define COL_INK lv_color_hex(0xF7E9D7)
#define COL_DIM lv_color_hex(0x8B8178)
#define COL_LINE lv_color_hex(0x39332F)
#define COL_ORANGE lv_color_hex(0xE17B52)
#define COL_RED lv_color_hex(0xEF4B38)
#define COL_GREEN lv_color_hex(0x64C987)
#define COL_YELLOW lv_color_hex(0xF1C75B)
#define COL_BLUE lv_color_hex(0x72A7D8)

static lv_obj_t *s_screen;
static lv_obj_t *s_canvas;
static LV_ATTRIBUTE_MEM_ALIGN uint8_t s_canvas_buffer[
    LV_DRAW_BUF_SIZE(UI_W, UI_H, LV_COLOR_FORMAT_I4)];
static buddy_ui_snapshot_t s_snapshot;
static bool s_have_snapshot;
static uint32_t s_tick;
static uint64_t s_elapsed_ms;
static int s_scroll;
static buddy_i4_surface_t s_surface;

#define I4_PALETTE_BYTES (16U * sizeof(lv_color32_t))

static const uint32_t s_palette_rgb[] = {0x080A0C, 0xF7E9D7, 0x8B8178, 0x39332F,
    0xE17B52, 0xEF4B38, 0x64C987, 0xF1C75B, 0x72A7D8, 0xFFFFFF,
    0xD97757, 0xA96349, 0xB48EAD, 0x81A1C1, 0xEBCB8B, 0x151719};

static uint8_t color_index(lv_color_t color)
{
    uint32_t rgb = lv_color_to_int(color);
    uint32_t best_distance = UINT32_MAX;
    uint8_t best = 0;
    uint8_t i;
    for (i = 0; i < sizeof(s_palette_rgb) / sizeof(s_palette_rgb[0]); ++i) {
        int dr = (int)((rgb >> 16) & 0xffU) - (int)((s_palette_rgb[i] >> 16) & 0xffU);
        int dg = (int)((rgb >> 8) & 0xffU) - (int)((s_palette_rgb[i] >> 8) & 0xffU);
        int db = (int)(rgb & 0xffU) - (int)(s_palette_rgb[i] & 0xffU);
        uint32_t distance = (uint32_t)(dr * dr + dg * dg + db * db);
        if (distance < best_distance) {
            best_distance = distance;
            best = i;
        }
    }
    return best;
}

static void pixel(int x, int y, uint8_t index)
{
    if ((unsigned)x >= UI_W || (unsigned)y >= UI_H) return;
    buddy_i4_set_pixel(s_canvas_buffer + I4_PALETTE_BYTES, UI_W,
                       (uint16_t)x, (uint16_t)y, index);
}

static size_t utf8_decode(const char *text, size_t remaining, uint32_t *codepoint)
{
    const uint8_t *s = (const uint8_t *)text;
    if (remaining == 0U) return 0U;
    if (s[0] < 0x80U) {
        *codepoint = s[0];
        return 1U;
    }
    if (remaining >= 2U && (s[0] & 0xe0U) == 0xc0U && (s[1] & 0xc0U) == 0x80U) {
        *codepoint = ((uint32_t)(s[0] & 0x1fU) << 6) | (uint32_t)(s[1] & 0x3fU);
        return 2U;
    }
    if (remaining >= 3U && (s[0] & 0xf0U) == 0xe0U &&
        (s[1] & 0xc0U) == 0x80U && (s[2] & 0xc0U) == 0x80U) {
        *codepoint = ((uint32_t)(s[0] & 0x0fU) << 12) |
                     ((uint32_t)(s[1] & 0x3fU) << 6) | (uint32_t)(s[2] & 0x3fU);
        return 3U;
    }
    *codepoint = '?';
    return 1U;
}

static void glyph(int x, int y, uint8_t index, const lv_font_t *font, uint32_t codepoint)
{
    lv_font_glyph_dsc_t dsc;
    const uint8_t *bitmap;
    unsigned row;
    unsigned col;
    if (!lv_font_get_glyph_dsc(font, &dsc, codepoint, 0) || dsc.box_w == 0 || dsc.box_h == 0) return;
    dsc.req_raw_bitmap = 1;
    bitmap = dsc.resolved_font->get_glyph_bitmap(&dsc, NULL);
    if (!bitmap || (dsc.format != LV_FONT_GLYPH_FORMAT_A1 &&
                    dsc.format != LV_FONT_GLYPH_FORMAT_A4)) return;
    y += font->line_height - font->base_line - dsc.box_h - dsc.ofs_y;
    x += dsc.ofs_x;
    for (row = 0; row < dsc.box_h; ++row) {
        for (col = 0; col < dsc.box_w; ++col) {
            uint32_t sample = row * dsc.box_w + col;
            bool visible = dsc.format == LV_FONT_GLYPH_FORMAT_A1
                               ? (bitmap[sample >> 3] & (0x80U >> (sample & 7U))) != 0
                               : (((sample & 1U) == 0U ? bitmap[sample >> 1] >> 4
                                                       : bitmap[sample >> 1] & 0x0fU) >= 4U);
            if (visible) pixel(x + col, y + row, index);
        }
    }
}

static void text_limited(lv_layer_t *layer, int x, int y, int width, lv_color_t color,
                         const char *value, bool large, lv_text_align_t align,
                         unsigned max_lines)
{
    const lv_font_t *font = large ? &buddy_font_zh_16 : &buddy_font_zh_14;
    int spacing = large ? 1 : 0;
    int line_step = font->line_height + (large ? 2 : 1);
    uint8_t index = color_index(color);
    const char *cursor = value;
    unsigned lines = 0;
    (void)layer;
    while (*cursor && y < UI_H && lines < max_lines) {
        const char *end = strchr(cursor, '\n');
        size_t length = end ? (size_t)(end - cursor) : strlen(cursor);
        size_t fit = 0;
        size_t offset = 0;
        int measured = 0;
        while (offset < length) {
            lv_font_glyph_dsc_t dsc;
            uint32_t codepoint;
            size_t consumed = utf8_decode(cursor + offset, length - offset, &codepoint);
            int advance = lv_font_get_glyph_dsc(font, &dsc, codepoint, 0)
                              ? dsc.adv_w + spacing : 0;
            if (fit > 0U && measured + advance > width) break;
            measured += advance;
            offset += consumed;
            fit = offset;
        }
        if (measured > 0) measured -= spacing;
        int pen = x;
        if (align == LV_TEXT_ALIGN_CENTER) pen += (width - measured) / 2;
        else if (align == LV_TEXT_ALIGN_RIGHT) pen += width - measured;
        offset = 0;
        while (offset < fit) {
            lv_font_glyph_dsc_t dsc;
            uint32_t codepoint;
            size_t consumed = utf8_decode(cursor + offset, fit - offset, &codepoint);
            glyph(pen, y, index, font, codepoint);
            if (lv_font_get_glyph_dsc(font, &dsc, codepoint, 0)) pen += dsc.adv_w + spacing;
            offset += consumed;
        }
        y += line_step;
        lines++;
        if (fit < length) cursor += fit;
        else cursor = end ? end + 1 : cursor + length;
    }
}

static void text(lv_layer_t *layer, int x, int y, int width, lv_color_t color,
                 const char *value, bool large, lv_text_align_t align)
{
    text_limited(layer, x, y, width, color, value, large, align, UINT32_MAX);
}

static void wrapped_text(lv_layer_t *layer, int x, int y, int width, lv_color_t color,
                         const char *value, unsigned max_lines)
{
    text_limited(layer, x, y, width, color, value, false, LV_TEXT_ALIGN_LEFT, max_lines);
}

static void box(lv_layer_t *layer, int x, int y, int w, int h, lv_color_t fill,
                lv_color_t border, int border_width, int radius)
{
    uint8_t fill_index = color_index(fill);
    uint8_t border_index = color_index(border);
    int px;
    int py;
    (void)layer;
    (void)radius;
    for (py = 0; py < h; ++py) {
        for (px = 0; px < w; ++px) {
            bool edge = px < border_width || py < border_width ||
                        px >= w - border_width || py >= h - border_width;
            pixel(x + px, y + py, edge ? border_index : fill_index);
        }
    }
}

static void rule(lv_layer_t *layer, int x, int y, int w, lv_color_t color)
{
    box(layer, x, y, w, 1, color, color, 0, 0);
}

static uint8_t art_state(buddy_character_t state)
{
    switch (state) {
    case BUDDY_CHARACTER_SLEEP: return 0;
    case BUDDY_CHARACTER_BUSY: return 2;
    case BUDDY_CHARACTER_ATTENTION:
    case BUDDY_CHARACTER_PAIRING:
    case BUDDY_CHARACTER_CONFIRMATION: return 3;
    case BUDDY_CHARACTER_CELEBRATE: return 4;
    case BUDDY_CHARACTER_DIZZY: return 5;
    case BUDDY_CHARACTER_HEART: return 6;
    default: return 1;
    }
}

static void draw_buddy(lv_layer_t *layer, const buddy_ui_snapshot_t *s, bool peek)
{
    buddy_i4_clip_t clip = {.x = 0, .y = BUDDY_UI_STAGE_Y,
                            .w = UI_W, .h = BUDDY_UI_STAGE_H};
    buddy_sprite_bounds_t bounds;
    int x = 88;
    int y = peek ? 72 : 65;
    (void)layer;
    if (buddy_sprite_bounds(s->species, art_state(s->character), s_tick, &bounds)) {
        x = (UI_W - bounds.w) / 2 - bounds.x;
    }
    buddy_sprite_render(&s_surface, &clip, s->species, art_state(s->character),
                        s_tick, x, y);
}

static void draw_status_bar(lv_layer_t *layer, const buddy_ui_snapshot_t *s)
{
    char left[32];
    char center[32];
    char battery[32];
    lv_color_t battery_color = COL_DIM;
    uint64_t age_ms = s_elapsed_ms >= s->time_received_ms ? s_elapsed_ms - s->time_received_ms : 0;
    time_t epoch = (time_t)(s->epoch_seconds + s->timezone_offset_seconds + age_ms / 1000U);
    struct tm tm_value;

    snprintf(left, sizeof(left), "%s", s->lan_connected ? "已连接LAN" :
             (s->ble_connected ? "已连接BLE" : "未连接"));
    if (s->epoch_seconds > 0 && gmtime_r(&epoch, &tm_value) != NULL) {
        snprintf(center, sizeof(center), "%02d:%02d", tm_value.tm_hour, tm_value.tm_min);
    } else {
        snprintf(center, sizeof(center), "%s", s->heartbeat_stale ? "休眠" : "在线");
    }
    if (s->battery_available) {
        snprintf(battery, sizeof(battery), "电量%u%%", (unsigned)s->battery_percent);
        battery_color = s->battery_percent <= 15U
                            ? COL_RED
                            : (s->battery_percent <= 35U ? COL_YELLOW : COL_GREEN);
    } else {
        snprintf(battery, sizeof(battery), "电量--");
    }
    text(layer, 8, 7, 80, (s->ble_connected || s->lan_connected) ? COL_GREEN : COL_DIM, left, false, LV_TEXT_ALIGN_LEFT);
    text(layer, 88, 7, 56, COL_DIM, center, false, LV_TEXT_ALIGN_CENTER);
    text(layer, 144, 7, 88, battery_color, battery, false, LV_TEXT_ALIGN_RIGHT);
    rule(layer, 8, 25, 224, COL_LINE);
}

static void draw_companion(lv_layer_t *layer, const buddy_ui_snapshot_t *s)
{
    char caption[176];
    text(layer, 10, 35, 220, COL_ORANGE, buddy_sprite_name(s->species), false,
         LV_TEXT_ALIGN_CENTER);
    draw_buddy(layer, s, false);
    rule(layer, 18, BUDDY_UI_INFO_Y, 204, COL_LINE);
    snprintf(caption, sizeof(caption), "%s", s->message[0] ? s->message :
             ((s->ble_connected || s->lan_connected) ? "助手已就绪" : "请启动电脑端桥接程序进行配对"));
    wrapped_text(layer, 18, 174, 204, s->heartbeat_stale ? COL_DIM : COL_INK,
                 caption, 8);
    text(layer, 8, 300, 224, COL_DIM, BUDDY_ACTION_HOME, false, LV_TEXT_ALIGN_CENTER);
}

static void usage_reset_text(char *destination, size_t size, uint64_t resets_at,
                             const buddy_ui_snapshot_t *s)
{
    uint64_t now = s->epoch_seconds > 0
                       ? (uint64_t)s->epoch_seconds +
                             (s_elapsed_ms >= s->time_received_ms
                                  ? (s_elapsed_ms - s->time_received_ms) / 1000U
                                  : 0U)
                       : 0U;
    uint64_t remaining = resets_at > now ? resets_at - now : 0U;

    if (resets_at == 0U || now == 0U) {
        snprintf(destination, size, "重置时间：--");
    } else if (remaining >= 86400U) {
        snprintf(destination, size, "距重置 %llu 天 %llu 小时",
                 (unsigned long long)(remaining / 86400U),
                 (unsigned long long)((remaining % 86400U) / 3600U));
    } else {
        snprintf(destination, size, "距重置 %llu 小时 %02llu 分",
                 (unsigned long long)(remaining / 3600U),
                 (unsigned long long)((remaining % 3600U) / 60U));
    }
}

static void draw_home_companion(lv_layer_t *layer, const buddy_ui_snapshot_t *s, bool compact)
{
    const buddy_i4_clip_t clip = {.x = 16, .y = compact ? 204 : 180, .w = 208, .h = compact ? 66 : 78};
    buddy_sprite_bounds_t bounds;
    uint8_t state = s->voice_recording ? BUDDY_SPRITE_TALK : art_state(s->character);
    int x = 88;
    const char *caption = "准备就绪";
    lv_color_t color = COL_DIM;

    if (buddy_sprite_bounds(s->species, state, s_tick, &bounds)) {
        x = (UI_W - bounds.w) / 2 - bounds.x;
    }
    rule(layer, 96, compact ? 264 : 255, 48, COL_LINE);
    buddy_sprite_render(&s_surface, &clip, s->species, state,
                        s->voice_recording && s->voice_peak < 500 ? 0 : s_tick,
                        x, compact ? 198 : 188);
    if (s->voice_recording) {
        /* Audio-reactive bars flank every pet species without covering its face. */
        unsigned level = s->voice_peak / 350U;
        if (level > 28U) level = 28U;
        for (unsigned i = 0; i < 4; ++i) {
            unsigned height = 3U + level * (1U + (s_tick + i) % 4U) / 4U;
            int center = compact ? 238 : 220;
            for (unsigned side = 0; side < 2; ++side)
                box(layer, (side ? 176 : 36) + (int)i * 7, center - (int)height / 2,
                    4, (int)height, COL_GREEN, COL_GREEN, 0, 0);
        }
        caption = "语音输入中";
        color = COL_GREEN;
    } else if (!(s->ble_connected || s->lan_connected) || s->heartbeat_stale) {
        caption = "等待同步";
    } else if (!s->voice_recording && s->character == BUDDY_CHARACTER_CELEBRATE) {
        caption = "任务完成";
        color = COL_GREEN;
    } else if (s->running > 0U) {
        caption = "工作中…";
        color = COL_GREEN;
    }
    text(layer, 18, 266, 204, color, caption, false, LV_TEXT_ALIGN_CENTER);
}

static void draw_home(lv_layer_t *layer, const buddy_ui_snapshot_t *s)
{
    char value[64];
    char reset[32];
    buddy_usage_window_t windows[2];
    size_t count = buddy_usage_windows(&s->codex_usage, windows);
    bool compact = count == 2U;
    text(layer, 8, 38, 224, COL_ORANGE, "Codex 使用量", true, LV_TEXT_ALIGN_CENTER);
    snprintf(value, sizeof(value), "进行中：%u 个任务", s->running);
    text(layer, 8, 58, 224, s->running > 0 ? COL_GREEN : COL_DIM,
         value, false, LV_TEXT_ALIGN_CENTER);
    if (count == 0U) {
        wrapped_text(layer, 22, 113, 196, COL_INK,
                     "暂无用量数据。\n请保持桥接程序运行。", 5);
    }
    for (size_t index = 0; index < count; ++index) {
        const buddy_usage_window_t *window = &windows[index];
        int top = 80 + (int)index * (compact ? 64 : 98);
        lv_color_t color = index == 0U ? COL_GREEN : COL_YELLOW;
        box(layer, 8, top, 224, compact ? 58 : 91, lv_color_hex(0x151719), COL_LINE, 1, 3);
        text(layer, 18, top + (compact ? 4 : 13), 100, COL_INK, window->label,
             false, LV_TEXT_ALIGN_LEFT);
        snprintf(value, sizeof(value), "剩余 %u%%", window->remaining);
        text(layer, 116, top + (compact ? 4 : 13), 106, window->remaining < 20U ? COL_RED : color,
             value, false, LV_TEXT_ALIGN_RIGHT);
        for (unsigned i = 0; i < 10U; ++i) {
            bool on = i * 10U < window->remaining;
            box(layer, 18 + (int)i * 20, top + (compact ? 26 : 42), 16, compact ? 8 : 13, on ? color : COL_LINE,
                on ? color : COL_LINE, 0, 1);
        }
        usage_reset_text(reset, sizeof(reset), window->resets_at, s);
        text(layer, 18, top + (compact ? 39 : 67), 204, COL_DIM, reset, false, LV_TEXT_ALIGN_LEFT);
    }
    if (count > 0U || s->voice_recording) draw_home_companion(layer, s, compact);
    if (s->voice_recording) {
        snprintf(value, sizeof(value), "%02u:%02u / 02:00  下键结束",
                 s->voice_seconds / 60U, s->voice_seconds % 60U);
        text(layer, 8, 297, 224, COL_GREEN, value, false, LV_TEXT_ALIGN_CENTER);
    } else {
        text(layer, 8, 284, 224, COL_DIM, "上键换页  下键语音", false, LV_TEXT_ALIGN_CENTER);
        text(layer, 8, 302, 224, COL_DIM, "长按确认菜单", false, LV_TEXT_ALIGN_CENTER);
    }
}

static void draw_info(lv_layer_t *layer, const buddy_ui_snapshot_t *s)
{
    static const char *const titles[] = {"关于", "按键说明", "用量状态", "设备信息", "蓝牙", "致谢"};
    char body[512];
    char page[16];
    unsigned p = s->info_page < 6 ? s->info_page : 0;
    text(layer, 14, 38, 180, COL_ORANGE, p == 4 ? "无线网络" : titles[p], true, LV_TEXT_ALIGN_LEFT);
    snprintf(page, sizeof(page), "%u / 6", p + 1);
    text(layer, 174, 43, 52, COL_DIM, page, false, LV_TEXT_ALIGN_RIGHT);
    rule(layer, 14, 66, 212, COL_LINE);
    switch (p) {
    case 0: snprintf(body, sizeof(body), "你的桌面伙伴。\n\n显示用量余量和任务完成提醒。"); break;
    case 1: snprintf(body, sizeof(body), "上键：切换界面\n下键：翻页或拒绝\n确认键：允许或更改\n首页下键：语音输入\n长按确认键：打开菜单"); break;
    case 2: {
        buddy_usage_window_t windows[2];
        size_t count = buddy_usage_windows(&s->codex_usage, windows);
        size_t used = (size_t)snprintf(body, sizeof(body),
            "任务：%u\n进行中：%u\n", s->total, s->running);
        if (count == 0U) {
            snprintf(body + used, sizeof(body) - used, "\n暂无用量数据。");
        }
        for (size_t i = 0; i < count && used < sizeof(body); ++i) {
            int written = snprintf(body + used, sizeof(body) - used,
                "\n%s 剩余：%u%%", windows[i].label, windows[i].remaining);
            if (written < 0) break;
            used += (size_t)written;
        }
        break;
    }
    case 3: snprintf(body, sizeof(body), "名称\n%s\n\n所有者\n%s\n\n屏幕：240 × 320", s->name[0] ? s->name : "Codex 助手", s->owner[0] ? s->owner : "-"); break;
    case 4: if (s->lan_setup) {
        snprintf(body, sizeof(body), "连接热点：\nPassport Setup\n\n密码：\n%s\n\nhttp://192.168.4.1\n\n10 分钟后关闭\n确认键：退出配网", s->lan_setup_password);
        break;
    } else if (s->lan_mode) {
        snprintf(body, sizeof(body), "无线网络\n\nIP：%s\n端口：8765\n\n%s\n\n确认键：无线配网",
                 s->lan_ip[0] ? s->lan_ip : "连接中…",
                 s->lan_connected ? "已加密连接" : "等待桥接连接");
        break;
    }
    snprintf(body, sizeof(body), "当前：蓝牙\n\n确认键：无线配网\n\n手机连接设备热点\n设置 2.4 GHz 无线网络。\n\n也可通过 USB 配网。"); break;
    default: snprintf(body, sizeof(body), "Codex 使用量助手\n\n适用于 FoloToy AI Passport\nESP32-C3 硬件\n\n基于公开的 Buddy 参考分支"); break;
    }
    wrapped_text(layer, 16, 82 - s_scroll, 208, COL_INK, body, 18);
    text(layer, 8, 300, 224, COL_DIM, BUDDY_ACTION_INFO, false, LV_TEXT_ALIGN_CENTER);
}

static void draw_list(lv_layer_t *layer, const char *title, const char *const *items,
                      unsigned count, unsigned selected, const buddy_ui_snapshot_t *s)
{
    unsigned first = selected > 5 ? selected - 5 : 0;
    unsigned i;
    text(layer, 14, 34, 212, COL_ORANGE, title, true, LV_TEXT_ALIGN_LEFT);
    rule(layer, 14, 62, 212, COL_LINE);
    for (i = first; i < count && i < first + 7; ++i) {
        int y = 76 + (int)(i - first) * 29;
        bool active = i == selected;
        char row[64];
        const char *suffix = "";
        char value[12];
        if (!s->reset_open && i == BUDDY_SETTINGS_BRIGHTNESS) { snprintf(value, sizeof(value), "%u/4", s->brightness_level); suffix = value; }
        else if (!s->reset_open && i == BUDDY_SETTINGS_SOUND) suffix = s->sound_mode == BUDDY_SOUND_OFF ? "关闭" : (s->sound_mode == BUDDY_SOUND_ON ? "开启" : "自动");
        else if (!s->reset_open && i == BUDDY_SETTINGS_SLEEP) {
            static const char *const modes[] = {"1 分钟", "5 分钟", "10 分钟", "永不"};
            suffix = modes[s->sleep_mode < BUDDY_SLEEP_COUNT ? s->sleep_mode : BUDDY_SLEEP_5_MIN];
        }
        else if (!s->reset_open && i == BUDDY_SETTINGS_WIFI) suffix = s->lan_mode ? "开" : "关";
        else if (!s->reset_open && i == BUDDY_SETTINGS_BLE) suffix = s->ble_enabled ? "开" : "关";
        else if (!s->reset_open && i == BUDDY_SETTINGS_ASCII_PET) suffix = buddy_sprite_name(s->species);
        snprintf(row, sizeof(row), "%s", items[i]);
        if (active) box(layer, 12, y - 7, 216, 24, COL_ORANGE, COL_ORANGE, 0, 3);
        text(layer, 20, y, 142, active ? COL_BG : COL_INK, row, false, LV_TEXT_ALIGN_LEFT);
        text(layer, 158, y, 62, active ? COL_BG : COL_DIM, suffix, false, LV_TEXT_ALIGN_RIGHT);
    }
    text(layer, 8, 300, 224, COL_DIM, BUDDY_ACTION_SETTINGS, false, LV_TEXT_ALIGN_CENTER);
}

static void draw_settings(lv_layer_t *layer, const buddy_ui_snapshot_t *s)
{
    static const char *const settings[] = {"屏幕亮度", "声音", "自动睡眠", "蓝牙", "Wi-Fi", "无线网络", "伙伴形象", "重置", "返回"};
    static const char *const reset[] = {"恢复出厂设置", "解除蓝牙配对", "返回"};
    _Static_assert(sizeof(settings) / sizeof(settings[0]) == BUDDY_SETTINGS_COUNT,
                   "Settings labels must match navigation");
    _Static_assert(sizeof(reset) / sizeof(reset[0]) == BUDDY_RESET_COUNT,
                   "Reset labels must match navigation");
    draw_list(layer, s->reset_open ? "重置" : "设置", s->reset_open ? reset : settings,
              s->reset_open ? BUDDY_RESET_COUNT : BUDDY_SETTINGS_COUNT,
              s->reset_open ? s->reset_selection : s->settings_selection, s);
}

static void panel(lv_layer_t *layer, int y, int h, lv_color_t accent, const char *title,
                  const char *body, const char *footer)
{
    box(layer, 10, y, 220, h, lv_color_hex(0x151719), accent, 2, 6);
    box(layer, 10, y, 220, 27, accent, accent, 0, 5);
    text(layer, 18, y + 8, 204, COL_BG, title, false, LV_TEXT_ALIGN_LEFT);
    wrapped_text(layer, 20, y + 42 - s_scroll, 200, COL_INK, body, 5);
    rule(layer, 20, y + h - 34, 200, COL_LINE);
    text(layer, 18, y + h - 23, 204, COL_DIM, footer, false, LV_TEXT_ALIGN_CENTER);
}

static void draw_overlay(lv_layer_t *layer, const buddy_ui_snapshot_t *s)
{
    char body[448];
    int x;
    int y;
    buddy_overlay_kind_t overlay = buddy_overlay_select(s->confirmation_pending,
                                                        s->passkey_visible,
                                                        s->prompt_id[0] != '\0',
                                                        s->menu_open);
    if (overlay != BUDDY_OVERLAY_NONE) {
        for (y = BUDDY_UI_STATUS_H; y < BUDDY_UI_ACTION_Y; ++y) {
            for (x = (y & 1); x < UI_W; x += 2) {
                uint8_t current = buddy_i4_get_pixel(s_surface.pixels, UI_W,
                                                     (uint16_t)x, (uint16_t)y);
                if (current != 0) buddy_i4_set_pixel(s_surface.pixels, UI_W,
                                                          (uint16_t)x, (uint16_t)y,
                                                          15);
            }
        }
    }
    if (overlay == BUDDY_OVERLAY_CONFIRMATION) {
        panel(layer, 62, 196, COL_RED, "确认操作",
              s->confirmation == BUDDY_CONFIRM_FACTORY_RESET ? "确定恢复出厂设置吗？\n\n全部设置和统计数据将被清除。" : "确定解除 Codex 桥接配对吗？\n\n已保存的蓝牙配对信息将被清除。",
              BUDDY_ACTION_CONFIRM);
    } else if (overlay == BUDDY_OVERLAY_PAIRING) {
        snprintf(body, sizeof(body), "请在电脑上输入此配对码\n\n       %06lu", (unsigned long)s->passkey);
        panel(layer, 66, 188, COL_BLUE, "蓝牙配对", body, "请保持此界面开启");
    } else if (overlay == BUDDY_OVERLAY_APPROVAL) {
        snprintf(body, sizeof(body), "%s\n\n%s", s->prompt_tool, s->prompt_hint);
        panel(layer, 154, 158, s->approval_locked ? COL_DIM : COL_RED, "助手请求授权", body,
              s->approval_locked ? (s->permission_delivery == BUDDY_PERMISSION_DELIVERY_FAILED ? "发送失败" : "正在发送……") : BUDDY_ACTION_APPROVAL);
    } else if (overlay == BUDDY_OVERLAY_MENU) {
        static const char *const menu[] = {"设置", "关闭屏幕", "帮助", "关于", "关闭菜单"};
        unsigned i;
        box(layer, 38, 48, 164, 74 + BUDDY_MENU_COUNT * 25, lv_color_hex(0x151719), COL_INK, 2, 5);
        text(layer, 52, 61, 136, COL_ORANGE, "菜单", true, LV_TEXT_ALIGN_CENTER);
        rule(layer, 52, 88, 136, COL_LINE);
        for (i = 0; i < BUDDY_MENU_COUNT; ++i) {
            int y = 103 + (int)i * 25;
            bool active = i == (unsigned)s->menu_selection;
            if (active) box(layer, 48, y - 7, 144, 21, COL_ORANGE, COL_ORANGE, 0, 2);
            text(layer, 56, y, 128, active ? COL_BG : COL_INK, menu[i], false, LV_TEXT_ALIGN_CENTER);
        }
    } else if (!s->voice_recording && s->character == BUDDY_CHARACTER_CELEBRATE) {
        buddy_usage_window_t windows[2];
        /* The single-window home already celebrates through its pet and caption. */
        if (s->page != BUDDY_PAGE_HOME || buddy_usage_windows(&s->codex_usage, windows) != 1U) {
            panel(layer, 194, 86, COL_GREEN, "任务已完成",
                  "助手已完成当前任务。", "请在电脑上查看结果");
        }
    }
}

static void redraw(void)
{
    lv_layer_t *layer = NULL;
    if (!s_canvas || !s_have_snapshot) return;
    memset(s_canvas_buffer + I4_PALETTE_BYTES, 0, sizeof(s_canvas_buffer) - I4_PALETTE_BYTES);
    draw_status_bar(layer, &s_snapshot);
    switch (s_snapshot.page) {
    case BUDDY_PAGE_PET: draw_companion(layer, &s_snapshot); break;
    case BUDDY_PAGE_INFO: draw_info(layer, &s_snapshot); break;
    case BUDDY_PAGE_SETTINGS: draw_settings(layer, &s_snapshot); break;
    default: draw_home(layer, &s_snapshot); break;
    }
    draw_overlay(layer, &s_snapshot);
    lv_obj_invalidate(s_canvas);
}

void buddy_ui_init(void)
{
    unsigned i;
    if (s_screen) return;
    s_screen = lv_obj_create(NULL);
    lv_obj_set_size(s_screen, UI_W, UI_H);
    lv_obj_remove_flag(s_screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_pad_all(s_screen, 0, 0);
    lv_obj_set_style_border_width(s_screen, 0, 0);
    lv_obj_set_style_bg_color(s_screen, COL_BG, 0);
    s_canvas = lv_canvas_create(s_screen);
    lv_canvas_set_buffer(s_canvas, s_canvas_buffer, UI_W, UI_H, LV_COLOR_FORMAT_I4);
    lv_obj_set_pos(s_canvas, 0, 0);
    buddy_i4_surface_init(&s_surface, s_canvas_buffer + I4_PALETTE_BYTES,
                          UI_W, UI_H, UI_W / 2);
    for (i = 0; i < sizeof(s_palette_rgb) / sizeof(s_palette_rgb[0]); ++i)
        lv_canvas_set_palette(s_canvas, i, lv_color_to_32(lv_color_hex(s_palette_rgb[i]), LV_OPA_COVER));
    lv_screen_load(s_screen);
}

void buddy_ui_render(const buddy_ui_snapshot_t *snapshot)
{
    if (!snapshot) return;
    buddy_ui_init();
    s_snapshot = *snapshot;
    s_have_snapshot = true;
    s_scroll = 0;
    if (!snapshot->screen_off) redraw();
}

void buddy_ui_show_passkey(uint32_t passkey)
{
    buddy_ui_snapshot_t snapshot = {.passkey_visible = true, .passkey = passkey};
    buddy_ui_render(&snapshot);
}

void buddy_ui_tick(uint64_t elapsed_ms)
{
    uint32_t tick = (uint32_t)(elapsed_ms / 200U);
    s_elapsed_ms = elapsed_ms;
    if (tick != s_tick && !s_snapshot.screen_off) {
        s_tick = tick;
        redraw();
    }
}

void buddy_ui_scroll(int delta)
{
    s_scroll += delta;
    if (s_scroll < 0) s_scroll = 0;
    if (s_scroll > 160) s_scroll = 160;
    redraw();
}

bool buddy_ui_write_screenshot(FILE *stream)
{
    uint8_t row[UI_W * 2U];
    unsigned x;
    unsigned y;

    if (stream == NULL || !s_have_snapshot) {
        return false;
    }
    if (fprintf(stream, "FAP_SCREENSHOT_V1 %u %u RGB565LE %u\n",
                UI_W, UI_H, UI_W * UI_H * 2U) < 0) {
        return false;
    }
    for (y = 0; y < UI_H; ++y) {
        for (x = 0; x < UI_W; ++x) {
            uint8_t palette_index = buddy_i4_get_pixel(
                s_canvas_buffer + I4_PALETTE_BYTES, UI_W,
                (uint16_t)x, (uint16_t)y);
            uint32_t rgb = s_palette_rgb[palette_index & 0x0fU];
            uint16_t rgb565 = (uint16_t)(((rgb >> 8) & 0xf800U) |
                                         ((rgb >> 5) & 0x07e0U) |
                                         ((rgb >> 3) & 0x001fU));

            row[x * 2U] = (uint8_t)(rgb565 & 0xffU);
            row[x * 2U + 1U] = (uint8_t)(rgb565 >> 8);
        }
        if (fwrite(row, 1, sizeof(row), stream) != sizeof(row)) {
            return false;
        }
    }
    return fflush(stream) == 0;
}
