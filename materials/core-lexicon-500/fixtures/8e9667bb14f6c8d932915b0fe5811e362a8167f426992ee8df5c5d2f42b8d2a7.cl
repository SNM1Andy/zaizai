: overtime(sym,qty(hour)).
: within_quota(sym).
& a overtime(week1,30@hour).
within_quota($x) <- overtime($x,$c) & qty_add($c,10@hour,$t) & qty_le($t,40@hour).
? within_quota(week1).
? within_quota(week2).
