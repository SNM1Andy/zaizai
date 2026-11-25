string decision_window(const Continuity& state,unsigned from,unsigned limit){
    require(from<=state.events.size()&&limit>0&&limit<=8,"invalid coherent decision cursor");
    ostringstream out;
    out<<"{\"from\":"<<from<<",\"results\":[";
    unsigned cursor=from,count=0;
    bool more=false;
    for(size_t i=from;i<state.events.size();++i){
        const auto& entry=state.events[i];
        if(!entry.starts_with("decision "))continue;
        if(count==limit){more=true;break;}
        if(count++)out<<',';
        cursor=static_cast<unsigned>(i+1);
        const auto key="e"+to_string(cursor);
        istringstream row(entry.substr(9));
        string kind,target;row>>kind>>target;
        const auto saved=state.decision_traces.find(key);
        out<<"{\"event\":"<<cursor<<",\"id\":"<<quote_json(key)<<",\"kind\":"<<quote_json(kind)
            <<",\"target\":"<<quote_json(target)<<",\"trace\":"<<(saved==state.decision_traces.end()?"null":saved->second)<<'}';
    }
    if(!more)cursor=static_cast<unsigned>(state.events.size());
    out<<"],\"cursor\":"<<cursor<<",\"more\":"<<(more?"true":"false")<<'}';
    return out.str();
}
string pinned_review(StateStore& reader,const Continuity& latest,const string& name,const string& digest,
                     unsigned decisions,unsigned notices,unsigned maximum,const vector<Atom>& goals){
    require(!digest.empty(),"pinned review requires expected snapshot SHA-256");
    const auto pin=latest.pins.find(name);
    require(pin!=latest.pins.end(),"unknown evidence pin");
    require(pin->second.digest==digest,"pinned review snapshot SHA-256 mismatch");
    const auto saved=verify_episode(reader,latest,pin->second);
    require(notices<=saved.events.size(),"pinned review notice cursor beyond snapshot");
    string proof="null";
    if(!goals.empty()){
        const auto program=compile_active(saved);
        for(const auto& goal:goals)validate_time_query(program,goal);
        proof=json_report(run(program,saved.inactive),goals,"pcgm",channel_context(saved));
    }
    auto value="{\"schema\":\"pcgm-pinned-review-v1\",\"label\":"+quote_json(name)+
        ",\"snapshot_sha256\":"+quote_json(digest)+",\"status\":"+channel_status(saved)+
        ",\"proofs\":"+proof+",\"decisions\":"+decision_window(saved,decisions,maximum)+
        ",\"notices\":"+notice_report(saved,notices,"")+"}";
    require(value.size()<=2*1024*1024,"pinned review exceeds 2 MiB");
    return value;
}

string reconstructed_basis(StateStore& reader,const Continuity& live,const string& id,const vector<Atom>& goals,
                           const string& head){
    const auto saved=live.choice_outcomes.find(id);
    const auto pinned=live.pins.find("basis_"+id);
    string output="{\"schema\":\"pcgm-choice-basis-v1\",\"id\":"+quote_json(id)+
        ",\"individual\":"+quote_json(live.id);
    if(saved==live.choice_outcomes.end())return output+",\"status\":\"not_recorded\"}";
    if(!live.choice_bases.contains(id))return output+",\"status\":\"basis_not_recorded\",\"decision\":"+saved->second.receipt+"}";
    require(pinned!=live.pins.end()&&saved->second.basis==pinned->second.digest,"choice basis does not match its recorded outcome");
    const auto basis=verify_episode(reader,live,pinned->second);
    output+=",\"status\":\"verified\",\"basis_sha256\":"+quote_json(saved->second.basis)+
        ",\"head_sha256\":"+quote_json(head)+",\"before\":"+channel_context(basis)+
        ",\"now\":"+channel_context(live)+",\"decision\":"+saved->second.receipt+",\"comparisons\":[";
    if(!goals.empty()){
        const auto earlier=compile_active(basis),current=compile_active(live);
        const auto earlier_facts=run(earlier,basis.inactive),now_facts=run(current,live.inactive);
        auto proof=[](const Program& p,const Table& table,const Atom& goal){
            try{validate_time_query(p,goal);}catch(const runtime_error&){return string("{\"status\":\"UNAVAILABLE\"}");}
            ostringstream result;json_fact(result,table,goal);return result.str();
        };
        for(size_t i=0;i<goals.size();++i){
            const auto& goal=goals[i];
            require(!goal.pred.starts_with('!')&&std::ranges::none_of(goal.args,variable),"choice basis expects an unsigned ground goal");
            if(i)output+=',';
            output+="{\"goal\":"+quote_json(show(goal))+",\"before\":"+proof(earlier,earlier_facts,goal)+
                    ",\"now\":"+proof(current,now_facts,goal)+"}";
        }
    }
    output+="]}";require(output.size()<=2*1024*1024,"choice basis proof comparison too large");
    return output;
}

string counterfactual_option(StateStore& reader,const Continuity& live,const string& id,unsigned index,
                             const vector<Atom>& goals){
    const auto outcome=live.choice_outcomes.find(id);
    const auto named=live.pins.find("basis_"+id);
    string out="{\"schema\":\"pcgm-counterfactual-proof-v1\",\"id\":"+quote_json(id)+
        ",\"individual\":"+quote_json(live.id)+",\"option_index\":"+to_string(index);
    if(outcome==live.choice_outcomes.end())return out+",\"status\":\"not_recorded\"}";
    if(!live.choice_bases.contains(id))return out+",\"status\":\"basis_not_recorded\"}";
    require(named!=live.pins.end()&&named->second.digest==outcome->second.basis,
            "counterfactual basis does not match recorded choice");
    const auto basis=verify_episode(reader,live,named->second);
    const auto program=compile_active(basis);
    const auto table=run(program,basis.inactive);
    const auto evaluated=run_frozen_choice(basis,program,table,reader);
    const auto recomputed=render_decision(basis,evaluated.options,evaluated.selected,outcome->second.kind=="committed",
                                         "live_job:"+id);
    require(recomputed==outcome->second.receipt,"historical option recomputation differs from its recorded choice");
    require(index<evaluated.options.size(),"counterfactual option index outside recorded set");
    const auto& option=evaluated.options[index];
    const auto chosen=evaluated.selected.has_value()&&*evaluated.selected==index;
    out+=",\"basis_sha256\":"+quote_json(outcome->second.basis)+",\"choice_receipt_sha256\":"+quote_json(sha256(recomputed))+
         ",\"kind\":"+quote_json(option.name)+",\"target\":"+quote_json(option.revision)+
         ",\"was_selected\":"+(chosen?"true":"false");
    if(!option.error.empty())return out+",\"status\":\"blocked\",\"reason\":"+quote_json(option.error.substr(0,240))+"}";
    require(option.name=="stay"||(option.program.has_value()&&option.table.has_value()),"eligible alternative has no evaluation");
    const auto& evaluated_program=option.name=="stay"?program:*option.program;
    const auto& evaluated_table=option.name=="stay"?table:*option.table;
    out+=",\"status\":\"verified\",\"results\":[";
    for(size_t i=0;i<goals.size();++i){
        if(i)out+=',';
        const auto& goal=goals[i];
        require(!goal.pred.starts_with('!')&&std::ranges::none_of(goal.args,variable),
                "counterfactual query must be an unsigned ground goal");
        bool available=true;
        try{validate_time_query(evaluated_program,goal);}catch(const runtime_error&){available=false;}
        out+="{\"goal\":"+quote_json(show(goal))+",\"proof\":";
        if(available){ostringstream result;json_fact(result,evaluated_table,goal);out+=result.str();}
        else out+="{\"status\":\"UNAVAILABLE\"}";
        out+="}";
    }
    out+="]}";require(out.size()<=2*1024*1024,"counterfactual proof report too large");
    return out;
}

struct ReplayObservation {string id;Atom fact;bool added,active;};
vector<ReplayObservation> later_observation_overlay(const Continuity& original,const Program& before,
                                                      const Continuity& target,const Program& after){
    set<string> edits;
    for(const auto& id:target.recorded_observations)
        if(!original.recorded_observations.contains(id))edits.insert(id);
    for(const auto& id:target.inactive)
        if(!original.inactive.contains(id))edits.insert(id);
    for(const auto& id:original.inactive)
        if(!target.inactive.contains(id))edits.insert(id);
    require(edits.size()<=32,"choice reassessment supports at most 32 observation changes");
    vector<ReplayObservation> result;
    for(const auto& id:edits){
        const auto b=before.observations.find(id),a=after.observations.find(id);
        require(a!=after.observations.end(),"later observation identity is unavailable");
        const bool new_id=b==before.observations.end();
        if(new_id)
            require(target.recorded_observations.contains(id)&&!original.recorded_observations.contains(id),
                    "later fact requires an exact recorded observation ID");
        else
            require(a->second==b->second,"later observation ID now has a different definition");
        result.push_back({id,a->second,new_id,!target.inactive.contains(id)});
    }
    return result;
}
Table replay_proofs(Program& target,set<string> inactive,const vector<ReplayObservation>& edits,JoinWork* work=nullptr){
    for(const auto& row:edits){
        const auto old=target.observations.find(row.id);
        if(row.added){
            require(old==target.observations.end()&&target.signatures.contains(base_name(row.fact))&&
                    target.arity.contains(base_name(row.fact))&&target.arity.at(base_name(row.fact))==row.fact.args.size(),
                    "later observation is not comparable in every retained program");
            map<string,Kind> typed;check_type(target,row.fact,typed);
            target.observations.emplace(row.id,row.fact);
        } else require(old!=target.observations.end()&&old->second==row.fact,
                       "later withdrawal or restoration is not comparable in every retained program");
        if(row.active)inactive.erase(row.id);else inactive.insert(row.id);
    }
    auto result=run(target,inactive,nullptr,work);
    if(work)require(work->probes<=1000000&&work->indexed<=1000000&&work->rounds<=2048,
                    "choice attribution aggregate inference budget");
    return result;
}
vector<Option> score_observation_overlay(const Continuity& prior,Program original,const vector<Option>& recorded,
                                         const vector<ReplayObservation>& overlay,JoinWork* work=nullptr){
    const auto updated=replay_proofs(original,prior.inactive,overlay,work);
    vector<Option> options;
    for(const auto& source:recorded){
        auto& alternative=options.emplace_back(source.name);
        alternative.revision=source.revision;
        alternative.remembered=source.remembered;
        if(source.name=="stay")score(alternative,original,updated,updated);
        else if(source.program&&source.state){
            auto program=*source.program;
            const auto check=replay_proofs(program,source.state->inactive,overlay,work);
            score(alternative,original,updated,check);
        }else alternative.error=source.error.empty()?"historical candidate unavailable":source.error;
    }
    return options;
}

string reassess_choice(StateStore& reader,const Continuity& live,const string& id,const string& head){
    const auto old=live.choice_outcomes.find(id);
    const auto pin=live.pins.find("basis_"+id);
    string out="{\"schema\":\"pcgm-observation-reassessment-v1\",\"id\":"+quote_json(id)+
        ",\"individual\":"+quote_json(live.id)+",\"head_sha256\":"+quote_json(head)+
        ",\"committable\":false";
    if(old==live.choice_outcomes.end())return out+",\"status\":\"not_recorded\"}";
    if(!live.choice_bases.contains(id))return out+",\"status\":\"basis_not_recorded\"}";
    require(pin!=live.pins.end()&&pin->second.digest==old->second.basis,"reassessment basis does not match recorded choice");
    const auto prior=verify_episode(reader,live,pin->second);
    auto original=compile_active(prior);
    const auto recorded=run_frozen_choice(prior,original,run(original,prior.inactive),reader);
    const auto exact=render_decision(prior,recorded.options,recorded.selected,old->second.kind=="committed","live_job:"+id);
    require(exact==old->second.receipt,"historical reassessment differs from its recorded choice");
    const auto head_program=compile_active(live);
    const auto overlay=later_observation_overlay(prior,original,live,head_program);
    const auto options=score_observation_overlay(prior,std::move(original),recorded.options,overlay);
    const auto selected=best_choice(options);
    out+=",\"status\":\"verified\",\"basis_sha256\":"+quote_json(old->second.basis)+
         ",\"original_receipt_sha256\":"+quote_json(sha256(exact))+",\"original\":"+exact+
         ",\"reassessed\":"+render_decision(prior,options,selected,false,"observation_overlay:"+id)+",\"observation_changes\":[";
    bool first=true;
    for(const auto& row:overlay){
        if(!first)out+=',';
        first=false;
        out+="{\"id\":"+quote_json(row.id)+",\"fact\":"+quote_json(show(row.fact))+
             ",\"added\":"+(row.added?"true":"false")+",\"active\":"+(row.active?"true":"false")+"}";
    }
    return out+"]}";
}

// Explanation over exact *net* observation changes. This is not chronology and
// does not claim any particular observation, combination or recommendation is true.
string explain_choice_attribution(StateStore& reader,const Continuity& live,const string& id,const string& head){
    string out="{\"schema\":\"pcgm-choice-attribution-v1\",\"id\":"+quote_json(id)+
        ",\"individual\":"+quote_json(live.id)+",\"head_sha256\":"+quote_json(head)+",\"committable\":false";
    const auto history=live.choice_outcomes.find(id);
    if(history==live.choice_outcomes.end())return out+",\"status\":\"not_recorded\"}";
    if(!live.choice_bases.contains(id))return out+",\"status\":\"basis_not_recorded\"}";
    const auto pin=live.pins.find("basis_"+id);
    require(pin!=live.pins.end()&&pin->second.digest==history->second.basis,"choice attribution basis does not match recorded choice");
    const auto prior=verify_episode(reader,live,pin->second);
    const auto original=compile_active(prior);
    const auto overlay=later_observation_overlay(prior,original,live,compile_active(live));
    require(overlay.size()<=4,"choice attribution supports at most four net observation changes");
    const auto frozen=run_frozen_choice(prior,original,run(original,prior.inactive),reader);
    require(frozen.options.size()<=8,"choice attribution supports at most eight retained alternatives");
    const auto exact=render_decision(prior,frozen.options,frozen.selected,history->second.kind=="committed","live_job:"+id);
    require(exact==history->second.receipt,"historical choice attribution differs from its recorded choice");
    JoinWork work;
    const unsigned count=1U<<overlay.size(),full=count-1;
    struct Result {optional<size_t> selected;string status;};
    vector<Result> replay;
    replay.reserve(count);
    for(unsigned mask=0;mask<count;++mask){
        vector<ReplayObservation> subset;
        for(size_t i=0;i<overlay.size();++i)if(mask&(1U<<i))subset.push_back(overlay[i]);
        const auto opts=score_observation_overlay(prior,original,frozen.options,subset,&work);
        const auto picked=best_choice(opts);
        replay.push_back({picked,decision_status(opts,picked,false)});
    }
    const auto& base=replay.front();
    const auto& final=replay.back();
    require(base.selected==frozen.selected&&base.status==decision_status(frozen.options,frozen.selected,false),
            "empty observation subset differs from reconstructed historical choice");
    const bool changed=base.selected!=final.selected||base.status!=final.status;
    auto subset_json=[&](unsigned mask){
        string encoded="[";
        bool first=true;
        for(size_t i=0;i<overlay.size();++i)if(mask&(1U<<i)){
            if(!first)encoded+=',';
            first=false;
            encoded+=quote_json(overlay[i].id);
        }
        return encoded+"]";
    };
    auto choice_json=[&](const Result& result){
        return "{\"status\":"+quote_json(result.status)+",\"selected\":"+
            (result.selected?to_string(*result.selected):string("null"))+",\"kind\":"+
            (result.selected?quote_json(frozen.options[*result.selected].name):string("null"))+"}";
    };
    out+=",\"status\":\"verified\",\"basis_sha256\":"+quote_json(history->second.basis)+
        ",\"original_receipt_sha256\":"+quote_json(sha256(exact))+
        ",\"scope\":\"net_observations_only\",\"baseline\":"+choice_json(base)+
        ",\"full\":"+choice_json(final)+",\"changed\":"+(changed?"true":"false")+
        ",\"change_ids\":"+subset_json(full)+",\"minimal_sufficient_sets\":[";
    bool first=true;
    if(changed&&final.selected)for(unsigned mask=1;mask<=full;++mask){
        if(replay[mask].selected!=final.selected)continue;
        bool minimal=true;
        for(unsigned sm=(mask-1)&mask;;sm=(sm-1)&mask){
            if(replay[sm].selected==final.selected){minimal=false;break;}
            if(!sm)break;
        }
        if(!minimal)continue;
        if(!first)out+=',';
        first=false;
        out+=subset_json(mask);
    }
    out+="],\"replays\":[";
    for(unsigned i=0;i<count;++i){
        if(i)out+=',';
        out+="{\"include\":"+subset_json(i)+",\"choice\":"+choice_json(replay[i])+"}";
    }
    return out+"]}";
}
