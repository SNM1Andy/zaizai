: streaming(sym,qty(cny_cent)).
: cheap(sym).
& a streaming(video,45@cny_cent).
& b streaming(music,60@cny_cent).
cheap($x) <- streaming($x,$c) & qty_lt($c,50@cny_cent).
? cheap(video).
? cheap(music).
