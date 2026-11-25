: seen(sym).
: reported(sym).
& a seen(node1).
reported($x) <- seen($x).
? reported(node1).
? reported(node2).
