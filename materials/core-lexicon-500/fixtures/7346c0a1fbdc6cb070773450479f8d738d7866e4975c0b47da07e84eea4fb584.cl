: window(sym,i64).
: active(sym).
& a window(win1,15).
& b window(win2,20).
active($x) <- window($x,$v) & int_le(12,$v) & int_lt($v,18).
? active(win1).
? active(win2).
