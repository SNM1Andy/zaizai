string historical_payload(StateStore& reader,const Continuity& head,const string& label,const Atom& query,bool detail){
    const auto pin=head.pins.find(label);
    require(pin!=head.pins.end(),"unknown evidence pin");
    const auto saved=verify_episode(reader,head,pin->second);
    const auto program=compile_active(saved);
    bool supported=true;
    try{validate_time_query(program,query);}catch(const runtime_error&){supported=false;}
    require(!query.pred.starts_with('!')&&std::ranges::none_of(query.args,variable),"historical queries are unsigned and ground");
    string verdict="UNAVAILABLE",fingerprint="null",proof="null";
    if(supported){
        const auto result=run(program,saved.inactive);
        verdict=truth_state(result,query);
        fingerprint=quote_json(proof_digest(result,query));
        if(detail)proof=json_report(result,{query},"pcgm",channel_context(saved));
    }
    return "{\"label\":"+quote_json(label)+",\"cursor\":"+to_string(pin->second.events+1)+
        ",\"state\":"+channel_context(saved)+",\"snapshot_sha256\":"+quote_json(pin->second.digest)+
        ",\"status\":"+quote_json(verdict)+",\"proof_identity_version\":2,\"proof_sha256\":"+fingerprint+
        (detail?",\"proof\":"+proof:"")+"}";
}
string historical_timeline(StateStore& reader,const Continuity& head,unsigned from,unsigned limit,const Atom& query){
    require(!query.pred.starts_with('!')&&std::ranges::none_of(query.args,variable),"historical queries are unsigned and ground");
    require(from<=head.events.size()&&limit>0&&limit<=12,"invalid historical cursor or page size");
    vector<pair<unsigned,string>> pinned;
    for(const auto& [label,pin]:head.pins)
        if(pin.events+1>from)pinned.emplace_back(pin.events+1,label);
    sort(pinned.begin(),pinned.end());
    unsigned cursor=from;
    ostringstream out;
    out<<"{\"schema\":\"pcgm-timeline-v1\",\"head\":"<<channel_context(head)<<",\"from\":"<<from<<",\"results\":[";
    for(size_t i=0;i<pinned.size()&&i<limit;++i){
        if(i)out<<',';
        cursor=pinned[i].first;
        out<<historical_payload(reader,head,pinned[i].second,query,false);
    }
    out<<"],\"cursor\":"<<cursor<<",\"more\":"<<(pinned.size()>limit?"true":"false")<<'}';
    return out.str();
}
