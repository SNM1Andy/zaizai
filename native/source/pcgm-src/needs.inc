// Inspect candidate paths under the same, explicit signed-fact semantics as run().
Atom substitute(Atom a,const map<string,string>& env){
    for(auto& x:a.args)
        if(auto it=env.find(x); it!=env.end()) x=it->second;
    return a;
}

using Why = pair<Atom,Atom>;
vector<Why> missing_inputs(const Program& p,const Table& t,ostream* log=nullptr,bool* complete=nullptr){
    vector<Why> result;
    if(complete)*complete=true;
    ostringstream silent;
    auto& cout=log?*log:static_cast<ostream&>(silent);
    size_t budget=20000;
    map<string,vector<const Atom*>> idx;
    size_t fold_rows=0;
    JoinIndex fold_index(fold_rows,nullptr);
    const bool has_fold=std::ranges::any_of(p.rules,[](const Rule& r){
        return std::ranges::any_of(r.body,[](const auto& atom){return sealed_calculation(atom.pred);});
    });
    for(const auto& [a,_]:t.facts){
        idx[a.pred].push_back(&a);
        if(has_fold)fold_index.add(&a);
    }
    for(const auto& goal:p.goals){
        cout<<"goal "<<show(goal)<<' ';
        auto opposite=goal; opposite.pred="!"+opposite.pred;
        if(t.facts.contains(goal)){
            cout<<(t.facts.contains(opposite)?"conflict":"supported")<<'\n';
            continue;
        }
        cout<<(t.facts.contains(opposite)?"negative_only":"unknown")<<'\n';
        set<pair<size_t,string>> found;
        set<Atom> askable;
        bool route=false, exhausted=false;
        for(size_t i=0;i<p.rules.size() && !exhausted;++i){
            const auto& r=p.rules[i];
            if(r.head.pred!=goal.pred || r.head.args.size()!=goal.args.size()) continue;
            using Env=map<string,string>;
            auto unify=[](const Atom& pat,const Atom& g,Env& env){
                for(size_t j=0;j<pat.args.size();++j){
                    const auto& x=pat.args[j];
                    if(!variable(x)){if(x!=g.args[j]) return false;}
                    else {
                        const auto [it,ok]=env.try_emplace(x,g.args[j]);
                        if(!ok && it->second!=g.args[j]) return false;
                    }
                }
                return true;
            };
            Env head;
            if(!unify(r.head,goal,head)) continue;
            route=true;
            std::function<void(size_t,const Env&)> visit=[&](size_t k,const Env& env){
                if(exhausted||k==r.body.size()) return;
                const auto& pattern=r.body[k];
                if(comparison(pattern.pred)){
                    auto next=env;
                    auto check=pattern;
                    bool satisfied=false;
                    if(sealed_calculation(check.pred)){
                        vector<const Atom*> witnesses;
                        const auto charge=[&]{if(budget==0)throw EvaluationLimit("closed fold needs scan budget");--budget;};
                        try{satisfied=unit_conversion(check.pred)?lookup_unit_conversion(fold_index,check,next,witnesses,charge):
                            lookup_closed_fold(p,fold_index,check,next,witnesses,charge);}
                        catch(const EvaluationLimit&){exhausted=true;return;}
                    }else satisfied=eval_builtin(check,next);
                    if(satisfied)visit(k+1,next);
                    else found.emplace(i+1,"constraint_not_met "+show(check));
                    if(found.size()>=64)exhausted=true;
                    return;
                }
                bool matched=false;
                if(const auto it=idx.find(pattern.pred); it!=idx.end())
                    for(const auto* fact:it->second){
                        if(budget==0){exhausted=true;return;}
                        --budget;
                        auto next=env;
                        if(unify(pattern,*fact,next)){matched=true; visit(k+1,next);}
                        if(exhausted) return;
                    }
                if(matched) return;
                auto missing=substitute(pattern,env);
                const auto ground=std::ranges::none_of(missing.args,variable);
                if(!ground&&complete)*complete=false;
                auto contrary=missing; contrary.pred=missing.pred.starts_with("!")
                    ?missing.pred.substr(1):"!"+missing.pred;
                string reason=!ground?"unbound_pattern":t.facts.contains(contrary)?"opposing_evidence":"missing_evidence";
                found.emplace(i+1,reason+" "+show(missing));
                if(reason=="missing_evidence" && !missing.pred.starts_with("!") && missing!=goal)
                    askable.insert(missing);
                if(found.size()>=64) exhausted=true;
            };
            visit(0,head);
        }
        for(const auto& [rule,msg]:found) cout<<"  r"<<rule<<" "<<msg<<'\n';
        if(!route) cout<<"  no_matching_rule_or_positive_observation\n";
        if(exhausted){if(complete)*complete=false;cout<<"  scan_budget_exhausted\n";}
        if(!exhausted && !t.facts.contains(opposite))
            for(const auto& fact:askable) result.emplace_back(goal,fact);
    }
    cout<<"needs_end goals="<<p.goals.size()<<'\n';
    return result;
}
