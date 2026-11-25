: observed(sym).
: inferred(sym).
: held(sym).
& a observed(item1).
inferred($x) <- observed($x).
held($x) <- inferred($x).
? held(item1).
? held(item2).
