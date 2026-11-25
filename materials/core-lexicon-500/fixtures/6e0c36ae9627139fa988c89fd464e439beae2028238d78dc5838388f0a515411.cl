: slot(sym,sym).
: busy(sym).
& a slot("roomA",nine_am).
& b slot("roomB",nine_am).
busy($x) <- slot($x,nine_am).
? busy("roomA").
? busy("roomB").
