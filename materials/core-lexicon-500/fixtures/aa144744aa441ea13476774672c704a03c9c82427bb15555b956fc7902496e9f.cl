: stated(sym).
: justified(sym).
: accepted(sym).
& a stated(case1).
justified($x) <- stated($x).
accepted($x) <- justified($x).
? accepted(case1).
? accepted(case2).
