: start(i64).
: next(i64).
& a start(40).
next($v) <- start($x) & int_add($x,2,$v).
? next(42).
