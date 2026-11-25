: rent(sym,qty(cny_cent)).
: refund_due(sym).
& a rent(flat1,1000@cny_cent).
refund_due($x) <- rent($x,$b) & qty_sub($b,300@cny_cent,$v) & qty_le($v,700@cny_cent) & qty_le(700@cny_cent,$v).
? refund_due(flat1).
? refund_due(flat2).
