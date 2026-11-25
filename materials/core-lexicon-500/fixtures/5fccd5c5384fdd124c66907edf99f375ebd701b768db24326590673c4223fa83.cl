: recorded(sym).
: linked(sym).
: signed(sym).
& a recorded(event1).
linked($x) <- recorded($x).
signed($x) <- linked($x).
? signed(event1).
? signed(event2).
