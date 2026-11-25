: expense(sym,qty(cny_cent)).
: reimbursable(sym).
& a expense(trip,700@cny_cent).
& b expense(party,1400@cny_cent).
reimbursable($x) <- expense($x,$c) & qty_le($c,1000@cny_cent).
? reimbursable(trip).
? reimbursable(party).
