constexpr size_t decision_trace_limit=12000;
string stored_decision(const Continuity& state,const string& id){
    const auto result=state.decision_traces.find(id);
    require(result!=state.decision_traces.end(),"no structured decision receipt for this event");
    return result->second;
}
string decision_status(const vector<Option>& options,optional<size_t> selected,bool commit){
    if(selected)return options.at(*selected).name=="stay"?"stay":commit?"committed":"recommended";
    return std::ranges::count_if(options,[](const auto& o){return o.error.empty();})>1?"tied":"blocked";
}
string render_decision(const Continuity& prior,const vector<Option>& options,optional<size_t> selected,
                       bool commit,string origin,size_t example_limit=16){
    const auto status=decision_status(options,selected,commit);
    ostringstream out;
    out<<"{\"schema\":\"pcgm-decision-v1\",\"individual\":"<<quote_json(prior.id)
       <<",\"observation_version\":"<<prior.observation_version<<",\"epoch\":"<<prior.epoch
       <<",\"basis_revision_sha256\":"<<quote_json(revision_snapshot(prior))<<",\"trigger\":"<<quote_json(origin)
       <<",\"status\":"<<quote_json(status)<<",\"selected\":";
    if(selected)out<<*selected;
    else out<<"null";
    out<<",\"options\":[";
    for(size_t i=0;i<options.size();++i){
        const auto& o=options[i];
        if(i)out<<',';
        out<<"{\"kind\":"<<quote_json(o.name)<<",\"target\":"
           <<(o.revision.empty()?string("null"):quote_json(o.revision))<<",\"eligible\":"<<(o.error.empty()?"true":"false")
           <<",\"blocked_reason\":"<<(o.error.empty()?string("null"):quote_json(o.error.substr(0,240)))
           <<",\"wishes\":"<<o.wishes<<",\"risk\":"<<o.risk<<",\"semantic_changes\":"<<o.changes
           <<",\"remembered_outcomes\":"<<o.remembered
           <<",\"criteria_count\":"<<o.criteria.size()<<",\"criteria_truncated\":"
           <<(o.criteria.size()>example_limit?"true":"false")<<",\"criteria\":[";
        const auto max=min(o.criteria.size(),example_limit);
        for(size_t c=0;c<max;++c){
            if(c)out<<',';
            const auto& row=o.criteria[c];
            out<<"{\"goal\":";json_atom(out,row.target);
            out<<",\"condition\":";
            if(row.condition)json_atom(out,*row.condition);else out<<"null";
            out<<",\"hard\":"<<(row.hard?"true":"false")<<",\"active\":"<<(row.active?"true":"false")
               <<",\"expected\":"<<quote_json(row.wanted)<<",\"before\":"<<quote_json(row.before)
               <<",\"after\":"<<quote_json(row.after)<<'}';
        }
        out<<"]}";
    }
    out<<"]}";
    auto text=out.str();
    if(text.size()>decision_trace_limit&&example_limit)
        return render_decision(prior,options,selected,commit,std::move(origin),example_limit/2);
    require(text.size()<=decision_trace_limit,"decision receipt summary too large");
    return text;
}
void retain_decision(Continuity& state,const string& id,const string& payload){
    require(!state.decision_traces.contains(id)&&payload.size()<=decision_trace_limit,"duplicate or oversized decision receipt");
    state.decision_traces.emplace(id,payload);
    state.events.push_back("decision_trace "+id+" "+to_hex(payload));
}
