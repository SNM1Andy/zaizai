: batch_size(sym,i64).
: small(sym).
& a batch_size(batch1,2).
& b batch_size(batch2,5).
small($x) <- batch_size($x,$v) & int_le($v,3).
? small(batch1).
? small(batch2).
