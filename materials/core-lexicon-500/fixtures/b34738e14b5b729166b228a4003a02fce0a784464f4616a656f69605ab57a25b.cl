: active(sym).
: standby(sym).
: switched(sym).
& a active(case1).
standby($x) <- active($x).
switched($x) <- standby($x).
? switched(case1).
? switched(case2).
