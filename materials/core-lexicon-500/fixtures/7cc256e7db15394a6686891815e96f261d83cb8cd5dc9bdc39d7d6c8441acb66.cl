: trace_span(sym,i64).
: few(sym).
& a trace_span(case1,2).
& b trace_span(case2,5).
few($x) <- trace_span($x,$v) & int_le($v,3).
? few(case1).
? few(case2).
