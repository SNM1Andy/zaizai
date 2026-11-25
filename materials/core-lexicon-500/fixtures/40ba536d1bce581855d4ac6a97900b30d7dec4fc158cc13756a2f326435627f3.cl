: probed(sym).
: healthy(sym).
: ready(sym).
& a probed(case1).
healthy($x) <- probed($x).
ready($x) <- healthy($x).
? ready(case1).
? ready(case2).
