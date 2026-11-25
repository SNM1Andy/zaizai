: seq(sym,i64).
: early(sym).
& a seq(item1,2).
& b seq(item2,5).
early($x) <- seq($x,$v) & int_lt($v,3).
? early(item1).
? early(item2).
