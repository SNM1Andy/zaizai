: daily_hours(sym,qty(minute)).
: normal(sym).
& a daily_hours(day1,480@minute).
& b daily_hours(day2,600@minute).
normal($x) <- daily_hours($x,$c) & qty_le($c,540@minute).
? normal(day1).
? normal(day2).
