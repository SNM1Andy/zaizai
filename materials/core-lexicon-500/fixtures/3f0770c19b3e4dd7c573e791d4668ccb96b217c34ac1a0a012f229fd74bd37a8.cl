: lead_time(sym,qty(day)).
: short(sym).
& a lead_time(order1,3@day).
& b lead_time(order2,9@day).
short($x) <- lead_time($x,$c) & qty_le($c,5@day).
? short(order1).
? short(order2).
