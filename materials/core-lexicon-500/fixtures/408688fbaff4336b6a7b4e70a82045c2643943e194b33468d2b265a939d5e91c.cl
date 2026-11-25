: doc(sym,qty(cny_cent)).
: enough(sym).
& a doc(doc1,700@cny_cent).
& b doc(doc2,1400@cny_cent).
enough($x) <- doc($x,$c) & qty_le($c,1000@cny_cent).
? enough(doc1).
? enough(doc2).
