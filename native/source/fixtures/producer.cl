: gen_head(sym,sym,sym).
: gen_body(sym,i64,sym,sym).
: authorized(sym).
: sample(sym).
: monitor(sym).
: generation(sym).
: output_for(sym,sym).
: premise_for(sym,i64,sym).
^ monitor sample.
^ monitor authorized.
? monitor(alpha).
? monitor(beta).
& permission authorized(alpha).
& signal sample(alpha).
& extra sample(beta).
& request generation(track).
& output output_for(track,monitor).
& step_a premise_for(track,1,sample).
& step_b premise_for(track,2,authorized).
# CL selects the output and premises from current evidence. No legacy @ template.
gen_head($id,$out,item) <- generation($id) & output_for($id,$out) & authorized(alpha).
gen_body($id,$idx,$pred,item) <- generation($id) & premise_for($id,$idx,$pred) & authorized(alpha).
