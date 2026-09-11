#include <assert.h>
#include <string.h>
#include "buddy_usage.h"

int main(void)
{
    buddy_usage_window_t windows[2];
    buddy_codex_usage_t usage = {.available = true,
        .primary_window_minutes = 10080, .primary_used_percent = 36,
        .primary_resets_at = 1234};
    assert(buddy_usage_windows(&usage, windows) == 1);
    assert(strcmp(windows[0].label, "7 天") == 0);
    assert(windows[0].remaining == 64 && windows[0].resets_at == 1234);
    assert(windows[1].label[0] == '\0');
    usage.secondary_window_minutes = 10080;
    usage.secondary_used_percent = 100;
    usage.primary_window_minutes = 300;
    assert(buddy_usage_windows(&usage, windows) == 2);
    assert(strcmp(windows[0].label, "5 小时") == 0);
    assert(windows[1].remaining == 0);
    usage.primary_window_minutes = 0;
    assert(buddy_usage_windows(&usage, windows) == 1);
    assert(strcmp(windows[0].label, "7 天") == 0);
    usage.secondary_window_minutes = 90;
    assert(buddy_usage_windows(&usage, windows) == 1);
    assert(strcmp(windows[0].label, "90 分钟") == 0);
    usage.secondary_window_minutes = 0;
    assert(buddy_usage_windows(&usage, windows) == 0);
    usage.primary_window_minutes = 300;
    usage.available = false;
    assert(buddy_usage_windows(&usage, windows) == 0);
    return 0;
}
