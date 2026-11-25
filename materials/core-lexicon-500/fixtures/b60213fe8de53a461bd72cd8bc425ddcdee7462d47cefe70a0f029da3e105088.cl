: count(i64).
: next(i64).
& seed count(40).
next($y) <- count($x) & int_add($x,2,$y).
? next(42).
