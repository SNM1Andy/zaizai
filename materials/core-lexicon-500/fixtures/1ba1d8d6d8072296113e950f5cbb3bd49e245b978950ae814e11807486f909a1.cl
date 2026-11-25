: refund(sym,qty(cny_cent)).
: net(sym).
& a refund(order1,1000@cny_cent).
net($x) <- refund($x,$b) & qty_sub($b,300@cny_cent,$v) & qty_le($v,700@cny_cent) & qty_le(700@cny_cent,$v).
? net(order1).
? net(order2).
