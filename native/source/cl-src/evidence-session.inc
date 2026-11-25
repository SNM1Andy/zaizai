constexpr size_t evidence_journal_limit=512*1024;
struct EvidenceRow {Atom atom;bool active=true;};
struct EvidenceCommit {string requested,basis;size_t revision=0,edits=0;};
struct EvidenceState {
    string package,goals;
    size_t revision=0;
    map<string,EvidenceRow> rows;
    map<string,EvidenceCommit> receipts;
    unsigned format=1;
};
string evidence_snapshot(const EvidenceState& value){
    IRWriter w;
    package_cell(w,value.package,64);
    package_cell(w,value.goals,64);
    w.number(value.revision);
    w.number(value.rows.size());
    for(const auto& [id,row]:value.rows){
        package_cell(w,id,48);
        w.number(row.active?1:0);
        package_cell(w,show(row.atom),2048);
    }
    if(value.format==2){
        w.number(value.receipts.size());
        for(const auto& [id,receipt]:value.receipts){
            package_cell(w,id,48);
            package_cell(w,receipt.requested,64);package_cell(w,receipt.basis,64);
            w.number(receipt.revision);w.number(receipt.edits);
        }
    }
    const auto raw="CLES-"+to_string(value.format)+"\n"+sha256(w.bytes)+"\n"+w.bytes;
    require(raw.size()<=evidence_journal_limit,"CL evidence journal size limit");
    return raw;
}
void validate_evidence_input(const Program& base,const Atom& a){
    require(!comparison(base_name(a))&&std::ranges::none_of(a.args,variable)&&
            base.signatures.contains(base_name(a)),"CL evidence requires a declared typed ground relation");
    map<string,Kind> variables;
    check_type(base,a,variables);
}
EvidenceState read_evidence_snapshot(const string& raw,const Program& base,const string& package,const string& goals){
    const string_view version=raw.starts_with("CLES-2\n")?"CLES-2\n":"CLES-1\n";
    require(raw.size()>=version.size()+65&&raw.starts_with(version)&&raw[version.size()+64]=='\n',
            "not a CL evidence journal");
    const auto bytes=raw.substr(version.size()+65);
    require(sha256(bytes)==raw.substr(version.size(),64),"CL evidence journal digest mismatch");
    IRReader reader{bytes};
    EvidenceState result;result.format=version=="CLES-2\n"?2:1;
    result.package=package_get(reader,64);result.goals=package_get(reader,64);
    require(result.package==package&&result.goals==goals,"CL evidence journal package or goal identity differs");
    result.revision=reader.number(0xffffffffU);
    const auto count=reader.number(512);
    for(size_t i=0;i<count;++i){
        const auto id=package_get(reader,48);Parser name{id};name.name();name.end();
        const auto active=reader.number(1);
        const auto source=package_get(reader,2048);Parser parsed{source};auto fact=parsed.atom();parsed.end();
        validate_evidence_input(base,fact);
        require(result.rows.emplace(id,EvidenceRow{std::move(fact),active!=0}).second,"duplicate CL evidence identifier");
    }
    if(result.format==2){
        const auto transactions=reader.number(128);
        set<size_t> revisions;
        for(size_t i=0;i<transactions;++i){
            auto id=package_get(reader,48);Parser n{id};n.name();n.end();
            auto request=package_get(reader,64),basis=package_get(reader,64);
            const auto revision=reader.number(result.revision),edits=reader.number(16);
            require(workspace_digest(request)&&workspace_digest(basis)&&revision>0&&edits>0&&revisions.insert(revision).second&&
                    result.receipts.emplace(std::move(id),EvidenceCommit{std::move(request),std::move(basis),revision,edits}).second,
                    "invalid durable CL evidence transaction receipt");
        }
    }
    require(reader.offset==bytes.size()&&evidence_snapshot(result)==raw,"noncanonical CL evidence journal");
    return result;
}
#ifndef CL_PORTABLE_MEMORY_CORE
struct EvidenceJournal {
    fs::path path;
    native_os::Descriptor dir,lease;
    string known;
    explicit EvidenceJournal(const fs::path& chosen)
        :path(fs::canonical(fs::absolute(chosen).parent_path())/chosen.filename()),
         dir(native_os::open_directory(path.parent_path())),
         lease(native_os::open_lock(dir.fd,path.filename().string()+".lock")){
        native_os::acquire_lock(lease.fd,"cannot open CL evidence lock","CL evidence lock is not a regular file",
                               "CL evidence journal already has a writer");
    }
    void verify()const{
        native_os::confirm_directory(dir.fd,path.parent_path(),"CL evidence journal directory moved");
    }
    string bytes(){
        verify();
        return native_os::read_confined_component(dir.fd,path.filename().string(),evidence_journal_limit,{
            "cannot open CL evidence directory","cannot open CL evidence journal","CL evidence journal is not a regular file",
            "cannot read CL evidence journal","CL evidence journal read limit"});
    }
    void save(const EvidenceState& state,bool init=false){
        if(!init)require(sha256(bytes())==known,"CL evidence journal changed outside this writer");
        verify();
        const auto raw=evidence_snapshot(state);
        native_os::atomic_local_commit(path.filename().string(),dir.fd,raw,".cl-evidence-pending-",init,{
            "cannot create pending CL evidence journal","write CL evidence journal failed","sync CL evidence journal failed",
            "CL evidence journal path already exists","cannot replace CL evidence journal",
            "CL evidence commit outcome uncertain; reopen and reconcile"});
        known=sha256(raw);
    }
};

#endif
struct EvidencePlanes {
    const Program& base;
    const vector<Atom>& requested;
    vector<ComputePlane> shape;
    vector<set<string>> dependency;
    vector<vector<string>> cache;
    vector<size_t> rebuilt;
    EvidencePlanes(const Program& program,const vector<Atom>& goals)
        :base(program),requested(goals),shape(plan_planes(program,goals)),dependency(shape.size()),
         cache(shape.size()),rebuilt(shape.size()){
        for(size_t i=0;i<shape.size();++i)
            for(const auto at:shape[i].goals){
                const auto names=dependency_relations(base,requested.at(at));
                dependency[i].insert(names.begin(),names.end());
            }
    }
    vector<string> evaluate(const EvidenceState& state,size_t i)const{
        auto program=base;
        for(const auto& [id,row]:state.rows){
            if(!row.active||!dependency.at(i).contains(base_name(row.atom)))continue;
            require(program.observations.emplace("live_"+id,row.atom).second,
                    "CL evidence row collides with immutable package");
        }
        vector<Atom> selected;
        for(auto j:shape.at(i).goals)selected.push_back(requested.at(j));
        SliceStats stats;
        const auto slice=query_slice(program,selected,stats);
        const auto result=run(slice);
        vector<string> proofs;
        for(const auto& goal:selected){
            ostringstream json;json_fact(json,result,goal);proofs.push_back(json.str());
        }
        return proofs;
    }
    void validate_label(const string& id)const{
        require(id.size()<=39&&!base.observations.contains("live_"+id),"CL evidence label exceeds limits or collides with package");
    }
    void verify_rows(const EvidenceState& state)const{
        for(const auto& [id,_]:state.rows)validate_label(id);
    }
    void recompute(const EvidenceState& state,const set<string>& changed={}){
        for(size_t i=0;i<shape.size();++i)
            if(changed.empty()||std::ranges::any_of(changed,[&](const auto& rel){return dependency.at(i).contains(rel); })){
                cache[i]=evaluate(state,i);
                ++rebuilt[i];
            }
    }
    void verify_complete(const EvidenceState& state)const{
        auto fresh=base;
        for(const auto& [id,row]:state.rows)if(row.active)
            require(fresh.observations.emplace("live_"+id,row.atom).second,"live evidence collides with reference");
        const auto exact=run(fresh);
        for(size_t i=0;i<shape.size();++i){
            for(size_t j=0;j<shape[i].goals.size();++j){
                ostringstream json;
                json_fact(json,exact,requested.at(shape[i].goals[j]));
                require(json.str()==cache.at(i).at(j),"incremental CL proof differs from full fresh computation");
            }
        }
    }
    string result(const EvidenceState& state)const{
        ostringstream out;
        out<<"{\"revision\":"<<state.revision<<",\"package_sha256\":"<<quote_json(state.package)<<
            ",\"goals_sha256\":"<<quote_json(state.goals)<<",\"rows\":"<<state.rows.size()<<",\"planes\":[";
        for(size_t i=0;i<shape.size();++i){
            if(i)out<<',';
            out<<"{\"evaluations\":"<<rebuilt.at(i)<<",\"results\":[";
            for(size_t j=0;j<cache.at(i).size();++j){if(j)out<<',';out<<cache.at(i).at(j);}
            out<<"]}";
        }
        out<<"]}";
        const auto bytes=out.str();
        require(bytes.size()<=2*1024*1024,"CL evidence proof result exceeds byte limit");
        return bytes;
    }
};

string transaction_receipt(const EvidenceState& state,const string& key,bool replay=false){
    const auto found=state.receipts.find(key);
    if(found==state.receipts.end())return "{\"status\":\"not_recorded\",\"transaction\":"+quote_json(key)+"}";
    const auto& saved=found->second;
    return "{\"status\":"+quote_json(replay?"replayed":"committed")+",\"transaction\":"+quote_json(key)+
        ",\"request_sha256\":"+quote_json(saved.requested)+",\"basis_sha256\":"+quote_json(saved.basis)+
        ",\"revision\":"+to_string(saved.revision)+",\"edits\":"+to_string(saved.edits)+"}";
}
string apply_evidence_edit(const Program& program,const EvidencePlanes& planes,EvidenceState& next,Parser& args,
                           const string& operation,string* label_written=nullptr){
    require(operation=="observe"||operation=="withdraw"||operation=="restore","invalid CL evidence edit");
    const auto label=args.name();
    planes.validate_label(label);
    if(label_written)*label_written=label;
    if(operation=="observe"){
        auto atom=args.atom();
        validate_evidence_input(program,atom);
        if(next.rows.contains(label)){
            require(next.rows.at(label).atom==atom,"CL evidence identity already binds different bytes");return {};
        }
        require(next.rows.size()<512,"CL evidence row capacity reached");
        auto changed=base_name(atom);
        next.rows.emplace(label,EvidenceRow{std::move(atom),true});
        return changed;
    }
    const auto found=next.rows.find(label);
    require(found!=next.rows.end(),"unknown CL evidence identifier");
    const bool active=operation=="restore";
    if(active==found->second.active)return {};
    found->second.active=active;
    return base_name(found->second.atom);
}
Program evidence_session_program(const string& raw,const string& pin){
    require(workspace_digest(pin)&&sha256(raw)==pin,"CL evidence session package SHA-256 mismatch");
    return verify_package(decode_package(raw));
}
struct PreparedEvidenceBatch {
    optional<EvidenceState> next;
    set<string> changed;
    string key;
};
PreparedEvidenceBatch prepare_evidence_batch(const Program& program,const EvidencePlanes& planes,
                    const EvidenceState& state,const string& basis,Parser& args){
    const auto key=args.name();
    const auto request=sha256("CL-EVIDENCE-TXN-1\n"+state.package+"\n"+state.goals+"\n"+
                              key+"\n"+workspace_tail(args)+"\n");
    if(const auto saved=state.receipts.find(key);saved!=state.receipts.end()){
        require(saved->second.requested==request,"CL evidence transaction ID already binds different bytes");
        return {nullopt,{},key};
    }
    const auto known=args.term();
    require(known==to_string(state.revision),"CL evidence expected revision is stale");
    auto next=state;
    set<string> changed,labels;
    size_t how_many=0;
    while(args.take(";")){
        require(++how_many<=16,"CL evidence batch has too many edits");
        const auto action=args.name();
        string label;
        const auto change=apply_evidence_edit(program,planes,next,args,action,&label);
        require(labels.insert(label).second,"CL evidence batch repeats a row");
        if(!change.empty())changed.insert(change);
    }
    args.end();
    require(!changed.empty()&&state.revision<0xffffffffU&&state.receipts.size()<128,
            "CL evidence batch has no change or capacity is exhausted");
    next.format=2;
    ++next.revision;
    next.receipts.emplace(key,EvidenceCommit{request,basis,next.revision,how_many});
    return {move(next),move(changed),key};
}
string init_evidence_buffer(const string& package,const string& pin,const string& goal_bytes){
    const auto program=evidence_session_program(package,pin);
    const auto goals=offline_goals(program,goal_bytes);
    EvidenceState initial;
    initial.package=pin;initial.goals=sha256(goal_bytes);
    EvidencePlanes planes(program,goals);
    planes.recompute(initial);
    (void)planes.result(initial);
    return evidence_snapshot(initial);
}
EvidenceBufferTransition evolve_evidence_buffer(const string& package,const string& pin,const string& goal_bytes,
                                 const string& prior,const string& expected,const string& frame){
    require(workspace_digest(expected)&&sha256(prior)==expected,"CL evidence buffer basis SHA-256 mismatch");
    require(frame.size()<=4096&&frame.find_first_of("\r\n")==string::npos&&frame.find('\0')==string::npos,
            "CL evidence frame invalid");
    Parser args{frame};
    (void)args.name();
    require(args.name()=="batch","CL evidence buffer accepts only batch frames");
    const auto program=evidence_session_program(package,pin);
    const auto goals=offline_goals(program,goal_bytes);
    const auto state=read_evidence_snapshot(prior,program,pin,sha256(goal_bytes));
    EvidencePlanes planes(program,goals);
    planes.verify_rows(state);
    const auto batch=prepare_evidence_batch(program,planes,state,expected,args);
    const auto& result=batch.next?*batch.next:state;
    planes.recompute(result);
    return {batch.next?evidence_snapshot(result):prior,transaction_receipt(result,batch.key,!batch.next),planes.result(result)};
}

#ifndef CL_PORTABLE_MEMORY_CORE
struct ClLiveEvidence final : EvidenceSession {
    Program program;
    vector<Atom> goals;
    EvidenceJournal journal;
    EvidenceState state;
    EvidencePlanes planes;
    bool poisoned=false;
    std::mutex mutex;
    ClLiveEvidence(const string& raw,const string& pin,const string& goal_bytes,const fs::path& target,bool init)
        :program(evidence_session_program(raw,pin)),goals(offline_goals(program,goal_bytes)),journal(target),
         planes(program,goals){
        state.package=pin;state.goals=sha256(goal_bytes);
        if(!init){
            const auto body=journal.bytes();
            state=read_evidence_snapshot(body,program,pin,state.goals);
            journal.known=sha256(body);
        }
        planes.verify_rows(state);
        planes.recompute(state);
        if(init)journal.save(state,true);
    }
    string command(const string& line) override{
        const std::lock_guard barrier(mutex);
        require(!poisoned,"CL evidence session has uncertain commit; close and reopen to reconcile");
        string id;
        try{
            require(line.size()<=4096&&line.find_first_of("\r\n")==string::npos&&line.find('\0')==string::npos,"CL evidence frame invalid");
            Parser p{line};id=p.name();const auto op=p.name();
            string reply;
            auto persist=[&](EvidenceState& next,const set<string>& changed){
                auto prepared=planes;
                prepared.recompute(next,changed);
                (void)prepared.result(next);
                journal.save(next);
                state=std::move(next);
                planes.cache=std::move(prepared.cache);
                planes.rebuilt=std::move(prepared.rebuilt);
            };
            if(op=="view"||op=="check"){
                p.end();
                if(op=="check")planes.verify_complete(state);
            }else if(op=="receipt"){
                const auto key=p.name();p.end();reply=transaction_receipt(state,key);
            }else if(op=="batch"){
                auto batch=prepare_evidence_batch(program,planes,state,journal.known,p);
                if(batch.next)persist(*batch.next,batch.changed);
                reply=transaction_receipt(state,batch.key,!batch.next);
            }else{
                const auto expected=p.term();
                require(expected==to_string(state.revision),"CL evidence expected revision is stale");
                auto next=state;
                const auto changed=apply_evidence_edit(program,planes,next,p,op);p.end();
                if(!changed.empty()){
                    require(next.revision<0xffffffffU,"CL evidence revision limit");
                    ++next.revision;
                    persist(next,{changed});
                }
            }
            if(reply.empty())reply=planes.result(state);
            return "{\"schema\":\"cl-evidence-session-v1\",\"id\":"+quote_json(id)+",\"ok\":true,\"payload\":"+reply+"}\n";
        }catch(const native_os::UncertainCommit& e){
            poisoned=true;throw EvidenceCommitUncertain(e.what());
        }catch(const exception& err){
            return "{\"schema\":\"cl-evidence-session-v1\",\"id\":"+(id.empty()?string("null"):quote_json(id))+
                ",\"ok\":false,\"error\":"+quote_json(err.what())+"}\n";
        }
    }
};
std::unique_ptr<EvidenceSession> open_evidence_session(const std::string& raw,const std::string& pin,
                        const std::string& goals,const std::string& path,bool create){
    require(!path.empty()&&path.find('\0')==string::npos,"CL evidence journal path invalid");
    try{return std::make_unique<ClLiveEvidence>(raw,pin,goals,fs::path(path),create);}
    catch(const native_os::UncertainCommit& e){throw EvidenceCommitUncertain(e.what());}
}
int run_evidence_session(const string& raw,const string& pin,const string& goal_bytes,const fs::path& target,bool init){
    ClLiveEvidence session(raw,pin,goal_bytes,target,init);
    cout<<unitbuf;
    string line;bool overflow;
    while(workspace_read(cin,line,overflow)){
        if(overflow){cout<<"{\"schema\":\"cl-evidence-session-v1\",\"id\":null,\"ok\":false,\"error\":\"CL evidence frame too long\"}\n";continue;}
        try{cout<<session.command(line);}
        catch(const EvidenceCommitUncertain& err){cerr<<err.what()<<'\n';return 2;}
    }
    return 0;
}

struct ClAuditReader final : EvidenceSession {
    const string pin;
    const Program program;
    const vector<Atom> requested;
    const string goal_pin;
    const fs::path path;
    const native_os::Descriptor anchor;
    EvidencePlanes validator;
    std::mutex access;
    static Program checked_package(const string& raw,const string& digest){
        require(workspace_digest(digest)&&sha256(raw)==digest,"CL evidence audit package SHA-256 mismatch");
        return verify_package(decode_package(raw));
    }
    ClAuditReader(const string& raw,const string& digest,const string& goal_bytes,const fs::path& target)
        :pin(digest),program(checked_package(raw,pin)),requested(offline_goals(program,goal_bytes)),
         goal_pin(sha256(goal_bytes)),path(fs::canonical(fs::absolute(target).parent_path())/target.filename()),
         anchor(native_os::open_directory(path.parent_path())),validator(program,requested){
        require(anchor.fd>=0,"cannot open CL evidence audit directory");
    }
    string command(const string& line) override {
        std::lock_guard guard(access);
        string id;
        try{
            require(line.size()<=4096&&line.find('\0')==string::npos&&line.find('\n')==string::npos,
                    "invalid or oversized CL evidence audit frame");
            Parser p{line};id=p.name();const auto op=p.name();
            require(op=="snapshot"||op=="receipt"||op=="feed"||op=="resume","unknown read-only CL evidence operation");
            p.ws();
            const size_t start=p.i;
            while(p.i<p.s.size()&&p.s[p.i]!=' ')++p.i;
            const auto required=p.s.substr(start,p.i-start);
            require(required=="latest"||workspace_digest(required),"expected latest or exact CL evidence audit snapshot digest");
            native_os::confirm_directory(anchor.fd,path.parent_path(),"CL evidence audit directory moved");
            const auto bytes=native_os::read_confined_component(anchor.fd,path.filename().string(),evidence_journal_limit,{
                "cannot open CL evidence audit directory","cannot read CL evidence audit journal",
                "CL evidence audit journal is not a regular file","cannot read complete CL evidence audit journal",
                "CL evidence audit journal exceeds size limit"});
            const auto snapshot_sha=sha256(bytes);
            require(required=="latest"||required==snapshot_sha,"CL evidence audit snapshot changed; no mixed-page response");
            const auto state=read_evidence_snapshot(bytes,program,pin,goal_pin);
            validator.verify_rows(state);
            ostringstream view;
            view<<"{\"schema\":\"cl-evidence-audit-v1\",\"id\":"<<quote_json(id)
                <<",\"ok\":true,\"snapshot_sha256\":"<<quote_json(snapshot_sha)
                <<",\"revision\":"<<state.revision<<",\"result\":";
            if(op=="snapshot"){
                p.end();view<<"{\"package_sha256\":"<<quote_json(pin)<<",\"goals_sha256\":"<<quote_json(goal_pin)
                    <<",\"rows\":"<<state.rows.size()<<",\"recorded_transactions\":"<<state.receipts.size()<<'}';
            }else if(op=="receipt"){
                const auto key=p.name();p.end();
                view<<transaction_receipt(state,key);
            }else{
                auto number=[&](){
                    const auto arg=p.term();const auto n=integer(arg);
                    require(n>=0&&to_string(n)==arg,"noncanonical CL evidence feed number");
                    return static_cast<size_t>(n);
                };
                const auto cursor=number();
                auto prefix_digest=[&](size_t through){
                    map<size_t,string> all;
                    for(const auto& [key,receipt]:state.receipts)
                        if(receipt.revision<=through)all.emplace(receipt.revision,key);
                    string chain="cl-evidence-feed-prefix-v1\n"+pin+"\n"+goal_pin+"\n"+to_string(through)+"\n";
                    for(const auto& [rev,key]:all){(void)rev;chain+=transaction_receipt(state,key)+'\n';}
                    return sha256(chain);
                };
                string claimed;
                if(op=="resume"){
                    p.ws();const auto begin=p.i;
                    while(p.i<p.s.size()&&p.s[p.i]!=' ')++p.i;
                    claimed=p.s.substr(begin,p.i-begin);
                    require((cursor==0&&claimed=="origin")||
                            (workspace_digest(claimed)&&claimed==prefix_digest(cursor)),
                            "CL evidence acknowledged receipt prefix differs");
                }
                const auto limit=number();p.end();
                require(cursor<=state.revision&&limit>0&&limit<=32,"invalid CL evidence feed cursor or limit");
                map<size_t,string> sorted;
                for(const auto& [key,receipt]:state.receipts)
                    if(receipt.revision>cursor)sorted.emplace(receipt.revision,key);
                size_t shown=0,next=cursor;
                view<<"{\"events\":[";
                for(const auto& [rev,key]:sorted){
                    if(shown==limit)break;
                    if(shown++)view<<',';
                    view<<transaction_receipt(state,key);
                    next=rev;
                }
                if(shown==sorted.size())next=state.revision;
                view<<"],\"next_cursor\":"<<next<<",\"more\":"<<(shown<sorted.size()?"true":"false");
                if(op=="resume")view<<",\"next_prefix_sha256\":"<<quote_json(prefix_digest(next));
                view<<'}';
            }
            view<<'}';
            return view.str()+'\n';
        }catch(const std::bad_alloc&){throw;}
        catch(const exception& e){
            ostringstream out;
            out<<"{\"schema\":\"cl-evidence-audit-v1\",\"id\":"<<(id.empty()?"null":quote_json(id))
                <<",\"ok\":false,\"error\":"<<quote_json(e.what())<<"}\n";
            return out.str();
        }

    }
};
std::unique_ptr<EvidenceSession> open_evidence_audit(const std::string& raw,const std::string& pin,
                      const std::string& goals,const std::string& path){
    require(!path.empty()&&path.find('\0')==string::npos,"CL evidence audit path invalid");
    return std::make_unique<ClAuditReader>(raw,pin,goals,fs::path(path));
}
int run_evidence_audit(const string& raw,const string& pin,const string& goal_bytes,const fs::path& target){
    ClAuditReader reader(raw,pin,goal_bytes,target);
    cout<<unitbuf;
    string frame;bool overflow=false;
    while(workspace_read(cin,frame,overflow)){
        if(overflow){cout<<"{\"schema\":\"cl-evidence-audit-v1\",\"id\":null,\"ok\":false,\"error\":\"CL evidence audit frame too long\"}\n";continue;}
        cout<<reader.command(frame);
    }
    return 0;
}

#endif
