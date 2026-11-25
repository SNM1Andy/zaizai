: generated(sym).
: signed(sym).
: verified(sym).
& a generated(case1).
signed($x) <- generated($x).
verified($x) <- signed($x).
? verified(case1).
? verified(case2).
