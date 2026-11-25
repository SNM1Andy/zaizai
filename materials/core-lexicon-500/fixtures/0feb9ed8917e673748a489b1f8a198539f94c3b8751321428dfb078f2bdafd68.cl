: authored(sym).
: approved(sym).
: published(sym).
& a authored(runbook1).
approved($x) <- authored($x).
published($x) <- approved($x).
? published(runbook1).
? published(runbook2).
