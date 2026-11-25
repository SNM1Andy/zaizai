: insurance(sym,qty(cny_cent)).
: affordable(sym).
& a insurance(policy1,700@cny_cent).
& b insurance(policy2,1400@cny_cent).
affordable($x) <- insurance($x,$c) & qty_le($c,1000@cny_cent).
? affordable(policy1).
? affordable(policy2).
