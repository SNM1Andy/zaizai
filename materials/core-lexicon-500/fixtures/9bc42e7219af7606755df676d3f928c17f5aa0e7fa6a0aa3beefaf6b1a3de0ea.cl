: meals_out(sym,i64).
: rare(sym).
& a meals_out(month1,2).
& b meals_out(month2,5).
rare($x) <- meals_out($x,$v) & int_le($v,3).
? rare(month1).
? rare(month2).
