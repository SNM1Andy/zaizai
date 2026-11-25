: nodes(sym,i64).
: small(sym).
& a nodes(cluster1,2).
& b nodes(cluster2,5).
small($x) <- nodes($x,$v) & int_le($v,3).
? small(cluster1).
? small(cluster2).
