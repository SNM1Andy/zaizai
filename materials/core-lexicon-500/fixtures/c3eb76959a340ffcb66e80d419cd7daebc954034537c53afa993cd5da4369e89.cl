: raised(sym).
: notified(sym).
: escalated(sym).
& a raised(case1).
notified($x) <- raised($x).
escalated($x) <- notified($x).
? escalated(case1).
? escalated(case2).
