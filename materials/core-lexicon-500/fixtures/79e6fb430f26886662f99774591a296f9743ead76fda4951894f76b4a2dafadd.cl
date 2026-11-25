: event_ticket(sym,qty(cny_cent)).
: small(sym).
& a event_ticket(case1,700@cny_cent).
& b event_ticket(case2,1400@cny_cent).
small($x) <- event_ticket($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
