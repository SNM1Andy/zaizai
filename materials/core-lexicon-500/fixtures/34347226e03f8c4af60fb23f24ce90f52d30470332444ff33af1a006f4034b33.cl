: prepared(sym).
: signed(sym).
: effective(sym).
& a prepared(case1).
signed($x) <- prepared($x).
effective($x) <- signed($x).
? effective(case1).
? effective(case2).
