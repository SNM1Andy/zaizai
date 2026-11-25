: chore(sym,i64).
: light(sym).
& a chore(day1,2).
& b chore(day2,5).
light($x) <- chore($x,$v) & int_le($v,3).
? light(day1).
? light(day2).
