string compiled_goal_obligation(const Continuity& state,const Program& native,const string& revision,const Atom& target,bool ephemeral,bool* eligible,bool* uncertain,Atom* chosen_premise,bool* clean_branches=nullptr){
    if(eligible)*eligible=false;
    if(uncertain)*uncertain=false;
    if(clean_branches)*clean_branches=true;
    validate_time_query(native,target);
    require((ephemeral||native.goals.contains(target))&&!target.pred.starts_with("!")&&
            ranges::none_of(target.args,variable),"obligation needs a declared unsigned ground goal");
    SliceStats scope;
    const auto baseline=query_slice(native,{target},scope);
    require(scope.rules<=256&&scope.observations<=2048,"obligation proof scope exceeds budget");
    const auto actual=run(baseline,state.inactive);
    auto contrary_goal=target;contrary_goal.pred="!"+target.pred;
    set<Atom> candidates;bool complete=true;
    if(!actual.facts.contains(target)&&!actual.facts.contains(contrary_goal)){
        for(const auto& [root,premise]:missing_inputs(baseline,actual,nullptr,&complete))
            if(root==target)candidates.insert(premise);
    }
    if(uncertain)*uncertain=!complete;
    ostringstream out;
    out<<"{\"schema\":\"pcgm-goal-obligation-v1\",\"actor\":"<<quote_json(state.id)
        <<",\"revision_sha256\":"<<quote_json(revision)<<",\"current\":";
    json_fact(out,actual,target);
    out<<",\"scan_complete\":"<<(complete?"true":"false")<<",\"candidate_count\":";
    if(complete)out<<candidates.size();else out<<"null";
    out<<",\"investigation\":";
    if(!complete||candidates.size()!=1)out<<"null";
    else{
        const auto goal=*candidates.begin();
        if(chosen_premise)*chosen_premise=goal;
        out<<"{\"premise\":";json_atom(out,goal);
        out<<",\"branches\":[";
        array<pair<bool,bool>,2> outcome;
        for(unsigned n=0;n<2;++n){
            if(n)out<<',';
            auto hypothetical=goal;
            if(n)hypothetical.pred="!"+hypothetical.pred;
            auto branch=baseline;
            const auto id="obligation_"+sha256(revision+show(target)+show(hypothetical)).substr(0,24);
            require(!branch.observations.contains(id)&&!state.inactive.contains(id),"hypothesis tag collision");
            branch.observations.emplace(id,hypothetical);
            const auto trial=run(branch,state.inactive);
            outcome[n]={trial.facts.contains(target),trial.facts.contains(contrary_goal)};
            // A clean grounding witness alone cannot clear a disputed *other*
            // antecedent. Inspect both proof trees; opposite conclusions remain
            // representable when their separate supporting chains are clean.
            if(clean_branches)for(const auto& sign:{target,contrary_goal}){
                const auto result=trial.facts.find(sign);
                if(result==trial.facts.end())continue;
                for(const auto& parent:result->second.parents){
                    bool limited=false;
                    if(!proof_without_conflict(trial,parent,&limited))*clean_branches=false;
                    if(limited&&uncertain)*uncertain=true;
                }
            }
            out<<"{\"hypothesis\":";json_atom(out,hypothetical);
            out<<",\"consequence\":";json_fact(out,trial,target);out<<'}';
        }
        if(eligible)*eligible=outcome[0]!=outcome[1];
        out<<"],\"distinguishes_consequence\":"<<(outcome[0]!=outcome[1]?"true":"false")<<'}';
    }
    return out.str()+",\"hypotheses_are_not_facts\":true,\"writes_state\":false,\"authorizes_action\":false,\"outbound\":false}";
}
string goal_obligation(const Continuity& state,const string& revision,const Atom& target,bool ephemeral=false,bool* eligible=nullptr,bool* uncertain=nullptr,Atom* chosen_premise=nullptr){
    return compiled_goal_obligation(state,compile_active(state),revision,target,ephemeral,eligible,uncertain,chosen_premise);
}
