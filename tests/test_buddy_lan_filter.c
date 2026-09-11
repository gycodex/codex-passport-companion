#include <assert.h>
#include <string.h>
#include "buddy_lan_filter.h"
int main(void)
{
    buddy_event_t event;
    const char *allowed = "{\"time\":[123,28800]}";
    assert(buddy_lan_parse(allowed, strlen(allowed), &event));
    assert(event.type == BUDDY_EVENT_TIME);
    const char *heartbeat = "{\"total\":1,\"running\":1,\"waiting\":0,\"msg\":\"working\","
        "\"entries\":[],\"tokens\":0,\"tokens_today\":0,\"codex\":{"
        "\"plan\":\"pro\",\"primary_used\":12,\"primary_window\":10080,"
        "\"primary_reset\":1,\"secondary_used\":0,\"secondary_window\":0,"
        "\"secondary_reset\":0,\"completion_seq\":7,\"available\":true}}";
    assert(buddy_lan_parse(heartbeat, strlen(heartbeat), &event));
    assert(event.heartbeat.running == 1 && event.heartbeat.codex_usage.completion_sequence == 7);
    const char *legacy = "{\"total\":1,\"running\":1,\"waiting\":0,\"msg\":\"working\","
        "\"entries\":[],\"tokens\":0,\"tokens_today\":0}";
    assert(!buddy_lan_parse(legacy, strlen(legacy), &event));
    const char *denied[] = {"{\"cmd\":\"status\"}", "{\"cmd\":\"unpair\"}",
                            "{\"name\":\"changed\"}", "{\"owner\":\"changed\"}", "{bad}",
                            "{\"time\":[123,28800]}junk"};
    for (unsigned i=0; i<sizeof(denied)/sizeof(denied[0]); ++i)
        assert(!buddy_lan_parse(denied[i], strlen(denied[i]), &event));
    return 0;
}
