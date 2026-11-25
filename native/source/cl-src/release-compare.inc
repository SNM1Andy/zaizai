string compare_verified_packages(const string& old_bytes,const string& old_pin,const string& new_bytes,
        const string& new_pin,const string& goals,const EvaluationCeilings& ceiling){
    require(workspace_digest(old_pin)&&sha256(old_bytes)==old_pin,"baseline package digest mismatch");
    require(workspace_digest(new_pin)&&sha256(new_bytes)==new_pin,"candidate package digest mismatch");
    if(!ceiling.rounds||ceiling.rounds>128||!ceiling.facts||ceiling.facts>12000||!ceiling.probes||
       ceiling.probes>2000000||!ceiling.indexed||ceiling.indexed>2000000)
        throw std::invalid_argument("invalid CL release comparison evaluation ceilings");
    const auto baseline=decode_package(old_bytes),candidate=decode_package(new_bytes);
    const auto a=verify_package(baseline),b=verify_package(candidate);
    const auto module_a=LinkedProject::load_text(baseline.entry,baseline.files.at(baseline.entry)).name;
    const auto module_b=LinkedProject::load_text(candidate.entry,candidate.files.at(candidate.entry)).name;
    const auto before=parse_api(baseline.api),after=parse_api(candidate.api);
    const auto cases=offline_goals(a,goals);
    const JoinLimit limits{ceiling.rounds,ceiling.facts,ceiling.probes,ceiling.indexed};
    const auto a_facts=run(a,{},nullptr,limits),b_facts=run(b,{},nullptr,limits);
    const auto scope=baseline.scope_policy==candidate.scope_policy?"unchanged":
                     baseline.scope_policy.empty()?"added":candidate.scope_policy.empty()?"removed":"changed";
    ostringstream exports,proofs;
    auto entry=[](const PublicEntry& e){
        return "{\"direction\":"+quote_json(e.direction)+",\"types\":"+quote_json(api_type_list(e.types))+"}";
    };
    size_t breaking=0,extended=0,belief_changed=0,reasons_changed=0;
    bool first=true;
    auto append=[&](const pair<string,string>& name,const char* kind,const string& previous,const string& next){
        if(!first)exports<<',';
        first=false;
        exports<<"{\"name\":"<<quote_json(name.first+"::"+name.second)<<",\"change\":"<<quote_json(kind)
               <<",\"before\":"<<previous<<",\"after\":"<<next<<'}';
    };
    for(const auto& [name,e]:before){
        const auto item=after.find(name);
        if(item==after.end()){append(name,"removed",entry(e),"null");++breaking;}
        else if(item->second!=e){append(name,"changed",entry(e),entry(item->second));++breaking;}
    }
    for(const auto& [name,e]:after)if(!before.contains(name)){append(name,"added","null",entry(e));++extended;}
    const auto atom_report=[](const Table& table,const Atom& goal){
        auto negative=goal;negative.pred="!"+goal.pred;
        const auto pos=table.facts.contains(goal),neg=table.facts.contains(negative);
        ostringstream json;json_fact(json,table,goal);
        return pair<string,string>{pos?(neg?"CONFLICT":"POSITIVE"):(neg?"NEGATIVE":"UNKNOWN"),sha256(json.str())};
    };
    size_t seed_added=0,seed_removed=0,seed_changed=0;
    for(const auto& [id,atom]:a.observations){
        const auto found=b.observations.find(id);
        if(found==b.observations.end())++seed_removed;
        else if(found->second!=atom)++seed_changed;
    }
    for(const auto& [id,_]:b.observations)if(!a.observations.contains(id))++seed_added;
    for(size_t i=0;i<cases.size();++i){
        const auto& goal=cases[i];
        const auto left=atom_report(a_facts,goal);
        bool available=true;
        try{
            require(b.arity.contains(goal.pred)&&b.arity.at(goal.pred)==goal.args.size(),"candidate goal unavailable");
            map<string,Kind> types;check_type(b,goal,types);
        }catch(const runtime_error&){available=false;}
        const auto right=available?atom_report(b_facts,goal):pair<string,string>{"UNAVAILABLE",""};
        const bool sign=left.first!=right.first,explanation=!sign&&left.second!=right.second;
        belief_changed+=sign;reasons_changed+=explanation;
        if(i)proofs<<',';
        proofs<<"{\"goal\":"<<quote_json(show(goal))<<",\"before\":"<<quote_json(left.first)
              <<",\"after\":"<<quote_json(right.first)<<",\"exact_before_sha256\":"<<quote_json(left.second)
              <<",\"exact_after_sha256\":"<<(available?quote_json(right.second):string("null"))
              <<",\"same_sign_different_proof\":"<<(explanation?"true":"false")<<'}';
    }
    const auto iface=(breaking||module_a!=module_b)?"breaking":extended?"additive":"unchanged";
    ostringstream out;
    out<<"{\"schema\":\"cl-release-comparison-v1\",\"baseline_sha256\":"<<quote_json(old_pin)
       <<",\"candidate_sha256\":"<<quote_json(new_pin)<<",\"goals_sha256\":"<<quote_json(sha256(goals))
       <<",\"root_before\":"<<quote_json(module_a)<<",\"root_after\":"<<quote_json(module_b)
       <<",\"interface\":"<<quote_json(iface)<<",\"scope\":"<<quote_json(scope)
       <<",\"scope_before_sha256\":"<<(baseline.scope_policy.empty()?string("null"):quote_json(sha256(baseline.scope_policy)))
       <<",\"scope_after_sha256\":"<<(candidate.scope_policy.empty()?string("null"):quote_json(sha256(candidate.scope_policy)))
       <<",\"observations\":{\"added\":"<<seed_added<<",\"removed\":"<<seed_removed<<",\"changed\":"<<seed_changed
       <<"},\"exports\":["<<exports.str()<<"],\"proofs\":["<<proofs.str()
       <<"],\"tested_outcomes_changed\":"<<belief_changed<<",\"same_outcome_different_proof\":"<<reasons_changed
       <<",\"semantic_equivalence_proved\":false,\"committable\":false}\n";
    auto result=out.str();
    require(result.size()<=1024*1024,"CL release comparison report exceeds output cap");
    return result;
}
