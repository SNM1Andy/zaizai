: loan(sym,qty(cny_cent)).
: small(sym).
& a loan(loan1,700@cny_cent).
& b loan(loan2,1400@cny_cent).
small($x) <- loan($x,$c) & qty_le($c,1000@cny_cent).
? small(loan1).
? small(loan2).
