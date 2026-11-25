string logical_cost(const Program& program,const vector<Atom>& goals,const string& context,const JoinLimit& cap){
    JoinWork work;
    CostLedger profile;
    string failure,proof_digest;
    size_t committed=0;
    try{
        RoundEvaluator evaluation(program,{},cap,&work,&profile);
        try{
            while(!evaluation.advance()){}
            proof_digest=sha256(json_report(evaluation.result(),goals,"cl",context)+'\n');
        }catch(const EvaluationLimit& e){failure=e.what();}
        committed=evaluation.facts();
    }catch(const EvaluationLimit& e){failure=e.what();committed=profile.initial_facts;}
    const bool complete=failure.empty();
    size_t probes=0,indexed=0,queued=0;
    for(const auto& r:profile.rules){probes+=r.probes;indexed+=r.indexed;queued+=r.queued;}
    require(probes==work.probes&&indexed<=work.indexed&&committed>=profile.initial_facts,
            "CL profile resource counters disagree");
    ostringstream out;
    out<<"{\"schema\":\"cl-logical-cost-v1\",\"context\":"<<context
        <<",\"complete\":"<<(complete?"true":"false")<<",\"resource_limit\":"<<(complete?"null":quote_json(failure))
        <<",\"proof_sha256\":"<<(complete?quote_json(proof_digest):"null")
        <<",\"totals\":{\"rounds\":"<<work.rounds<<",\"probes\":"<<work.probes
        <<",\"indexed\":"<<work.indexed<<",\"between_rule_indexed\":"<<work.indexed-indexed
        <<",\"initial_facts\":"<<profile.initial_facts<<",\"committed_facts\":"<<committed
        <<",\"queued_conclusions\":"<<queued<<"},\"rules\":[";
    for(size_t i=0;i<profile.rules.size();++i){
        if(i)out<<',';
        const auto& row=profile.rules.at(i);
        out<<"{\"rule\":"<<(program.rule_numbers.empty()?i+1:program.rule_numbers.at(i))
            <<",\"source\":"<<(program.rule_labels.empty()?"null":quote_json(program.rule_labels.at(i)))
            <<",\"head\":"<<quote_json(show(program.rules.at(i).head))
            <<",\"rounds_reached\":"<<row.rounds<<",\"probes\":"<<row.probes
            <<",\"indexed\":"<<row.indexed<<",\"queued_conclusions\":"<<row.queued<<'}';
    }
    out<<"]}\n";return out.str();
}
std::string profile_package_cost(const string& raw,const string& pin,const string& goal_bytes,const EvaluationCeilings& limits){
    require(workspace_digest(pin)&&sha256(raw)==pin,"CL profile package SHA-256 mismatch");
    const auto bundle=decode_package(raw);
    const auto program=verify_package(bundle);
    const auto goals=offline_goals(program,goal_bytes);
    return logical_cost(program,goals,
        "{\"protocol\":\"cl-offline-proof-v1\",\"package_sha256\":"+quote_json(pin)+
        ",\"ir_sha256\":"+quote_json(sha256(bundle.ir))+",\"goals_sha256\":"+quote_json(sha256(goal_bytes))+"}",
        bounded_limits(limits));
}
std::string profile_workspace_cost(const string& raw,const string& pin,const string& lock,const string& goal_bytes,
                                   const EvaluationCeilings& limits){
    require(workspace_digest(pin)&&sha256(raw)==pin,"CL profile workspace SHA-256 mismatch");
    const auto workspace=decode_workspace(raw);
    const auto exact=assemble_workspace_bytes(workspace.input,lock);
    require(workspace.report==sha256(exact.receipt)&&workspace.ir==to_image(exact.program,{}),
            "CL profile workspace failed independent reconstruction");
    const auto goals=offline_goals(exact.program,goal_bytes);
    return logical_cost(exact.program,goals,
        "{\"protocol\":\"cl-workspace-proof-v1\",\"archive_sha256\":"+quote_json(pin)+",\"lock_sha256\":"+quote_json(lock)+
        ",\"ir_sha256\":"+quote_json(sha256(workspace.ir))+",\"goals_sha256\":"+quote_json(sha256(goal_bytes))+"}",
        bounded_limits(limits));
}
