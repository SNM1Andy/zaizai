: lexref25_chosen(sym,sym).
: lexref25_binding(sym,sym,sym,sym).
: lexref25_version(sym,sym,sym).
: lexref25_available(sym,sym,sym).
: lexref25_retired(sym,sym,sym).
: lexref25_tombstone_at(sym,sym,sym).
: lexref25_active(sym).
: lexref25_tombstone(sym).
lexref25_active($r) <- lexref25_binding($r,$s,$h1,$h2) & lexref25_version($r,$v1,$v2) & lexref25_available($s,$v1,$v2).
lexref25_tombstone($r) <- lexref25_binding($r,$s,$h1,$h2) & lexref25_version($r,$v1,$v2) & lexref25_retired($s,$v1,$v2).
lexref25_tombstone($r) <- lexref25_binding($r,$s,$h1,$h2) & lexref25_chosen($v1,$v2) & lexref25_tombstone_at($s,$v1,$v2).
