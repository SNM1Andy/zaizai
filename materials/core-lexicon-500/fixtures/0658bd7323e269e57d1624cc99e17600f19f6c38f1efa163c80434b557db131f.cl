: accumulated(sym,qty(hour)).
: within_quota(sym).
& a accumulated(case1,30@hour).
within_quota($x) <- accumulated($x,$c) & qty_add($c,10@hour,$t) & qty_le($t,40@hour).
? within_quota(case1).
? within_quota(case2).
