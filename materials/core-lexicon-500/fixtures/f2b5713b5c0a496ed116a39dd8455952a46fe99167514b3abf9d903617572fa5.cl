: cpu(sym,i64).
: small(sym).
& a cpu(pod1,2).
& b cpu(pod2,5).
small($x) <- cpu($x,$v) & int_le($v,3).
? small(pod1).
? small(pod2).
