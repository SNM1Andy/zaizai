: detected(sym).
: triaged(sym).
: resolved(sym).
& a detected(incident1).
triaged($x) <- detected($x).
resolved($x) <- triaged($x).
? resolved(incident1).
? resolved(incident2).
