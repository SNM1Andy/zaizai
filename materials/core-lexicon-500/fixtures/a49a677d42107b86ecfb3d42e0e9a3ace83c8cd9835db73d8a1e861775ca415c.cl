: start(i64).
: result(i64).
& a start(10).
result($y) <- start($x) & int_sub($x,3,$y).
? result(7).
