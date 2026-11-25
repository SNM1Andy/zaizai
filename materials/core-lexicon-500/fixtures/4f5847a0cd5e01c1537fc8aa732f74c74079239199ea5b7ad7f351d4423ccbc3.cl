: cost(sym,qty(cny_cent)).
: within(sym).
& a cost(clerk,900@cny_cent).
within($x) <- cost($x,$c) & qty_le($c,900@usd_cent).
? within(clerk).
