: benchmark(sym,qty(cny_cent)).
: low(sym).
& a benchmark(case1,700@cny_cent).
& b benchmark(case2,1400@cny_cent).
low($x) <- benchmark($x,$c) & qty_le($c,1000@cny_cent).
? low(case1).
? low(case2).
