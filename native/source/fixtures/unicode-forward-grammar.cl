# Finite grammar over token positions. The bridges supply only lex, step and span.
: lex(i64,sym).
: step(i64,i64).
: span(i64,i64).
: token(i64,sym,i64).
: value(i64,i64).
: more_args(i64,i64).
: arguments(i64,i64).
: atom(i64,i64).
: literal(i64,i64).
: conditions(i64,i64).
: type_spec(i64,i64).
: type_list(i64,i64).
: declaration(i64,i64).
: observation(i64,i64).
: question(i64,i64).
: production(i64,i64).
: statement(i64,i64).
: source_line(i64,i64).
: source_lines(i64,i64).
: accept(sym).

token($s,$kind,$e) <- lex($s,$kind) & step($s,$e).
value($s,$e) <- token($s,name,$e).
value($s,$e) <- token($s,number,$e).
value($s,$e) <- token($s,quoted_symbol,$e).
value($s,$e) <- token($s,var,$a) & token($a,name,$e).
value($s,$e) <- token($s,number,$a) & token($a,tag,$b) & token($b,name,$e).
more_args($s,$e) <- token($s,comma,$a) & arguments($a,$e).
arguments($s,$e) <- value($s,$e).
arguments($s,$e) <- value($s,$a) & more_args($a,$e).
atom($s,$e) <- token($s,name,$a) & token($a,op,$b) & arguments($b,$c) & token($c,cp,$e).
literal($s,$e) <- atom($s,$e).
literal($s,$e) <- token($s,bang,$a) & atom($a,$e).
conditions($s,$e) <- literal($s,$e).
conditions($s,$e) <- literal($s,$a) & token($a,and,$b) & conditions($b,$e).
type_spec($s,$e) <- token($s,name,$e).
type_spec($s,$e) <- token($s,name,$a) & token($a,op,$b) & token($b,name,$c) & token($c,cp,$e).
type_list($s,$e) <- type_spec($s,$e).
type_list($s,$e) <- type_spec($s,$a) & token($a,comma,$b) & type_list($b,$e).
declaration($s,$e) <- token($s,colon,$a) & token($a,name,$b) & token($b,op,$c) & type_list($c,$d) & token($d,cp,$e).
observation($s,$e) <- token($s,and,$a) & token($a,name,$b) & literal($b,$e).
question($s,$e) <- token($s,ask,$a) & atom($a,$e).
production($s,$e) <- literal($s,$e).
production($s,$e) <- literal($s,$a) & token($a,arrow,$b) & conditions($b,$e).
statement($s,$e) <- declaration($s,$e).
statement($s,$e) <- observation($s,$e).
statement($s,$e) <- question($s,$e).
statement($s,$e) <- production($s,$e).
source_line($s,$e) <- token($s,eol,$e).
source_line($s,$e) <- statement($s,$a) & token($a,dot,$b) & token($b,eol,$e).
source_lines($s,$e) <- source_line($s,$e).
source_lines($s,$e) <- source_line($s,$a) & source_lines($a,$e).
accept(unit) <- span($s,$e) & source_lines($s,$e).
? accept(unit).

# The semantic head is the direct literal parent, regardless of its position.
production($s,$e) <- conditions($s,$a) & token($a,forward,$b) & literal($b,$e).
