#include <assert.h>
#include "buddy_alert.h"

int main(void)
{
    const int64_t day = 86400;
    assert(!buddy_alert_allowed(BUDDY_SOUND_OFF, day + 12 * 3600, 0, 0, 0));
    assert(buddy_alert_allowed(BUDDY_SOUND_ON, 0, 0, 0, 0));
    assert(!buddy_alert_allowed(BUDDY_SOUND_AUTO, 0, 0, 0, 0));
    assert(!buddy_alert_allowed(BUDDY_SOUND_AUTO, day + 8 * 3600 - 1, 0, 0, 0));
    assert(buddy_alert_allowed(BUDDY_SOUND_AUTO, day + 8 * 3600, 0, 0, 0));
    assert(buddy_alert_allowed(BUDDY_SOUND_AUTO, day + 22 * 3600 - 1, 0, 0, 0));
    assert(!buddy_alert_allowed(BUDDY_SOUND_AUTO, day + 22 * 3600, 0, 0, 0));
    assert(buddy_alert_allowed(BUDDY_SOUND_AUTO, day, 8 * 3600, 0, 0));
    assert(!buddy_alert_allowed(BUDDY_SOUND_AUTO, day, -3 * 3600, 0, 3600000));
    assert(!buddy_alert_allowed(BUDDY_SOUND_AUTO, day + 21 * 3600, 0, 0, 3600000));
    assert(!buddy_alert_allowed(99, day + 12 * 3600, 0, 0, 0));
    return 0;
}
