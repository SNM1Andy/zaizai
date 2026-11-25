: term_candidate(sym).
: term_local_match(sym).
: term_grounded(sym).
: term_conflict(sym).
: term_adopt(sym).
term_adopt($x) <- term_candidate($x) & term_local_match($x) & term_grounded($x).
!term_adopt($x) <- term_conflict($x).

