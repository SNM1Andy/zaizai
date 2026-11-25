: quota(sym,qty(mib)).
: left(sym).
& a quota(ns1,1000@mib).
left($x) <- quota($x,$b) & qty_sub($b,300@mib,$v) & qty_le($v,700@mib) & qty_le(700@mib,$v).
? left(ns1).
? left(ns2).
