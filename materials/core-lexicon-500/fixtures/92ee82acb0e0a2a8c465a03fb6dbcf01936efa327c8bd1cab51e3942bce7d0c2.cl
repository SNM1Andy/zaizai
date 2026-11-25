: owns(sym,sym).
: owner(sym).
& a owns(book,anna).
& b owns(pen,bo).
owner($who) <- owns($item,$who).
? owner(anna).
? owner(bo).
? owner(cy).
