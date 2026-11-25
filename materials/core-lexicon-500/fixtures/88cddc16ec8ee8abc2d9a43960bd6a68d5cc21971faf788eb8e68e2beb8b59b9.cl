: opened(sym).
: matched(sym).
: closed(sym).
& a opened(case1).
matched($x) <- opened($x).
closed($x) <- matched($x).
? closed(case1).
? closed(case2).
