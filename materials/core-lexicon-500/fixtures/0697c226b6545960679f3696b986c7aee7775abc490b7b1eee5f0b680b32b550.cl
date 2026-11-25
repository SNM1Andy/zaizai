: count(i64).
: next(i64).
& seed count(9223372036854775807).
next($y) <- count($x) & int_add($x,1,$y).
? next(0).
