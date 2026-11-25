: commute(sym,qty(minute)).
: tolerable(sym).
& a commute(route1,30@minute).
& b commute(route2,90@minute).
tolerable($x) <- commute($x,$c) & qty_le($c,60@minute).
? tolerable(route1).
? tolerable(route2).
