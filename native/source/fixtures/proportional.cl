: budget(sym,qty(cny_cent)).
: rate(sym,i64,i64).
: allocation(sym,qty(cny_cent)).
: reserve(sym,qty(cny_cent)).
& cash budget(a,-1001@cny_cent).
& ration rate(a,2,3).
allocation($id,$result) <- budget($id,$pool) & rate($id,$numerator,$denominator) & qty_ratio_floor($pool,$numerator,$denominator,$result).
reserve($id,$result) <- budget($id,$pool) & rate($id,$numerator,$denominator) & qty_ratio_ceil($pool,$numerator,$denominator,$result).
? allocation(a,-668@cny_cent).
? reserve(a,-667@cny_cent).
