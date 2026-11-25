: member_level(sym,i64).
: basic(sym).
& a member_level(user1,2).
& b member_level(user2,5).
basic($x) <- member_level($x,$v) & int_le($v,3).
? basic(user1).
? basic(user2).
