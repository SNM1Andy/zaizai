: hotel(sym,qty(cny_cent)).
: within_policy(sym).
& a hotel(stay1,2800@cny_cent).
& b hotel(stay2,4200@cny_cent).
within_policy($x) <- hotel($x,$c) & qty_le($c,3500@cny_cent).
? within_policy(stay1).
? within_policy(stay2).
