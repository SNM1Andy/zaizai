: budget(sym,qty(cny_cent)).
: ok(sym).
& a budget(pilot,1000@cny_cent).
ok($x) <- budget($x,$b) & qty_sub($b,$fee,$v) & qty_le($v,700@cny_cent).
? ok(pilot).
