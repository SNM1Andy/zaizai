: gen_head(sym,sym,sym).
: gen_body(sym,i64,sym,sym).
: learned_use(sym).
: learning_source(sym).
: requested_learning(sym).
: reconsider_learning(sym).
^ learned_use term_grounded.
^ learned_use term_local_match.
& local_task_kind learning_source(dictionary).
gen_head(desktop_rule,learned_use,item) <- learning_source(dictionary) & requested_learning(current).
gen_body(desktop_rule,1,term_grounded,item) <- learning_source(dictionary).
gen_body(desktop_rule,2,term_local_match,item) <- learning_source(dictionary).
? learned_use(current).
| hard positive identity_restored(zaizai).
| hard positive receipt_available(zaizai).
| wish positive learned_use(current) when requested_learning(current).
| wish unknown learned_use(current) when reconsider_learning(current).

