: watermark(sym,qty(mib)).
: low(sym).
& a watermark(case1,700@mib).
& b watermark(case2,1400@mib).
low($x) <- watermark($x,$c) & qty_le($c,1000@mib).
? low(case1).
? low(case2).
