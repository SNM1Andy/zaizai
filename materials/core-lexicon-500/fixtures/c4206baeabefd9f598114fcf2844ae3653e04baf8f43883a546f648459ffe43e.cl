: meeting_len(sym,qty(minute)).
: short(sym).
& a meeting_len(meet1,30@minute).
& b meeting_len(meet2,90@minute).
short($x) <- meeting_len($x,$c) & qty_lt($c,60@minute).
? short(meet1).
? short(meet2).
