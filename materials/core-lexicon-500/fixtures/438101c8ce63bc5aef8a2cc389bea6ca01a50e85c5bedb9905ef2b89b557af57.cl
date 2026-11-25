: commute_time(sym,qty(minute)).
: acceptable(sym).
& a commute_time(route1,30@minute).
& b commute_time(route2,90@minute).
acceptable($x) <- commute_time($x,$c) & qty_le($c,60@minute).
? acceptable(route1).
? acceptable(route2).
