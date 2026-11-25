string anchored_goal_obligation(const Continuity& state,const string& revision,const string& from,const string& to,optional<pair<Atom,Atom>>* choice=nullptr){
    if(choice)choice->reset();
    const auto current=compile_active(state);
    require(from!=to&&current.signatures.contains(from)&&current.signatures.contains(to),
            "anchored review needs two distinct declared predicates");
    const auto& types=current.signatures.at(from);
    require(!types.empty()&&types.size()<=4&&types==current.signatures.at(to),
            "anchored review signatures differ");
    SliceStats deps;
    const auto linked=query_slice(current,{{to,{}}},deps);
    require(deps.rules<=256&&deps.observations<=2048,"anchored review target scope exceeds budget");
    require(ranges::any_of(linked.rules,[&](const auto& r){
        return ranges::any_of(r.body,[&](const auto& term){
            return sealed_calculation(term.pred)?term.args.at(0)==from:
                   !comparison(term.pred)&&base_name(term)==from;
        });
    }),"anchor is not a native dependency of the target");
    SliceStats sizes;
    auto source=query_slice(current,{{from,{}}},sizes);
    source.goals.clear();
    require(sizes.rules<=256&&sizes.observations<=2048,"anchored review source scope exceeds budget");
    const auto observed=run(source,state.inactive);
    vector<Atom> targets;
    size_t inspected=0;
    bool complete=true;
    for(const auto& [fact,_]:observed.facts){
        if(fact.pred!=from)continue;
        if(++inspected>8){complete=false;break;}
        auto opposite=fact;opposite.pred="!"+from;
        if(observed.facts.contains(opposite))continue;
        Atom target{to,fact.args};
        if(!current.goals.contains(target))targets.push_back(move(target));
    }
    size_t candidates=0;
    string proposal;
    optional<pair<Atom,Atom>> selected;
    if(complete)for(const auto& target:targets){
        bool eligible=false,uncertain=false;
        Atom premise;
        const auto report=goal_obligation(state,revision,target,true,&eligible,&uncertain,&premise);
        if(uncertain){complete=false;break;}
        if(eligible){++candidates;proposal=report;selected=pair{target,premise};}
    }
    if(complete&&candidates==1&&choice)*choice=selected;
    ostringstream out;
    out<<"{\"schema\":\"pcgm-anchored-goal-obligation-v1\",\"actor\":"<<quote_json(state.id)
       <<",\"revision_sha256\":"<<quote_json(revision)
       <<",\"search_complete\":"<<(complete?"true":"false")
       <<",\"eligible_count\":";
    if(complete)out<<candidates;else out<<"null";
    out<<",\"proposed_review\":"<<((complete&&candidates==1)?proposal:"null")
       <<",\"promotes_goal\":false,\"writes_state\":false,\"outbound\":false}";
    return out.str();
}
