: duration(sym,qty(minute)).
: within_window(sym).
& a duration(task1,30@minute).
& b duration(task2,90@minute).
within_window($x) <- duration($x,$c) & qty_le($c,60@minute).
? within_window(task1).
? within_window(task2).
