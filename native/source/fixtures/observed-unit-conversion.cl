: quote(sym,sym,i64,i64).
: balance(sym,qty(cny_cent)).
: lower(sym,qty(token)).
: upper(sym,qty(token)).
: total(sym,qty(token)).
& negative balance(negative,-5@cny_cent).
& positive balance(positive,5@cny_cent).
& backward quote(token,cny_cent,2,3).
lower($x,$v) <- balance($x,$amount) & qty_convert_floor(quote,$amount,token,$v).
upper($x,$v) <- balance($x,$amount) & qty_convert_ceil(quote,$amount,token,$v).
total($x,$t) <- balance($x,$amount) & qty_convert_ceil(quote,$amount,token,$v) & qty_add($v,1@token,$t).
