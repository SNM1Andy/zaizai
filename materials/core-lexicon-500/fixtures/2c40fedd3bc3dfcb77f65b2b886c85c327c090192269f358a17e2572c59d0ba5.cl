: first_response(sym,qty(minute)).
: short(sym).
& a first_response(case1,700@minute).
& b first_response(case2,1400@minute).
short($x) <- first_response($x,$c) & qty_le($c,1000@minute).
? short(case1).
? short(case2).
