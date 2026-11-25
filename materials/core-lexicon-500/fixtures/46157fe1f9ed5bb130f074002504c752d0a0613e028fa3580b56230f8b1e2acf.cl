: installments(sym,i64).
: few(sym).
& a installments(plan1,2).
& b installments(plan2,5).
few($x) <- installments($x,$v) & int_le($v,3).
? few(plan1).
? few(plan2).
