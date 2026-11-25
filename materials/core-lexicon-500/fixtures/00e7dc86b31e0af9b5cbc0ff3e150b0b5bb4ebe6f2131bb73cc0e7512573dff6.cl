: generated(sym).
: verified(sym).
: locked(sym).
& a generated(case1).
verified($x) <- generated($x).
locked($x) <- verified($x).
? locked(case1).
? locked(case2).
