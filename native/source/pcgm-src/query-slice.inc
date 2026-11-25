struct SliceStats { size_t relations=0,rules=0,observations=0; };
Program query_slice(const Program& program,const vector<Atom>& goals,SliceStats& stats){
    auto kept=program;
    kept.rules.clear();kept.rule_labels.clear();kept.rule_lines.clear();kept.rule_numbers.clear();
#ifdef PCGM_SLICE_GUARDS
    kept.live_guards.clear();
#endif
    kept.goals.clear();kept.goals.insert(goals.begin(),goals.end());
    map<string,vector<size_t>> produced;
    for(size_t i=0;i<program.rules.size();++i)
        produced[base_name(program.rules[i].head)].push_back(i);
    set<string> included;
    vector<string> todo;
    auto mark=[&](const string& relation){if(included.insert(relation).second)todo.push_back(relation);};
    for(const auto& target:goals)mark(base_name(target));
    set<size_t> keep_rules;
    for(size_t i=0;i<todo.size();++i){
        const auto rs=produced.find(todo[i]);
        if(rs==produced.end())continue;
        for(const auto ordinal:rs->second){
            if(!keep_rules.insert(ordinal).second)continue;
            for(const auto& pred:program.rules[ordinal].body)
                if(sealed_calculation(pred.pred))mark(pred.args.at(0));
                else if(!comparison(pred.pred))mark(base_name(pred));
#ifdef PCGM_SLICE_GUARDS
            if(const auto g=program.live_guards.find(ordinal);g!=program.live_guards.end())mark(g->second);
#endif
        }
    }
    for(const auto n:keep_rules){
#ifdef PCGM_SLICE_GUARDS
        if(const auto g=program.live_guards.find(n);g!=program.live_guards.end())
            kept.live_guards.emplace(kept.rules.size(),g->second);
#endif
        kept.rules.push_back(program.rules[n]);
        kept.rule_numbers.push_back(program.rule_numbers.empty()?n+1:program.rule_numbers[n]);
        if(!program.rule_labels.empty())kept.rule_labels.push_back(program.rule_labels[n]);
        if(!program.rule_lines.empty())kept.rule_lines.push_back(program.rule_lines[n]);
    }
    erase_if(kept.observations,[&](const auto& point){return !included.contains(base_name(point.second));});
    stats={included.size(),kept.rules.size(),kept.observations.size()};
    return kept;
}
