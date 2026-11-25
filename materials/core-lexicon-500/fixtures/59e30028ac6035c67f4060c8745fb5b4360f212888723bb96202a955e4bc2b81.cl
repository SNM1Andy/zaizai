: gas_bill(sym,qty(cny_cent)).
: small(sym).
& a gas_bill(case1,700@cny_cent).
& b gas_bill(case2,1400@cny_cent).
small($x) <- gas_bill($x,$c) & qty_le($c,1000@cny_cent).
? small(case1).
? small(case2).
