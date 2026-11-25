string observation_batch_receipt(const Continuity& state,const string& id,const string& digest,bool retry){
    require(digest.size()==64&&hex_chars(digest),"expected exact observation batch request SHA-256");
    const auto found=state.observation_batches.find(id);
    string out="{\"schema\":\"pcgm-observation-batch-v1\",\"id\":"+quote_json(id)+
        ",\"individual\":"+quote_json(state.id)+",\"request_sha256\":"+quote_json(digest);
    if(found==state.observation_batches.end())return out+",\"status\":\"not_recorded\"}";
    const auto& receipt=found->second;
    require(digest==receipt.digest,"observation batch ID already committed with different request bytes");
    return out+",\"status\":"+quote_json(retry?"already_applied":"committed")+
        ",\"basis_sha256\":"+quote_json(receipt.basis)+",\"event\":"+to_string(receipt.event)+
        ",\"observation_version\":"+to_string(receipt.version)+",\"edits\":"+to_string(receipt.count)+"}";
}

struct StagedObservationBatch {Continuity state;Program program;Table proofs;};
StagedObservationBatch stage_observation_batch(const Continuity& state,const Program& current,const ObservationBatch& parsed,
                                               const string& line){
    require(sha256(encode(state))==parsed.basis,"observation batch base SHA-256 does not match current head");
    require(state.observation_batches.size()<128&&state.observation_version<=10000-parsed.edits.size(),
            "observation batch retention or version limit");
    auto next=state;
    if(parsed.audited)
        require(next.observation_batch_audit_bases.size()<16&&
                next.observation_batch_audit_bases.emplace(parsed.id,Pin{parsed.basis,static_cast<unsigned>(next.events.size())}).second,
                "observation audit retention limit or duplicate basis");
    next.events.push_back("observation_batch "+to_hex(line));
    for(const auto& item:parsed.edits){
        if(item.fact){
            require(!current.observations.contains(item.id)&&!next.recorded_observations.contains(item.id),
                    "observation batch cannot replace or reuse an observation ID");
            require(current.signatures.contains(base_name(*item.fact))||current.arity.contains(base_name(*item.fact)),
                    "observation batch predicate not declared");
            next.source+="\n& "+item.id+" "+show(*item.fact)+".\n";
            next.recorded_observations.insert(item.id);
            next.observation_batch_facts.emplace(item.id,*item.fact);
        }else{
            require(current.observations.contains(item.id)&&!current.observation_labels.contains(item.id)&&
                    !state.receipt_question.contains(item.id),"observation batch cannot edit unknown, imported or question evidence");
            const bool changed=item.operation=="withdraw"?next.inactive.insert(item.id).second:next.inactive.erase(item.id)!=0;
            require(changed,"observation batch edit would make no change");
        }
        next.events.push_back(item.operation+" "+item.id);
        ++next.observation_version;
    }
    const auto edits=static_cast<unsigned>(parsed.edits.size());
    const auto event=static_cast<unsigned>(next.events.size());
    next.observation_batches.emplace(parsed.id,ObservationBatchReceipt{
        parsed.basis,sha256(line),event,next.observation_version,edits});
    auto program=compile_active(next);
    auto table=run(program,next.inactive);
    return {std::move(next),std::move(program),std::move(table)};
}

string audit_observation_batch(const StateStore& reader,const Continuity& live,const string& item,
                               const string& exact,const vector<Atom>& goals){
    require(exact.size()==64&&hex_chars(exact),"observation audit needs the exact request SHA-256");
    string out="{\"schema\":\"pcgm-observation-batch-audit-v1\",\"id\":"+quote_json(item)+
        ",\"individual\":"+quote_json(live.id)+",\"read_only\":true,\"request_sha256\":"+quote_json(exact);
    const auto receipt=live.observation_batches.find(item);
    if(receipt==live.observation_batches.end())return out+",\"status\":\"not_recorded\"}";
    require(receipt->second.digest==exact,"observation audit request SHA-256 does not match receipt");
    const auto basis=live.observation_batch_audit_bases.find(item);
    if(basis==live.observation_batch_audit_bases.end())return out+",\"status\":\"basis_not_retained\"}";
    const auto& pin=basis->second;
    require(pin.digest==receipt->second.basis&&pin.events<live.events.size()&&
            receipt->second.event==pin.events+1+receipt->second.count,
            "observation batch pending history does not match receipt");
    constexpr string_view marker="observation_batch ";
    const auto& event=live.events.at(pin.events);
    require(event.starts_with(marker),"missing historical observation batch marker");
    const auto payload=from_hex(event.substr(marker.size()));
    const auto cmd=parse_observation_batch(payload);
    require(sha256(payload)==exact&&cmd.audited&&cmd.basis==pin.digest&&cmd.id==item,
            "historical observation batch differs from its receipt");
    const auto before=verify_episode(reader,live,pin);
    require(before.observation_version+cmd.edits.size()==receipt->second.version,
            "historical observation batch version differs from receipt");
    const auto predecessor=compile_active(before);
    for(const auto& g:goals)validate_time_query(predecessor,g);
    const auto prior_proofs=run(predecessor,before.inactive);
    auto after=stage_observation_batch(before,predecessor,cmd,payload);
    add_notices(after.state,prior_proofs,after.proofs);
    require(after.state.events.size()<=live.events.size()&&
            std::equal(after.state.events.begin()+pin.events,after.state.events.end(),live.events.begin()+pin.events),
            "reconstructed observation batch or notices differ from recorded history");
    if(after.state.events.size()<live.events.size())
        require(!live.events.at(after.state.events.size()).starts_with("notice2 "),
                "unexpected notice after observation batch history");
    out+=",\"status\":\"verified\",\"basis_sha256\":"+quote_json(pin.digest)+
        ",\"reconstructed_after_sha256\":"+quote_json(sha256(encode(after.state)))+
        ",\"first_event\":"+to_string(pin.events+1)+",\"last_event\":"+to_string(after.state.events.size())+
        ",\"observation_version\":"+to_string(after.state.observation_version)+
        ",\"results\":[";
    for(size_t i=0;i<goals.size();++i){
        if(i)out+=',';
        const auto& g=goals[i];
        validate_time_query(after.program,g);
        ostringstream details;
        details<<"{\"before_sha256\":"<<quote_json(proof_digest(prior_proofs,g))<<
            ",\"after_sha256\":"<<quote_json(proof_digest(after.proofs,g))<<",\"before\":";
        json_fact(details,prior_proofs,g);
        details<<",\"after\":";json_fact(details,after.proofs,g);details<<'}';
        out+=details.str();
    }
    out+="]}";
    require(out.size()<=1024*1024,"observation batch audit proof output limit");
    return out;
}
