: portfolio(sym).
: quotes(sym,sym,qty(cny_cent)).
: support_count(sym,i64).
: bottom(sym,qty(cny_cent)).
: top(sym,qty(cny_cent)).
: diversified(sym).
& live portfolio(active).
& no_quotes portfolio(empty).
& low quotes(active,low,-9223372036854775808@cny_cent).
& middle quotes(active,middle,17@cny_cent).
& repeated quotes(active,middle,17@cny_cent).
& high quotes(active,high,9223372036854775807@cny_cent).
& denied !quotes(active,excluded,99@cny_cent).
support_count($g,$n) <- portfolio($g) & qty_fold_count(quotes,$g,$n).
bottom($g,$amount) <- portfolio($g) & qty_fold_min(quotes,$g,$amount).
top($g,$amount) <- portfolio($g) & qty_fold_max(quotes,$g,$amount).
diversified($g) <- support_count($g,$n) & int_le(3,$n).
