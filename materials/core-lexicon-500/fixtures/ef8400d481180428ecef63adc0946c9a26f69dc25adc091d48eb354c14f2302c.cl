: cause(sym).
: link(sym).
: effect(sym).
& a cause(case1).
link($x) <- cause($x).
effect($x) <- link($x).
? effect(case1).
? effect(case2).
