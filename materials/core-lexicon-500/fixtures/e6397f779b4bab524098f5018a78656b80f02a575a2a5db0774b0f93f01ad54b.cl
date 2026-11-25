: response_sla(sym,qty(ms)).
: short(sym).
& a response_sla(case1,700@ms).
& b response_sla(case2,1400@ms).
short($x) <- response_sla($x,$c) & qty_le($c,1000@ms).
? short(case1).
? short(case2).
