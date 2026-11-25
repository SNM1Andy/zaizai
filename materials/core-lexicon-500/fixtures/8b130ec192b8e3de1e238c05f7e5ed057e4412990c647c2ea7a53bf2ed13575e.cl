: streak(sym,i64).
: reached(sym).
& a streak(user1,3).
reached($x) <- streak($x,$n) & int_add($n,2,$t) & int_le($t,5).
? reached(user1).
? reached(user2).
