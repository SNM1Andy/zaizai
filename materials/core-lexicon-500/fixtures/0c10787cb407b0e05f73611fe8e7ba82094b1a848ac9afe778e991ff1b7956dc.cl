: slot_count(sym,i64).
: few(sym).
& a slot_count(case1,2).
& b slot_count(case2,5).
few($x) <- slot_count($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
