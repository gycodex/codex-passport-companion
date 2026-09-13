#include <assert.h>
#include "buddy_pair_gate.h"

int main(void)
{
    buddy_pair_gate_t gate = {.id=7, .code=123456, .deadline_ms=30000};
    assert(buddy_pair_gate_live(&gate, 29999));
    assert(!buddy_pair_gate_live(&gate, 30000));
    assert(!buddy_pair_gate_decide(&gate, 6, true, 1000));
    assert(!gate.approved);
    assert(!buddy_pair_gate_decide(&gate, 7, true, 30000));
    assert(buddy_pair_gate_decide(&gate, 7, true, 29999));
    assert(!buddy_pair_gate_decide(&gate, 7, true, 29999));
    assert(!buddy_pair_gate_decide(&gate, 7, false, 29999));
    gate = (buddy_pair_gate_t){.id=8, .deadline_ms=40000};
    assert(!buddy_pair_gate_decide(&gate, 7, true, 30001));
    assert(buddy_pair_gate_decide(&gate, 8, false, 30001));
    assert(!buddy_pair_gate_live(&gate, 30002));
    assert(!buddy_pair_gate_decide(&gate, 8, true, 30002));
    gate.id = 0;
    assert(!buddy_pair_gate_live(&gate, 0));
    return 0;
}
