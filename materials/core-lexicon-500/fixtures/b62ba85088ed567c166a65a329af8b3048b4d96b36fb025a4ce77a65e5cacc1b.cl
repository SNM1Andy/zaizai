: agreed(sym,sym).
: consensus(sym).
& a agreed(teamA,decision).
& b agreed(teamB,decision).
consensus($x) <- agreed($x,decision).
? consensus(teamA).
? consensus(teamB).
