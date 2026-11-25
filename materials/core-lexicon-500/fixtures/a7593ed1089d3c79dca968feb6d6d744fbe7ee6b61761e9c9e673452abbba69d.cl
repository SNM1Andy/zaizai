: node(sym,i64).
: few(sym).
& a node(cluster1,2).
& b node(cluster2,5).
few($x) <- node($x,$v) & int_le($v,3).
? few(cluster1).
? few(cluster2).
