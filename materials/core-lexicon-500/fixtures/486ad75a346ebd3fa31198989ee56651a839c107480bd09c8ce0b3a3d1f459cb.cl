: contract_term(sym,i64).
: few(sym).
& a contract_term(case1,2).
& b contract_term(case2,5).
few($x) <- contract_term($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
