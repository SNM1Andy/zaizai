: said(sym).
: valid(sym).
& a said(alice).
& b said(bob).
& c !said(bob).
valid($x) <- said($x).
!valid($x) <- !said($x).
? valid(bob).
? valid(alice).
