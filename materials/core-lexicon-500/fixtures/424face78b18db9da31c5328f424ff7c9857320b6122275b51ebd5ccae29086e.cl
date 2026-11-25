: cost(sym,qty(cny_cent)).
: cheap(sym).
& a cost(job1,700@cny_cent).
& b cost(job2,1400@cny_cent).
cheap($x) <- cost($x,$c) & qty_le($c,1000@cny_cent).
? cheap(job1).
? cheap(job2).
