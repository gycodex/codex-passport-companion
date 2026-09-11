#include "buddy_lan_filter.h"
#include "buddy_protocol.h"

bool buddy_lan_parse(const char *json, size_t length, buddy_event_t *event)
{
    int parsed = buddy_protocol_parse(json, length, event);
    if (parsed == BUDDY_EVENT_TIME) return true;
    /* LAN is a usage display transport, not a remote approval/admin channel. */
    return parsed == BUDDY_EVENT_HEARTBEAT && event->heartbeat.codex_usage.present &&
           event->heartbeat.prompt.id[0] == '\0';
}
