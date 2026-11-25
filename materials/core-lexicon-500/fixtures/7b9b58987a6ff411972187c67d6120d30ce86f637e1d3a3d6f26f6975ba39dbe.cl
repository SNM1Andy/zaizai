: deadline_ts(sym,i64).
: early(sym).
& a deadline_ts(case1,20250101).
& b deadline_ts(case2,20260101).
early($x) <- deadline_ts($x,$v) & int_le($v,20250601).
? early(case1).
? early(case2).
