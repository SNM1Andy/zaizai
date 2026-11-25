// Follow the two selected native witnesses. Stable rule identities survive
// unrelated edits that only renumber source lines.
struct OutcomeWitnesses {set<string> observations,rules;};
OutcomeWitnesses outcome_witnesses(const Table& table,const Atom& goal){
    OutcomeWitnesses refs;
    vector<Atom> queue{goal,opposite_of(goal)};
    set<Atom> seen;
    for(size_t i=0;i<queue.size();++i){
        const auto fact=queue[i];
        const auto found=table.facts.find(fact);
        if(found==table.facts.end()||!seen.insert(fact).second)continue;
        const auto& proof=found->second;
        if(proof.origin.starts_with("obs:")){
            const auto ref=proof.origin.substr(4);
            refs.observations.insert(ref.substr(0,ref.find('@')));
        }else refs.rules.insert(proof.identity);
        queue.insert(queue.end(),proof.parents.begin(),proof.parents.end());
    }
    return refs;
}

map<string,size_t> outcome_rules(const Program& program){
    map<string,size_t> rules;
    for(size_t i=0;i<program.rules.size();++i)rules.emplace(rule_origin_id(program,i),i);
    return rules;
}

void outcome_rule_changes(ostream& out,const Program& scope,const Program& other,
                          const OutcomeWitnesses& refs){
    const auto known=outcome_rules(other);
    bool comma=false;
    out<<'[';
    for(const auto& [digest,i]:outcome_rules(scope)){
        if(known.contains(digest))continue;
        const auto& r=scope.rules[i];
        string cl=show(r.head)+" <- ";
        for(size_t j=0;j<r.body.size();++j)cl+=(j?" & ":"")+show(r.body[j]);
        if(comma)out<<',';
        comma=true;
        out<<"{\"origin_sha256\":"<<quote_json(digest)<<",\"rule\":"<<quote_json(cl+".")
           <<",\"guard\":"<<(scope.live_guards.contains(i)?quote_json(scope.live_guards.at(i)):"null")
           <<",\"in_witness\":"<<(refs.rules.contains(digest)?"true":"false")<<'}';
    }
    out<<']';
}

// This receipt compares two verified points of the same actor's history.
// An observation in the predicate slice may concern a different argument.
// For small changes, undo one observation in memory and rerun the same rules
// to distinguish a causal change in truth from a concurrent edit.
string outcome_effect(const StateStore& store,const Continuity& current,const string& head,
                      const string& label,const Atom& goal,const Program& program,
                      const Program& scope,const Table& actual){
    const auto pin=current.pins.find(label);
    require(pin!=current.pins.end(),"unknown outcome comparison pin");
    const auto prior=verify_episode(store,current,pin->second);
    const auto earlier=compile_active(prior);
    validate_time_query(earlier,goal);
    SliceStats stats;
    const auto previous_scope=query_slice(earlier,{goal},stats);
    const auto before=run(previous_scope,prior.inactive);
    const auto before_refs=outcome_witnesses(before,goal),after_refs=outcome_witnesses(actual,goal);
    const auto prior_status=truth_state(before,goal),status=truth_state(actual,goal);
    const auto prior_proof=proof_digest(before,goal),proof=proof_digest(actual,goal);
    ostringstream out;
    out<<"{\"basis_revision\":"<<quote_json(pin->second.digest)<<",\"basis_event\":"<<pin->second.events
       <<",\"state_revision\":"<<quote_json(head)<<",\"effect_point\":";
    json_atom(out,goal);
    out<<",\"before_status\":"<<quote_json(prior_status)<<",\"after_status\":"<<quote_json(status)
       <<",\"conclusion_changed\":"<<(prior_status!=status?"true":"false")
       <<",\"before_proof_sha256\":"<<quote_json(prior_proof)<<",\"after_proof_sha256\":"<<quote_json(proof)
       <<",\"proof_changed\":"<<(prior_proof!=proof?"true":"false")<<",\"before_proof\":";
    json_fact(out,before,goal);
    set<string> ids;
    for(const auto& [id,_]:scope.observations)ids.insert(id);
    for(const auto& [id,_]:previous_scope.observations)ids.insert(id);
    size_t changed=0;
    out<<",\"observation_changes\":[";
    const auto active=[](const Program& p,const Continuity& s,const string& id)->optional<Atom>{
        const auto found=p.observations.find(id);
        if(found==p.observations.end()||s.inactive.contains(id))return nullopt;
        return found->second;
    };
    for(const auto& id:ids){
        const auto old=active(earlier,prior,id),now=active(program,current,id);
        if(old==now)continue;
        if(changed++)out<<',';
        out<<"{\"observation_id\":"<<quote_json(id)<<",\"before\":";
        if(old)json_atom(out,*old);else out<<"null";
        out<<",\"after\":";if(now)json_atom(out,*now);else out<<"null";
        out<<",\"in_before_witness\":"<<(before_refs.observations.contains(id)?"true":"false")
           <<",\"in_after_witness\":"<<(after_refs.observations.contains(id)?"true":"false")
           <<",\"status_if_change_undone\":";
        if(changed<=8&&scope.rules.size()<=256&&scope.observations.size()<=2048){
            auto trial=scope;
            auto inactive=current.inactive;
            if(old){trial.observations[id]=*old;inactive.erase(id);}
            else trial.observations.erase(id);
            // A counterfactual can exceed the native evaluator's limits even
            // when the two historical states are evaluable.
            try{const auto result=run(trial,inactive);out<<quote_json(truth_state(result,goal));}
            catch(const runtime_error&){out<<"null";}
        }else out<<"null";
        out<<'}';
    }
    out<<"],\"rules_added\":";outcome_rule_changes(out,scope,earlier,after_refs);
    out<<",\"rules_removed\":";outcome_rule_changes(out,previous_scope,program,before_refs);
    out<<",\"writes_state\":false}";
    return out.str();
}

string reasoned_outcome(const StateStore& store,const Continuity& current,const string& revision,
                        const string& case_id,const Atom& goal,const string& pin,
                        const Program& program,const Table& table){
    validate_time_query(program,goal);
    SliceStats stats;
    const auto scope=query_slice(program,{goal},stats);
    bool complete=true;
    const auto missing=missing_inputs(scope,table,nullptr,&complete);
    ostringstream out;
    out<<"{\"schema\":\"pcgm-reasoned-outcome-v1\",\"case_id\":"<<quote_json(case_id)
       <<",\"source_id\":"<<quote_json(current.id)
       <<",\"baseline_version\":\"source-sha256:9e456752f08769fb3757c21665587c847ec3104a87be7b4fb306bee892af2f31\""
       <<",\"state_revision\":"<<quote_json(revision)<<",\"event\":"<<current.events.size()<<",\"goal\":";
    json_atom(out,goal);
    out<<",\"status\":"<<quote_json(truth_state(table,goal))<<",\"positive_proof\":";
    json_branch(out,table,goal);out<<",\"negative_proof\":";json_branch(out,table,opposite_of(goal));
    out<<",\"missing_scan_complete\":"<<(complete?"true":"false")<<",\"missing\":[";
    for(size_t i=0;i<missing.size();++i){if(i)out<<',';json_atom(out,missing[i].second);}
    vector<string> tickets;
    for(const auto& [id,q]:current.questions)if(q.goal==goal)tickets.push_back(id);
    out<<"],\"question_ticket\":";
    if(tickets.size()==1)out<<quote_json(tickets.front());else out<<"null";
    out<<",\"questions\":[";
    if(!tickets.empty()){
        const auto gaps=open_gaps(program,table);
        for(size_t i=0;i<tickets.size();++i){
            if(i)out<<',';
            const auto& id=tickets[i];
            out<<question_json(current,id,current.questions.at(id),table,gaps,&program);
        }
    }
    out<<"],\"effect_receipt\":";
    if(pin.empty())out<<"null";
    else out<<outcome_effect(store,current,revision,pin,goal,program,scope,table);
    out<<'}';
    auto result=out.str();
    require(result.size()<=2*1024*1024,"reasoned outcome exceeds read response budget");
    return result;
}
