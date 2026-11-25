: marked(sym).
: purged(sym).
: verified(sym).
& a marked(case1).
purged($x) <- marked($x).
verified($x) <- purged($x).
? verified(case1).
? verified(case2).
