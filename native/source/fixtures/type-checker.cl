# A declarative type audit. Only t* input tables are supplied by the host.
: tsig(i64,sym,i64).
: tslot(i64,i64,i64).
: tuse(i64,i64,sym,i64).
: trole(i64,sym).
: tvar(i64,i64,i64,sym).
: tlit(i64,i64,i64).
: expected(i64,i64,i64).
: variable_kind(i64,sym,i64).
: known_site(i64).
: bound_var(i64,sym).
: type_error(i64,i64,sym).
: declaration_error(i64,sym).
known_site($id) <- tuse($id,$clause,$name,$n) & tsig($slot,$name,$m).
expected($id,$arg,$kind) <- tuse($id,$clause,$name,$n) & tsig($line,$name,$n) & tslot($line,$arg,$kind).
variable_kind($clause,$var,$kind) <- tvar($id,$arg,$clause,$var) & expected($id,$arg,$kind).
bound_var($clause,$var) <- tvar($id,$arg,$clause,$var) & trole($id,body).
type_error($id,0,arity) <- tuse($id,$clause,$name,$n) & tsig($line,$name,$m) & int_lt($n,$m).
type_error($id,0,arity) <- tuse($id,$clause,$name,$n) & tsig($line,$name,$m) & int_lt($m,$n).
type_error($id,$arg,literal_type) <- tlit($id,$arg,$is) & expected($id,$arg,$want) & int_lt($is,$want).
type_error($id,$arg,literal_type) <- tlit($id,$arg,$is) & expected($id,$arg,$want) & int_lt($want,$is).
type_error($id,$arg,variable_type) <- tvar($id,$arg,$clause,$var) & expected($id,$arg,$mine) & variable_kind($clause,$var,$other) & int_lt($mine,$other).
type_error($id,$arg,ground_required) <- tvar($id,$arg,$clause,$var) & trole($id,ground).
declaration_error($right,duplicate_signature) <- tsig($left,$name,$x) & tsig($right,$name,$y) & int_lt($left,$right).
declaration_error($line,arity_limit) <- tsig($line,$name,$n) & int_lt(4,$n).
