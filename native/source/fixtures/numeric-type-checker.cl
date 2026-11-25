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
type_error($id,0,arity) <- tuse($id,$clause,$name,$n) & tsig($line,$name,$m) & int_lt($n,$m).
type_error($id,0,arity) <- tuse($id,$clause,$name,$n) & tsig($line,$name,$m) & int_lt($m,$n).
type_error($id,$arg,literal_type) <- tlit($id,$arg,$is) & expected($id,$arg,$want) & int_lt($is,$want).
type_error($id,$arg,literal_type) <- tlit($id,$arg,$is) & expected($id,$arg,$want) & int_lt($want,$is).
type_error($id,$arg,variable_type) <- tvar($id,$arg,$clause,$var) & expected($id,$arg,$mine) & variable_kind($clause,$var,$other) & int_lt($mine,$other).
type_error($id,$arg,ground_required) <- tvar($id,$arg,$clause,$var) & trole($id,ground).
declaration_error($right,duplicate_signature) <- tsig($left,$name,$x) & tsig($right,$name,$y) & int_lt($left,$right).
declaration_error($line,arity_limit) <- tsig($line,$name,$n) & int_lt(4,$n).

: toperator(i64,sym,i64).
: tclass(i64,sym).
: tplain(i64).
: part(i64,i64).
: numeric_family(i64,sym).
: actual(i64,i64,i64).
: quantity_kind(i64,i64).
: quantity_known(i64).
: producer(i64,i64,sym).
: bound_before(i64,i64,sym).
known_site($id) <- toperator($id,$op,$n).
part($id,$position) <- tlit($id,$position,$kind).
part($id,$position) <- tvar($id,$position,$rule,$name).
numeric_family($id,integer) <- toperator($id,int_calc,$arity).
numeric_family($id,integer) <- toperator($id,int_cmp,$arity).
numeric_family($id,quantity) <- toperator($id,qty_calc,$arity).
numeric_family($id,quantity) <- toperator($id,qty_cmp,$arity).
expected($id,$position,$kind) <- numeric_family($id,integer) & part($id,$position) & tclass($kind,integer).
actual($id,$position,$kind) <- tlit($id,$position,$kind).
actual($id,$position,$kind) <- tvar($id,$position,$clause,$var) & variable_kind($clause,$var,$kind).
quantity_kind($id,$kind) <- numeric_family($id,quantity) & actual($id,$position,$kind) & tclass($kind,quantity).
quantity_known($id) <- quantity_kind($id,$kind).
expected($id,$position,$kind) <- quantity_kind($id,$kind) & part($id,$position).
type_error($id,0,operator_context) <- toperator($id,$op,$arity) & trole($id,ground).
type_error($id,0,operator_context) <- toperator($id,$op,$arity) & trole($id,head).
type_error($id,0,operator_arity) <- toperator($id,$op,$want) & tuse($id,$line,$name,$got) & int_lt($want,$got).
type_error($id,0,operator_arity) <- toperator($id,$op,$want) & tuse($id,$line,$name,$got) & int_lt($got,$want).
type_error($id,$position,quantity_required) <- numeric_family($id,quantity) & actual($id,$position,$kind) & tclass($kind,integer).
type_error($id,$position,quantity_required) <- numeric_family($id,quantity) & actual($id,$position,$kind) & tclass($kind,symbol).
type_error($id,$position,quantity_units) <- quantity_kind($id,$kind) & actual($id,$position,$other) & tclass($other,quantity) & int_lt($other,$kind).
producer($id,$clause,$var) <- tvar($id,$position,$clause,$var) & tplain($id) & trole($id,body).
producer($id,$clause,$var) <- tvar($id,3,$clause,$var) & toperator($id,int_calc,3) & trole($id,body).
producer($id,$clause,$var) <- tvar($id,3,$clause,$var) & toperator($id,qty_calc,3) & trole($id,body).
bound_var($clause,$var) <- producer($id,$clause,$var).
bound_before($id,$clause,$var) <- tvar($id,$position,$clause,$var) & producer($first,$clause,$var) & int_lt($first,$id).

: tsign(i64,sym).
type_error($id,0,operator_sign) <- toperator($id,$op,$arity) & tsign($id,negative).
