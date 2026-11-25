: spent(sym,qty(cny_cent)).
: remaining(sym,qty(cny_cent)).
: affordable(sym).
& a spent(alpha,6000@cny_cent).
& b spent(beta,11000@cny_cent).
? affordable(alpha).
? affordable(beta).
? remaining(alpha,4000@cny_cent).
? remaining(beta,-1000@cny_cent).
