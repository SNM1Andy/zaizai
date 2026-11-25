// A host tick carries no rule text, observations or preferred winner. Authority
// for each unary rule is the program's existing @ schema. All trials are copies.
string repair_rule(const Rule& rule){
    string text=show(rule.head);
    for(size_t i=0;i<rule.body.size();++i)text+=(i?" & ":" <- ")+show(rule.body[i]);
    return text+".\n";
}

string repair_cl_check(const Program& p,const Table& table,const set<string>& inactive,const set<Atom>& goals){
    require(!goals.empty()&&goals.size()<=32,"repair check needs 1..32 distinct cases");
    SliceStats sizes;
    const auto slice=query_slice(p,{goals.begin(),goals.end()},sizes);
    require(slice.live_guards.empty()&&sizes.rules<=128&&sizes.observations<=512,
            "repair check exceeds independent CL proof scope");
    string source;
    for(const auto& [name,types]:slice.signatures){
        source+=": "+name+"(";
        for(size_t i=0;i<types.size();++i)source+=(i?",":"")+type_text(types[i]);
        source+=").\n";
    }
    for(const auto& rule:slice.rules)source+=repair_rule(rule);
    for(const auto& [id,fact]:slice.observations)
        if(!inactive.contains(id))source+="& "+id+" "+show(fact)+".\n";
    vector<string> expected;
    for(const auto& goal:goals){
        source+="? "+show(goal)+".\n";
        expected.push_back(truth_state(table,goal));
    }
    require(cl_native::checked_repair_statuses(source)==expected,"CL and PCGM repair proofs differ");
    return sha256(source);
}

struct RepairEvidence {
    string rule,reference_pin;
    set<string> witnesses,origins;
};

void repair_origins(const Table& table,const Atom& root,RepairEvidence& evidence){
    set<Atom> seen;
    vector<Atom> queue{root};
    for(size_t i=0;i<queue.size();++i){
        const auto fact=queue.at(i);
        if(!seen.insert(fact).second)continue;
        const auto& proof=table.facts.at(fact);
        evidence.origins.insert(proof.origin);
        require(seen.size()<=64&&evidence.origins.size()<=64,"repair witness proof exceeds budget");
        queue.insert(queue.end(),proof.parents.begin(),proof.parents.end());
    }
}

// Preserve both signs of a real held-out negative case. Wishes measure
// improvement, while independent hard cases and the output boundary can veto it.
set<Atom> repair_cases(const Program& p,const Table& before,const string& output){
    set<Atom> goals;
    bool negative=false,positive=false;
    for(const auto& pref:p.preferences){
        if(pref.when&&!proof_without_conflict(before,*pref.when))continue;
        goals.insert(pref.proposition);
        if(pref.proposition.pred!=output)continue;
        negative|=pref.hard&&pref.expected=="NEGATIVE"&&
                  before.facts.contains(opposite_of(pref.proposition));
        positive|=!pref.hard&&pref.expected=="POSITIVE";
    }
    require(negative&&positive,"repair scope needs active positive cases and a signed hard negative control");
    return goals;
}

void repair_validate(Option& option,RepairEvidence& evidence,Continuity next,const Program& p,
                     const Table& before,const string& output){
    auto candidate=compile_active(next);
    auto after=run(candidate,next.inactive);
    const auto delta=changes(p,before,after);
    require(delta.added.size()+delta.removed.size()<=64,"repair changes more than 64 facts");
    for(const auto* changed:{&delta.added,&delta.removed})for(const auto& fact:*changed)
        require(base_name(fact)==output,"repair affects predicates beyond its authorized output");
    evidence.reference_pin=repair_cl_check(candidate,after,next.inactive,repair_cases(p,before,output));
    score(option,p,before,after);
    // A candidate must not introduce unreviewed conflicts outside the fixed
    // preference examples, even when every named positive and negative passes.
    for(const auto& fact:delta.added)if(after.facts.contains(opposite_of(fact)))
        option.error="candidate introduces opposing support for "+show(fact);
    option.state=move(next);option.program=move(candidate);option.table=move(after);
}

const string repair_marker="# pcgm bounded repair v1 ";
bool repair_terminal_output(const Program& p,const string& output){
    for(const auto* prefix:{"gen_","ir_","geom_"})if(output.starts_with(prefix))return false;
    if(output=="outcome"||output=="measured_outcome")return false;
    for(const auto& rule:p.rules)for(const auto& term:rule.body){
        if(sealed_calculation(term.pred)&&term.args.at(0)==output)return false;
        if(!comparison(term.pred)&&base_name(term)==output)return false;
    }
    for(const auto& [_,guard]:p.live_guards)if(guard==output)return false;
    for(const auto& schema:p.schemas)if(schema.premise==output||schema.trigger==output)return false;
    for(const auto& pref:p.preferences)if(pref.when&&base_name(*pref.when)==output)return false;
    for(const auto& [_,condition]:p.experience_contexts)if(base_name(condition)==output)return false;
    for(const auto* policies:{&p.sensor_policy,&p.synth_policy,&p.multi_policy})
        for(const auto& [_,inputs]:*policies)if(inputs.contains(output)||inputs.contains("!"+output))return false;
    return true;
}
void repair_rewrite(Option& o,RepairEvidence& evidence,const Continuity& state,const Program& p,
                    const Table& table,const Schema& schema){
    require(p.signatures.contains(schema.result)&&p.signatures.contains(schema.premise)&&
            p.signatures.contains(schema.trigger),"repair requires explicit unary signatures");
    const Rule rule{{schema.result,{"$x"}},{{schema.premise,{"$x"}}}};
    evidence.rule=repair_rule(rule);
    require(repair_terminal_output(p,schema.result),"repair output is an input to downstream rules or runtime policy");
    require(ranges::find(p.rules,rule)==p.rules.end(),"authorized rule already active");
    // Discover repeated subjects from live trigger evidence. A new subject need
    // not be listed in the host's frozen validation cases or registered goals.
    for(const auto& [trigger,_]:table.facts){
        if(trigger.pred!=schema.trigger)continue;
        const Atom goal{schema.result,trigger.args},premise{schema.premise,trigger.args};
        if(truth_state(table,goal)!="UNKNOWN")continue;
        if(!proof_without_conflict(table,trigger)||!proof_without_conflict(table,premise))continue;
        evidence.witnesses.insert(show(goal));
        require(evidence.witnesses.size()<=32,"repair exceeds 32 distinct stalled cases");
        repair_origins(table,trigger,evidence);
        repair_origins(table,premise,evidence);
    }
    require(evidence.witnesses.size()>=2,"fewer than two distinct unresolved cases with clean trigger and premise");
    string patch=repair_marker+schema.result+"\n";
    for(const auto& witness:evidence.witnesses)patch+="# unresolved "+witness+"\n";
    for(const auto& origin:evidence.origins)patch+="# support "+origin+"\n";
    patch+=evidence.rule;
    require(patch.size()<=16384&&state.plans.size()<128,"repair proposal exceeds plan budget");
    auto next=state;
    o.revision="p"+to_string(next.events.size()+1);
    const auto base=revision_snapshot(state);
    const auto pos=next.source.size();
    next.events.push_back("proposal "+base+" "+to_hex(patch));
    next.events.push_back("apply "+o.revision+" "+to_string(pos));
    next.plans.emplace(o.revision,RevisionPlan{base,patch,pos,true,false});
    next.active_revisions.push_back(o.revision);
    next.source+="\n"+patch;
    ++next.epoch;
    repair_validate(o,evidence,move(next),p,table,schema.result);
}

void repair_rollback(Option& o,RepairEvidence& evidence,const Continuity& state,const Program& p,
                     const Table& table){
    require(!state.active_revisions.empty(),"no active bounded repair");
    auto next=state;
    o.revision=next.active_revisions.back();
    auto& plan=next.plans.at(o.revision);
    require(plan.patch.starts_with(repair_marker),"latest revision is outside the bounded repair scope");
    const auto end=plan.patch.find('\n');
    const auto output=plan.patch.substr(repair_marker.size(),end-repair_marker.size());
    const auto schema=ranges::find_if(p.schemas,[&](const auto& item){
        const string text=item.result+"($x) <- "+item.premise+"($x).\n";
        return item.result==output&&plan.patch.ends_with(text);
    });
    require(schema!=p.schemas.end(),"rollback output is outside the active repair policy");
    evidence.rule=output+"($x) <- "+schema->premise+"($x).\n";
    expect_patch(next,plan);
    next.source.erase(plan.offset,plan.patch.size()+1);
    plan.reverted=true;
    next.active_revisions.pop_back();
    next.events.push_back("revert "+o.revision);
    ++next.epoch;
    repair_validate(o,evidence,move(next),p,table,output);
}

// Evaluate both signs of the first exact missing input. Neither branch can
// authorize a write. An accepted answer on the independent host pipe changes
// the basis and the next tick scores the actual evidence.
string repair_knowledge(Option& option,const Continuity& state,const Program& p,const Table& table){
    auto focus=p;
    focus.goals.clear();
    for(const auto& pref:p.preferences)
        if(!pref.hard&&truth_state(table,pref.proposition)=="UNKNOWN"&&
           (!pref.when||proof_without_conflict(table,*pref.when)))focus.goals.insert(pref.proposition);
    bool complete=true;
    const auto gaps=missing_inputs(focus,table,nullptr,&complete);
    option.error=complete?"no exact missing input in current cases":"incomplete missing-input scan";
    if(!complete||gaps.empty())return "null";
    const auto& [goal,premise]=gaps.front();
    option.error="requires an independently approved evidence answer";
    ostringstream out;
    out<<"{\"goal\":";json_atom(out,goal);out<<",\"premise\":";json_atom(out,premise);
    out<<",\"gap_count\":"<<gaps.size()<<",\"ticket\":";
    auto ticket=ranges::find_if(state.questions,[&](const auto& row){return matches_question(row.second,premise);});
    if(ticket==state.questions.end())out<<"null";else out<<quote_json(ticket->first);
    out<<",\"hypotheses\":[";
    for(size_t n=0;n<2;++n){
        auto branch=p;
        const string id="repair_trial_"+sha256(show(premise)).substr(0,24);
        require(!branch.observations.contains(id)&&!state.inactive.contains(id),"repair trial tag collision");
        branch.observations.emplace(id,n?opposite_of(premise):premise);
        const auto after=run(branch,state.inactive);
        Option evaluation("knowledge");
        score(evaluation,p,table,after);
        if(n)out<<',';
        out<<"{\"polarity\":"<<quote_json(n?"negative":"positive")<<",\"status\":"<<quote_json(truth_state(after,goal))
           <<",\"wishes\":"<<evaluation.wishes<<",\"hard_cases_pass\":"<<(evaluation.error.empty()?"true":"false")<<"}";
    }
    return out.str()+"],\"writes_state\":false}";
}

string bounded_repair(StateStore& store,Continuity& state,Program& p,Table& table,bool execute){
    require(!p.schemas.empty()&&p.schemas.size()<=8,"bounded repair needs 1..8 locally authorized @ schemas");
    require(p.preferences.size()<=32,"repair criterion budget exceeded");
    vector<Option> options;
    for(const auto* kind:{"stay","knowledge","rollback"})options.emplace_back(kind);
    vector<RepairEvidence> evidence(3);
    score(options.front(),p,table,table);
    string knowledge="null";
    try{knowledge=repair_knowledge(options[1],state,p,table);}
    catch(const runtime_error& error){options[1].error=error.what();}
    try{repair_rollback(options[2],evidence[2],state,p,table);}
    catch(const runtime_error& error){options[2].error=error.what();}
    for(const auto& schema:p.schemas){
        options.emplace_back("rewrite");evidence.emplace_back();
        try{repair_rewrite(options.back(),evidence.back(),state,p,table,schema);}
        catch(const runtime_error& error){options.back().error=error.what();}
    }
    const auto chosen=best_choice(options);
    const bool write=execute&&chosen&&options[*chosen].name!="stay";
    const auto decision=render_decision(state,options,chosen,write,"bounded_repair_v1");
    const auto head=sha256(encode(state));
    string event;
    if(write){
        auto& best=options.at(*chosen);
        auto& next=*best.state;
        next.events.push_back("decision "+best.name+" "+best.revision+" "+revision_snapshot(state)+" "+
                              to_string(best.wishes)+" "+to_string(best.risk)+" "+to_string(best.changes));
        event="e"+to_string(next.events.size());
        record_experience_context(next,p,table);
        retain_decision(next,event,decision);
        add_notices(next,table,*best.table);
        store.save(next);
        state=move(next);p=move(*best.program);table=move(*best.table);
    }
    ostringstream out;
    out<<"{\"schema\":\"pcgm-bounded-repair-v1\",\"actor\":"<<quote_json(state.id)
       <<",\"basis_sha256\":"<<quote_json(head)<<",\"head_sha256\":"<<quote_json(sha256(encode(state)))
       <<",\"decision_event\":"<<(event.empty()?"null":quote_json(event))<<",\"writes_state\":"<<(write?"true":"false")
       <<",\"decision\":"<<decision<<",\"knowledge_review\":"<<knowledge<<",\"rule_reviews\":[";
    for(size_t i=2;i<options.size();++i){
        if(i!=2)out<<',';
        const auto& record=evidence[i];
        out<<"{\"option_index\":"<<i<<",\"rule\":"<<quote_json(record.rule)
           <<",\"compiled_cl_slice_sha256\":"<<(record.reference_pin.empty()?"null":quote_json(record.reference_pin))
           <<",\"stalled_cases\":[";
        bool first=true;
        for(const auto& witness:record.witnesses){if(!first)out<<',';out<<quote_json(witness);first=false;}
        out<<"],\"proof_origins\":[";first=true;
        for(const auto& origin:record.origins){if(!first)out<<',';out<<quote_json(origin);first=false;}
        out<<"]}";
    }
    return out.str()+"]}";
}
