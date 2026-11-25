: temp(sym,i64).
: safe(sym).
& a temp(rack1,20).
& b temp(rack2,35).
safe($x) <- temp($x,$v) & int_le(18,$v) & int_lt($v,30).
? safe(rack1).
? safe(rack2).
