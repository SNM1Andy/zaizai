// A candidate is a typed rule head grounded by a live relational body witness.
// The rule may reorder, project, or constrain arguments. No Cartesian product
// of constants and predicate names is considered.
struct AgendaDiscovery {
    map<Atom,pair<Atom,size_t>> targets;
    vector<Atom> eligible;
    optional<pair<Atom,Atom>> choice;
    string review,grounding,limit;
    size_t unclean=0,disputed_dependencies=0,settled=0,covered=0;

    string reason()const{
        if(!limit.empty())return "scan_truncated";
        if(eligible.size()>1)return "tied";
        if(eligible.size()==1)return "pending_approval";
        if(covered)return "already_ticketed";
        if(disputed_dependencies)return "contested_dependencies";
        if(!targets.empty())return "no_distinguishing_gap";
        if(unclean)return "contested_or_unverified_grounding";
        if(settled)return "already_decided";
        return "insufficient_evidence";
    }
    string json(const Continuity& state,const string& revision)const{
        const bool unique=limit.empty()&&eligible.size()==1;
        ostringstream out;
        out<<"{\"schema\":\"pcgm-work-agenda-v1\",\"actor\":"<<quote_json(state.id)
           <<",\"revision_sha256\":"<<quote_json(revision)<<",\"scope\":\"typed_single_witness_rule_heads\""
           <<",\"reason\":"<<quote_json(reason())<<",\"limit\":"<<(limit.empty()?"null":quote_json(limit))
           <<",\"search_complete\":"<<(limit.empty()?"true":"false")<<",\"eligible_count\":"
           <<(limit.empty()?to_string(eligible.size()):"null")<<",\"eligible_goals\":[";
        if(limit.empty())for(size_t i=0;i<eligible.size();++i){if(i)out<<',';json_atom(out,eligible[i]);}
        out<<"],\"ticketed_count\":"<<covered<<",\"grounding\":"<<(unique?grounding:"null")
           <<",\"proposed_review\":"<<(unique?review:"null")
           <<",\"review_sha256\":"<<(unique?quote_json(sha256(review)):"null")
           <<",\"writes_state\":false,\"outbound\":false}";
        return out.str();
    }
};

optional<Atom> ground_agenda_head(const Atom& head,const Atom& pattern,const Atom& fact){
    map<string,string> bindings;
    for(size_t i=0;i<pattern.args.size();++i){
        const auto& term=pattern.args[i];
        if(!variable(term)){
            if(term!=fact.args[i])return nullopt;
        }else{
            const auto [at,inserted]=bindings.emplace(term,fact.args[i]);
            if(!inserted&&at->second!=fact.args[i])return nullopt;
        }
    }
    auto target=substitute(head,bindings);
    if(ranges::any_of(target.args,variable))return nullopt;
    target.pred=base_name(target);
    return target;
}

AgendaDiscovery scan_agenda(const Continuity& state,const string& revision,const Program& program,const Table* known=nullptr,const Atom* focus=nullptr){
    AgendaDiscovery scan;
    if(program.rules.size()>256 || program.observations.size()>2048){
        scan.limit="program_scope";return scan;
    }
    try{
        Table computed;
        if(!known)computed=run(program,state.inactive);
        const auto& actual=known?*known:computed;
        size_t probes=0;
        for(size_t i=0;i<program.rules.size();++i){
            const auto& rule=program.rules[i];
            if(focus&&base_name(rule.head)!=focus->pred)continue;
            if(!program.signatures.contains(base_name(rule.head)))continue;
            for(const auto& pattern:rule.body){
                if(comparison(pattern.pred)||!program.signatures.contains(base_name(pattern)))continue;
                for(auto it=actual.facts.lower_bound({pattern.pred,{}});it!=actual.facts.end()&&it->first.pred==pattern.pred;++it){
                    if(++probes>4096){scan.limit="grounding_probes";return scan;}
                    auto target=ground_agenda_head(rule.head,pattern,it->first);
                    if(!target||(focus&&*target!=*focus)||scan.targets.contains(*target))continue;
                    if(actual.facts.contains(*target)||actual.facts.contains(opposite_of(*target))){++scan.settled;continue;}
                    bool limited=false;
                    if(!proof_without_conflict(actual,it->first,&limited)){
                        if(limited){scan.limit="grounding_proof";return scan;}
                        ++scan.unclean;continue;
                    }
                    if(scan.targets.size()>=16){scan.limit="grounded_targets";return scan;}
                    scan.targets.emplace(*target,pair{it->first,i});
                }
            }
        }
        for(const auto& [goal,basis]:scan.targets){
            bool eligible=false,incomplete=false,clean=true;
            Atom need;
            auto review=compiled_goal_obligation(state,program,revision,goal,true,&eligible,&incomplete,&need,&clean);
            if(incomplete){scan.limit="premise_scan";return scan;}
            if(!eligible)continue;
            if(!clean){++scan.disputed_dependencies;continue;}
            if(!focus&&ranges::any_of(state.questions,[&](const auto& item){return matches_question(item.second,need);})){
                ++scan.covered;continue;
            }
            scan.eligible.push_back(goal);
            if(scan.eligible.size()==1){
                scan.choice=pair{goal,need};
                scan.review=move(review);
                ostringstream context;
                const auto& [witness,ordinal]=basis;
                context<<"{\"rule_number\":"<<(program.rule_numbers.empty()?ordinal+1:program.rule_numbers.at(ordinal))
                       <<",\"witness\":";json_atom(context,witness);
                context<<",\"proof\":";json_branch(context,actual,witness);context<<'}';
                scan.grounding=context.str();
            }
        }
    }catch(const runtime_error& error){
        const string message=error.what();
        if(message!="join budget"&&message!="fixpoint budget"&&message!="fact limit")throw;
        scan.limit=message;
    }
    return scan;
}

AgendaDiscovery discover_agenda(const Continuity& state,const string& revision){
    return scan_agenda(state,revision,compile_active(state));
}

// Recover the approved ticket's live dependency basis independently of new
// competing targets. An unrelated dialogue turn does not change its address.
string agenda_ticket_context(const Continuity& state,const Program& program,const Table& table,const LocalQuestion& q){
    const auto seed=sha256("PCGM-AGENDA-TICKET-CONTEXT-1\n"+state.id+"\n"+show(q.goal)+"\n"+show(q.fact));
    const auto scan=scan_agenda(state,seed,program,&table,&q.goal);
    if(!scan.limit.empty()||!scan.choice||scan.choice->second!=q.fact)return {};
    SliceStats scope;
    const auto slice=query_slice(program,{q.goal},scope);
    string rules;
    for(size_t i=0;i<slice.rules.size();++i){
        rules+=show(slice.rules[i].head)+" <-";
        for(const auto& term:slice.rules[i].body)rules+=" "+show(term);
        if(const auto guard=slice.live_guards.find(i);guard!=slice.live_guards.end())rules+=" guard "+guard->second;
        rules+='\n';
    }
    return sha256(seed+"\n"+rules+scan.grounding+"\n"+scan.review);
}

string agenda_approval(const string& actor,const string& head,const string& review){
    require(valid_identity(actor)&&head.size()==64&&hex_chars(head)&&review.size()==64&&hex_chars(review),
            "agenda approval needs an actor and exact revision/review pins");
    return "PCGM-LOCAL-AGENDA-APPROVAL-1\n"+actor+"\n"+head+"\n"+review+"\n";
}
