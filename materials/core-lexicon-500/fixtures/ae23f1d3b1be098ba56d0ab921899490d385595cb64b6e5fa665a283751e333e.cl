: phone_bill(sym,qty(cny_cent)).
: cheap(sym).
& a phone_bill(line1,45@cny_cent).
& b phone_bill(line2,60@cny_cent).
cheap($x) <- phone_bill($x,$c) & qty_lt($c,50@cny_cent).
? cheap(line1).
? cheap(line2).
