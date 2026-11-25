: slo(sym,qty(ms)).
: met(sym).
& a slo(case1,700@ms).
& b slo(case2,1400@ms).
met($x) <- slo($x,$c) & qty_le($c,1000@ms).
? met(case1).
? met(case2).
