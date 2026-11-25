: approved(sym).
: valid(sym).
& a approved(change1).
& b approved(change2).
& c !approved(change2).
valid($x) <- approved($x).
!valid($x) <- !approved($x).
? valid(change2).
? valid(change1).
