: active(sym).
: literal_cfg(sym,i64,sym,sym).
: variable_cfg(sym,i64,i64,sym).
: amount_cfg(sym,i64,i64,i64).
: unit_cfg(sym,i64,i64,sym).
: ast_literal(sym,i64,sym,sym).
: ast_var(sym,i64,i64,sym).
: ast_amount(sym,i64,i64,i64).
: ast_unit(sym,i64,i64,sym).
& enabled active(install_budget).
& l1 literal_cfg(balance,0,remaining,pos).
& l2 literal_cfg(balance,1,spent,pos).
& l3 literal_cfg(balance,2,qty_sub,pos).
& v01 variable_cfg(balance,0,1,candidate).
& v02 variable_cfg(balance,0,2,left).
& v11 variable_cfg(balance,1,1,candidate).
& v12 variable_cfg(balance,1,2,spend).
& a21 amount_cfg(balance,2,1,10000).
& u21 unit_cfg(balance,2,1,cny_cent).
& v22 variable_cfg(balance,2,2,spend).
& v23 variable_cfg(balance,2,3,left).
& l4 literal_cfg(approval,0,affordable,pos).
& l5 literal_cfg(approval,1,remaining,pos).
& l6 literal_cfg(approval,2,qty_le,pos).
& v010 variable_cfg(approval,0,1,candidate).
& v110 variable_cfg(approval,1,1,candidate).
& v120 variable_cfg(approval,1,2,left).
& a210 amount_cfg(approval,2,1,0).
& u210 unit_cfg(approval,2,1,cny_cent).
& v220 variable_cfg(approval,2,2,left).
ast_literal($r,$p,$n,$s) <- active(install_budget) & literal_cfg($r,$p,$n,$s).
ast_var($r,$p,$i,$v) <- active(install_budget) & variable_cfg($r,$p,$i,$v).
ast_amount($r,$p,$i,$v) <- active(install_budget) & amount_cfg($r,$p,$i,$v).
ast_unit($r,$p,$i,$u) <- active(install_budget) & unit_cfg($r,$p,$i,$u).
