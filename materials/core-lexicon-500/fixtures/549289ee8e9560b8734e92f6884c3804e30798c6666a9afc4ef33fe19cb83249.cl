: ranking(sym,i64).
: good(sym).
& a ranking(case1,2).
& b ranking(case2,5).
good($x) <- ranking($x,$v) & int_le($v,3).
? good(case1).
? good(case2).
