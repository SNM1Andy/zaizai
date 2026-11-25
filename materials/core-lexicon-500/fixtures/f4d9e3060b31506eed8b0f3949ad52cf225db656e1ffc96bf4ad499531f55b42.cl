: strength(sym,qty(cny_cent)).
: strong(sym).
& a strength(s1,700@cny_cent).
& b strength(s2,1400@cny_cent).
strong($x) <- strength($x,$c) & qty_le($c,1000@cny_cent).
? strong(s1).
? strong(s2).
