: guests(sym,i64).
: small(sym).
& a guests(party1,2).
& b guests(party2,5).
small($x) <- guests($x,$v) & int_le($v,3).
? small(party1).
? small(party2).
