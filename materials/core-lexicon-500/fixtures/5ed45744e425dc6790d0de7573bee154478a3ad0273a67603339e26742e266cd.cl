: start(i64).
: result(i64).
& a start(42).
result($v) <- start($x) & int_sub($x,2,$v).
? result(40).
