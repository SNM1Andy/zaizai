: age(sym,i64).
: minor(sym).
& a age(guest1,15).
& b age(guest2,20).
minor($x) <- age($x,$v) & int_le(12,$v) & int_lt($v,18).
? minor(guest1).
? minor(guest2).
