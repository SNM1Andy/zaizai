void verify_effect_cone(const Program& epoch,const map<string,string>& allowed,const set<string>& outputs){
    set<string> reached=outputs;
    vector<string> walk(outputs.begin(),outputs.end());
    for(size_t i=0;i<walk.size();++i){
        for(const auto& r:epoch.rules){
            if(std::ranges::none_of(r.body,[&](const Atom& premise){return premise.pred==walk[i];}))continue;
            require(allowed.contains(r.head.pred),"derived effect outside automatic policy");
            if(reached.insert(r.head.pred).second)walk.push_back(r.head.pred);
        }
    }
}
// Mark automatic rules from the committed journal and immutable source offsets.
Program compile_active(const Continuity& state){
    auto p=compile(effective_artifact_source(state));
    for(const auto& [id,fact]:state.observation_batch_facts)
        require(p.observations.contains(id)&&p.observations.at(id)==fact,
                "durable observation batch differs from its source fact");

    auto verify_origin=[&](const string& name,const string& label){
        const auto end=name.find("__");
        require(name.starts_with("artifact_")&&end!=string::npos&&end>9,"unbound CLIR origin");
        const auto alias=name.substr(9,end-9);
        require(state.artifacts.contains(alias)&&label.starts_with("CLIR:"+state.artifacts.at(alias)+":"),
                "artifact origin lacks matching receipt");
    };
    for(const auto& [id,label]:p.observation_labels)verify_origin(id,label);
    for(size_t i=0;i<p.rules.size();++i)
        if(!p.rule_labels.at(i).empty())verify_origin(base_name(p.rules[i].head),p.rule_labels.at(i));
    map<string,string> channels;
    for(const auto& [key,receipt]:state.automatic)
        if(state.plans.contains(receipt.status))channels.emplace(receipt.status,key.first);
    for(const auto& id:state.active_revisions){
        const auto channel=channels.find(id);
        if(channel==channels.end())continue;
        const auto& plan=state.plans.at(id);
        expect_patch(state,plan);
        const auto begin=state.source.begin()+static_cast<ptrdiff_t>(plan.offset+1);
        const auto end=begin+static_cast<ptrdiff_t>(plan.patch.size());
        const auto first=count(state.source.begin(),begin,'\n')+1;
        const auto last=first+count(begin,end,'\n')-1;
        const auto& policy=p.auto_policy.at(channel->second);
        size_t tagged=0;set<string> outputs;
        for(size_t i=0;i<p.rules.size();++i){
            const auto line=p.rule_lines.at(i);
            if(line<first||line>last)continue;
            const auto& r=p.rules[i];
            require(policy.contains(r.head.pred),"persisted automatic output not approved");
            require(p.live_guards.emplace(i,policy.at(r.head.pred)).second,"automatic rule spans overlap");
            outputs.insert(r.head.pred);
            ++tagged;
        }
        require(tagged>0&&tagged<=4,"automatic revision did not resolve to bounded rules");
        verify_effect_cone(p,policy,outputs);
    }
    return p;
}
