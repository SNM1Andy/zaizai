struct Automatic {
    string status,reason,patch;
    optional<Program> next_epoch;
    optional<Table> next_table;
};
Automatic vet_auto(const Program& p,const Table& base,const string& channel,const Continuity& state){
    Automatic a;
    const auto matching=p.auto_policy.find(channel);
    if(matching==p.auto_policy.end())return a;
    try{
        a.patch=render_synth(p,base);
        if(a.patch.empty()){a.status="no_change";return a;}
        require(a.patch.size()<=16384,"automatic patch too large");
        auto staged=state;
        staged.source+="\n"+a.patch;
        auto epoch=compile_active(staged);
        require(epoch.rules.size()>p.rules.size()&&epoch.rules.size()-p.rules.size()<=4,
                "automatic rule count out of bounds");
        const auto& allowed=matching->second;
        for(size_t i=p.rules.size();i<epoch.rules.size();++i){
            const auto& rule=epoch.rules[i];
            require(allowed.contains(rule.head.pred),"output outside automatic policy");
            require(epoch.live_guards.emplace(i,allowed.at(rule.head.pred)).second,"overlapping automatic rule");
            require(std::ranges::any_of(rule.body,[&](const Atom& x){
                return x.pred==allowed.at(rule.head.pred)&&x.args==rule.head.args;
            }),"required automatic guard missing");
        }
        set<string> outputs;
        for(size_t i=p.rules.size();i<epoch.rules.size();++i)outputs.insert(epoch.rules[i].head.pred);
        verify_effect_cone(epoch,allowed,outputs);
        auto table=run(epoch,state.inactive);
        const auto delta=changes(p,base,table);
        require(!delta.added.empty(),"automatic candidate has no clean derivation");
        require(delta.removed.empty()&&delta.added.size()<=16,"automatic impact not within bounds");
        for(const auto& fact:delta.added){
            require(allowed.contains(fact.pred),"derived effect outside automatic policy");
            require(!table.facts.contains(opposite_of(fact)),"automatic candidate would cause conflict");
            require(proof_without_conflict(base,{allowed.at(fact.pred),fact.args}),"automatic guard lacks clean proof");
        }
        a.status="ready";
        a.next_epoch=std::move(epoch);
        a.next_table=std::move(table);
    }catch(const runtime_error& e){
        a.status="blocked";a.reason=string(e.what()).substr(0,512);
    }
    return a;
}
