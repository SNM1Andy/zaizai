: retention(sym,i64).
: short(sym).
& a retention(policy1,2).
& b retention(policy2,5).
short($x) <- retention($x,$v) & int_le($v,3).
? short(policy1).
? short(policy2).
