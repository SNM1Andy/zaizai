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

# Proportional extent is a unit-preserving amount, two integers, and a same-unit result.
: ratio_abi(sym).
: ratio_quantity(i64,i64).
ratio_abi(v1).
ratio_quantity($id,$kind) <- toperator($id,qty_ratio,4) & actual($id,1,$kind) & tclass($kind,quantity).
quantity_known($id) <- ratio_quantity($id,$kind).
expected($id,1,$kind) <- ratio_quantity($id,$kind).
expected($id,4,$kind) <- ratio_quantity($id,$kind).
expected($id,2,$kind) <- toperator($id,qty_ratio,4) & tclass($kind,integer).
expected($id,3,$kind) <- toperator($id,qty_ratio,4) & tclass($kind,integer).
producer($id,$clause,$var) <- tvar($id,4,$clause,$var) & toperator($id,qty_ratio,4) & trole($id,body).

# Closed fold first term names an immutable quantity input relation.
: fold_abi(sym).
: tclosed(sym).
: tfold(i64,sym).
: fold_signature(i64,i64).
: fold_unit(i64,i64).
: fold_known(i64).
fold_abi(v1).
fold_abi(v2).
fold_signature($site,$line) <- tfold($site,$rel) & tclosed($rel) & tsig($line,$rel,3) & tslot($line,1,$one) & tslot($line,2,$two) & tclass($one,symbol) & tclass($two,symbol).
fold_unit($site,$kind) <- fold_signature($site,$line) & tslot($line,3,$kind) & tclass($kind,quantity).
fold_known($site) <- fold_unit($site,$kind).
expected($site,1,$kind) <- toperator($site,qty_fold,3) & tclass($kind,symbol).
expected($site,2,$kind) <- toperator($site,qty_fold,3) & tclass($kind,symbol).
expected($site,3,$kind) <- toperator($site,qty_fold,3) & fold_unit($site,$kind).
producer($site,$clause,$name) <- toperator($site,qty_fold,3) & tvar($site,3,$clause,$name) & trole($site,body).

# Count proves the same closed quantity input, but its output is dimensionless.
expected($site,1,$kind) <- toperator($site,qty_fold_count,3) & tclass($kind,symbol).
expected($site,2,$kind) <- toperator($site,qty_fold_count,3) & tclass($kind,symbol).
expected($site,3,$kind) <- toperator($site,qty_fold_count,3) & fold_known($site) & tclass($kind,integer).
producer($site,$clause,$name) <- toperator($site,qty_fold_count,3) & tvar($site,3,$clause,$name) & trole($site,body).

# A unit conversion selects a sealed rational quote and emits the explicit target type.
: conversion_abi(sym).
: tconvert(i64,sym,i64).
: conversion_signature(i64,i64).
: conversion_rate(i64).
: conversion_input(i64,i64).
: conversion_known(i64).
conversion_abi(v1).
conversion_signature($site,$line) <- tconvert($site,$rel,$want) & tclosed($rel) & tsig($line,$rel,4).
conversion_rate($site) <- conversion_signature($site,$line) & tslot($line,1,$s) & tslot($line,2,$s) & tclass($s,symbol) & tslot($line,3,$i) & tslot($line,4,$i) & tclass($i,integer).
conversion_input($site,$kind) <- toperator($site,qty_conversion,4) & actual($site,2,$kind) & tclass($kind,quantity).
conversion_known($site) <- conversion_rate($site) & conversion_input($site,$from) & tconvert($site,$rel,$target).
expected($site,1,$kind) <- toperator($site,qty_conversion,4) & tclass($kind,symbol).
expected($site,3,$kind) <- toperator($site,qty_conversion,4) & tclass($kind,symbol).
expected($site,4,$kind) <- tconvert($site,$rel,$kind) & conversion_rate($site).
type_error($site,2,same_unit) <- conversion_input($site,$kind) & tconvert($site,$rel,$kind).
producer($site,$rule,$name) <- toperator($site,qty_conversion,4) & tvar($site,4,$rule,$name) & trole($site,body).
