: group(sym).
: claims(sym,sym,qty(cny_cent)).
: total(sym,qty(cny_cent)).
& g1 group(active).
& g2 group(empty).
& q1 claims(active,early,120@cny_cent).
& q2 claims(active,late,55@cny_cent).
& q3 claims(active,out,-20@cny_cent).
& same claims(active,early,120@cny_cent).
& theoretical !claims(active,proposed,1000@cny_cent).
total($g,$amount) <- group($g) & qty_fold_sum(claims,$g,$amount).
? total(active,155@cny_cent).
? total(empty,0@cny_cent).
