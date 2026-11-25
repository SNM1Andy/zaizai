: ldecl(i64).
: lsite(i64,i64).
: lform(i64,sym).
: rule_clause(i64).
: emit_declaration(i64).
: emit_site(i64,i64,sym).
emit_declaration($at) <- ldecl($at).
emit_site($id,$at,query) <- lsite($id,$at) & lform($id,query).
emit_site($id,$at,observation) <- lsite($id,$at) & lform($id,observation).
emit_site($id,$at,fact) <- lsite($id,$at) & lform($id,fact).
rule_clause($at) <- lsite($id,$at) & lform($id,head).
emit_site($id,$at,head) <- lsite($id,$at) & lform($id,head) & rule_clause($at).
emit_site($id,$at,body) <- lsite($id,$at) & lform($id,body) & rule_clause($at).
