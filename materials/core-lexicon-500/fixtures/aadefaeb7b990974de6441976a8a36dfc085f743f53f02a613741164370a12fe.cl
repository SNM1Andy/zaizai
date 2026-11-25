: school_lunch(sym,qty(cny_cent)).
: cheap(sym).
& a school_lunch(case1,45@cny_cent).
& b school_lunch(case2,60@cny_cent).
cheap($x) <- school_lunch($x,$c) & qty_lt($c,50@cny_cent).
? cheap(case1).
? cheap(case2).
