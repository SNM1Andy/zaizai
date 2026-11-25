: planned(sym).
: approved(sym).
: scheduled(sym).
& a planned(plan1).
approved($x) <- planned($x).
scheduled($x) <- approved($x).
? scheduled(plan1).
? scheduled(plan2).
