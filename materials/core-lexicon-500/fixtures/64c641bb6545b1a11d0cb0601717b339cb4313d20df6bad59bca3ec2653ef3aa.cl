: days_left(sym,qty(day)).
: urgent(sym).
& a days_left(job1,3@day).
& b days_left(job2,5@day).
urgent($x) <- days_left($x,$c) & qty_lt($c,4@day).
? urgent(job1).
? urgent(job2).
