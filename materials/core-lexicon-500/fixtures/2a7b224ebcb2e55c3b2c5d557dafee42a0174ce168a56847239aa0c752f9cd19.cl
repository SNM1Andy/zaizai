: start(i64).
: result(i64).
& a start(42).
result($v) <- start($x) & int_sub($x,$missing,$v).
? result(40).
