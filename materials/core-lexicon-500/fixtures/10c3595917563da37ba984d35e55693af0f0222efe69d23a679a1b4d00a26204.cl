: salary(sym,qty(cny_cent)).
: below_cap(sym).
& a salary(staff1,8000@cny_cent).
& b salary(staff2,12000@cny_cent).
below_cap($x) <- salary($x,$c) & qty_le($c,10000@cny_cent).
? below_cap(staff1).
? below_cap(staff2).
