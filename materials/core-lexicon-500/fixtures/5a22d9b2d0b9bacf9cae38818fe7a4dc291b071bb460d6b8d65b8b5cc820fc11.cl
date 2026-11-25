: frequency(sym,i64).
: low(sym).
& a frequency(event1,2).
& b frequency(event2,5).
low($x) <- frequency($x,$v) & int_le($v,3).
? low(event1).
? low(event2).
