: active_signal(sym).
: suppressed(sym).
& a !active_signal("caseA").
!suppressed($x) <- !active_signal($x).
? suppressed("caseA").
? suppressed("caseB").
