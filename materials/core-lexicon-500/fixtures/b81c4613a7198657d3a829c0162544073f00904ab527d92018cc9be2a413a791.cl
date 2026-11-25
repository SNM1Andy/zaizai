: memory(sym,qty(mib)).
: within_limit(sym).
& a memory(node1,700@mib).
within_limit($x) <- memory($x,$c) & qty_add($c,300@mib,$t) & qty_le($t,1000@mib).
? within_limit(node1).
? within_limit(node2).
