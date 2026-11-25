: cost(sym,qty(cny_cent)).
: within(sym).
& a cost(clerk,900@cny_cent).
& b cost(guest,901@cny_cent).
within($x) <- cost($x,$c) & qty_le($c,900@cny_cent).
? within(clerk).
? within(guest).
