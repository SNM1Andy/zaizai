string question_condition_context(const Program& p,const Table& table,const Atom& objective){
    if(!p.criteria_questions||p.goals.contains(objective))return {};
    set<pair<Atom,string>> support;
    bool unconditional=false;
    for(const auto& rule:p.preferences)if(rule.proposition==objective&&rule.expected=="POSITIVE"){
        if(!rule.when)unconditional=true;
        else if(proof_without_conflict(table,*rule.when)){
            auto query=*rule.when;
            query.pred=base_name(query);
            support.emplace(*rule.when,proof_digest(table,query));
        }
    }
    if(support.empty())return {};
    string basis="PCGM-QUESTION-CONDITION-1\n"+show(objective)+"\n"+(unconditional?"unconditional\n":"guarded\n");
    for(const auto& [guard,proof]:support)basis+=show(guard)+" "+proof+"\n";
    return sha256(basis);
}
string question_pin(const Continuity& state,const string& ticket,const LocalQuestion& q,const string& status,
                    const Program* program=nullptr,const Table* table=nullptr){
    const auto guard=program&&table&&status=="open"?question_condition_context(*program,*table,q.goal):string{};
    const string exact=state.id+"\n"+ticket+"\n"+show(q.goal)+"\n"+show(q.fact)+"\n"+status+"\n";
    if(q.agenda&&status=="open"){
        require(program&&table,"agenda question address requires its live dependency proof");
        const auto context=agenda_ticket_context(state,*program,*table,q);
        require(!context.empty(),"agenda question no longer has a distinguishing dependency");
        return sha256("PCGM-AGENDA-QUESTION-1\n"+exact+context+"\n");
    }
    if(guard.empty())return sha256("PCGM-QUESTION-1\n"+exact);
    return sha256("PCGM-QUESTION-2\n"+exact+guard+"\n");
}
struct AnswerPacket {string individual,ticket,source,pin;Atom evidence;};
AnswerPacket decode_answer_packet(const string& bytes){
    istringstream in(bytes);
    string marker,id,ticket,source,pin,line,extra;
    require(bool(getline(in,line)),"question answer header missing");
    istringstream header(line);
    require(bool(header>>marker>>id>>ticket>>source>>pin)&&marker=="PCGM_ANSWER_1"&&!(header>>extra),"invalid question answer header");
    Parser names{ticket+" "+source};
    require(names.name()==ticket&&names.name()==source,"invalid answer identifiers");names.end();
    require(valid_identity(id)&&source.size()<=24&&pin.size()==64&&hex_chars(pin),"invalid question answer identity or pin");
    require(bool(getline(in,line))&&!(getline(in,extra)),"answer packet requires exactly one CL atom");
    Parser p{line};const auto fact=p.atom();p.end();
    require(std::ranges::none_of(fact.args,variable),"answer evidence must be ground");
    require(bytes=="PCGM_ANSWER_1 "+id+" "+ticket+" "+source+" "+pin+"\n"+show(fact)+"\n",
            "answer packet is not canonical");
    return {id,ticket,source,pin,fact};
}
string question_json(const Continuity& state,const string& ticket,const LocalQuestion& q,const Table& table,const set<Why>& gaps,const Program* program=nullptr){
    const auto status=question_status(q,table,gaps,state,program);
    ostringstream out;
    out<<"{\"id\":"<<quote_json(ticket)<<",\"status\":"<<quote_json(status)<<",\"request_sha256\":"
       <<quote_json(question_pin(state,ticket,q,status,program,&table))<<",\"goal\":";
    json_atom(out,q.goal);
    out<<",\"needed\":";json_atom(out,q.fact);
    if(program&&status=="open"){
        const auto context=question_condition_context(*program,table,q.goal);
        if(!context.empty())out<<",\"condition_context_sha256\":"<<quote_json(context);
    }
    if(program&&program->criteria_questions&&!program->goals.contains(q.goal)){
        const auto [guard,objective]=criteria_question_origin(*program,q.goal);
        if(guard||objective)out<<",\"origin\":"<<quote_json(guard&&objective?"decision_guard_and_goal":guard?"decision_guard":"decision_goal");
    }
    out<<",\"evidence\":[";
    bool first=true;
    for(const auto& [id,who]:state.receipt_question)if(who==ticket){
        if(!first)out<<',';
        first=false;
        out<<"{\"observation\":"<<quote_json(id)<<",\"active\":"<<(state.inactive.contains(id)?"false":"true");
        const auto item=state.wire_receipts.find(id);
        if(item!=state.wire_receipts.end()){
            out<<",\"source_label\":"<<quote_json(item->second.source)
               <<",\"packet_sha256\":"<<quote_json(item->second.packet);
        }
        const auto bundle=state.bundle_receipts.find(id);
        if(bundle!=state.bundle_receipts.end()){
            const auto workspace=state.workspace_answer_locks.find(id);
            if(workspace!=state.workspace_answer_locks.end())
                out<<",\"cl_workspace_archive_sha256\":"<<quote_json(bundle->second.package)
                   <<",\"cl_workspace_lock_sha256\":"<<quote_json(workspace->second);
            else out<<",\"cl_package_sha256\":"<<quote_json(bundle->second.package);
            out<<",\"cl_proof_sha256\":"<<quote_json(bundle->second.proof)
               <<",\"request_sha256\":"<<quote_json(bundle->second.request);
            const auto assessment=state.bundle_assessments.find(id);
            if(assessment!=state.bundle_assessments.end())out<<",\"assessment\":"<<assessment->second;
        }
        if(const auto frozen=state.frozen_receipts.find(id);frozen!=state.frozen_receipts.end())
            out<<",\"cl_frozen_artifact_sha256\":"<<quote_json(frozen->second.first)
               <<",\"cl_frozen_snapshot_sha256\":"<<quote_json(frozen->second.second);
        out<<'}';
    }
    out<<"]}";
    return out.str();
}
string review_question_bundle(const fs::path& state_path,const string& ticket,const string& request_sha,
                              const fs::path& package,const string& package_sha,const cl_native::EvaluationCeilings& cap){
    const auto path=fs::absolute(state_path);
    StateStore reader(fs::canonical(path.parent_path())/path.filename(),false);
    string revision;
    const auto saved=reader.load(&revision);
    const auto item=saved.questions.find(ticket);
    require(item!=saved.questions.end(),"unknown question");
    const auto active=compile_active(saved);
    const auto answer=run(active,saved.inactive);
    const auto status=question_status(item->second,answer,open_gaps(active,answer),saved,&active);
    require(status=="open"&&question_pin(saved,ticket,item->second,status,&active,&answer)==request_sha,
            "question is no longer open at supplied request pin");
    const auto image=native_os::read_regular_input(package,2*1024*1024,{
        "cannot open CL package directory","cannot open supplied CL package","supplied CL package is not a regular file",
        "cannot read supplied CL package","supplied CL package size limit"});
    const auto checked=cl_native::offline_proof_bounded_bytes(image,package_sha,show(item->second.fact)+"\n",
                                                             cap);
    require(checked.size()<=512*1024,"CL evidence review exceeds proof receipt size limit");
    // Frozen local revision and recomputed foreign world are distinct in this receipt.
    return "{\"schema\":\"pcgm-question-bundle-review-v1\",\"question\":"+quote_json(ticket)+
        ",\"request_sha256\":"+quote_json(request_sha)+",\"individual\":"+quote_json(saved.id)+
        ",\"revision_sha256\":"+quote_json(revision)+",\"proof_sha256\":"+quote_json(sha256(checked))+",\"observation_written\":false,\"cl_proof\":"+checked.substr(0,checked.size()-1)+"}";
}

string review_frozen_question(const fs::path& state,const string& ticket,const string& request,const fs::path& artifact,
                              const string& artifact_pin,const string& package,const string& snapshot,bool integrity=false){
    const auto path=fs::absolute(state);
    StateStore reader(fs::canonical(path.parent_path())/path.filename(),false);
    const auto current=reader.load();
    const auto q=current.questions.find(ticket);
    require(q!=current.questions.end(),"unknown question");
    const auto program=compile_active(current);
    const auto table=run(program,current.inactive);
    const auto status=question_status(q->second,table,open_gaps(program,table),current,&program);
    require(status=="open"&&question_pin(current,ticket,q->second,status,&program,&table)==request,"frozen proof question has a stale request address");
    const auto raw=native_os::read_regular_input(artifact,5*1024*1024,{"cannot open frozen proof directory","cannot open frozen proof",
        "frozen proof must be a regular file","cannot read frozen proof","frozen proof exceeds size limit"});
    if(integrity){
        const auto rechecked=cl_native::offline_frozen_integrity_single_goal(raw,artifact_pin,package,snapshot,show(q->second.fact)+"\n");
        auto report=rechecked.integrity_receipt;
        require(!report.empty()&&report.back()=='\n',"missing exact integrity report");
        report.pop_back();
        return "{\"schema\":\"pcgm-frozen-question-integrity-v1\",\"individual\":"+quote_json(current.id)+
               ",\"request_sha256\":"+quote_json(request)+",\"ticket\":"+quote_json(ticket)+
               ",\"observation_written\":false,\"clean_signed_advisory\":"+(rechecked.clean_single?"true":"false")+
               ",\"cl_proof\":"+rechecked.signed_receipt+",\"cl_integrity\":"+report+"}";
    }
    const auto rechecked=cl_native::offline_frozen_single_goal(raw,artifact_pin,package,snapshot,show(q->second.fact)+"\n");
    return "{\"schema\":\"pcgm-frozen-question-review-v1\",\"ticket\":"+quote_json(ticket)+
        ",\"individual\":"+quote_json(current.id)+",\"request_sha256\":"+quote_json(request)+
        ",\"artifact_sha256\":"+quote_json(artifact_pin)+",\"package_sha256\":"+quote_json(package)+
        ",\"source_snapshot_sha256\":"+quote_json(snapshot)+",\"proof_sha256\":"+quote_json(sha256(rechecked.receipt))+
        ",\"observation_written\":false,\"cl_proof\":"+rechecked.receipt+"}";
}


string review_workspace_question(const fs::path& state,const string& ticket,const string& request,
                                 const fs::path& artifact,const string& archive_pin,const string& lock){
    const auto path=fs::absolute(state);
    StateStore reader(fs::canonical(path.parent_path())/path.filename(),false);
    const auto current=reader.load();
    const auto q=current.questions.find(ticket);
    require(q!=current.questions.end(),"unknown question");
    const auto program=compile_active(current);
    const auto table=run(program,current.inactive);
    const auto status=question_status(q->second,table,open_gaps(program,table),current,&program);
    require(status=="open"&&question_pin(current,ticket,q->second,status,&program,&table)==request,
            "workspace proof question has a stale request address");
    const auto raw=native_os::read_regular_input(artifact,16*1024*1024,{"cannot open workspace proof directory",
        "cannot open workspace proof archive","workspace proof archive must be regular","cannot read workspace proof archive",
        "workspace proof archive exceeds size limit"});
    const auto checked=cl_native::workspace_single_goal_bounded(raw,archive_pin,lock,show(q->second.fact)+"\n",{128,12000,2000000,2000000});
    require(checked.receipt.size()<=512*1024,"workspace question proof exceeds receipt size limit");
    return "{\"schema\":\"pcgm-workspace-question-review-v1\",\"ticket\":"+quote_json(ticket)+
        ",\"individual\":"+quote_json(current.id)+",\"request_sha256\":"+quote_json(request)+
        ",\"archive_sha256\":"+quote_json(archive_pin)+",\"lock_sha256\":"+quote_json(lock)+
        ",\"proof_sha256\":"+quote_json(sha256(checked.receipt))+
        ",\"observation_written\":false,\"cl_proof\":"+checked.receipt+"}";
}
