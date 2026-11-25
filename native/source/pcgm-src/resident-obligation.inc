/* Read requests and exact local approvals come from independently wired host pipes.
 * A digest binds bytes, not an authority: only the host-provided approval pipe
 * carries authority in this mode. No legacy commands or user-selected paths. */
int resident_obligation(StateStore& store,uintptr_t approval_handle,bool schedule_agenda){
    HANDLE pipes[2]={GetStdHandle(STD_INPUT_HANDLE),reinterpret_cast<HANDLE>(approval_handle)};
    auto same_object=reinterpret_cast<BOOL(WINAPI*)(HANDLE,HANDLE)>(
        GetProcAddress(GetModuleHandleW(L"kernelbase.dll"),"CompareObjectHandles"));
    using QueryObject=LONG(NTAPI*)(HANDLE,ULONG,PVOID,ULONG,PULONG);
    auto query=reinterpret_cast<QueryObject>(GetProcAddress(GetModuleHandleW(L"ntdll.dll"),"NtQueryObject"));
    require(query&&same_object,"Windows pipe identity checks unavailable");
    for(auto pipe:pipes){
        ULONG basic[14]{},length=0;
        require(pipe&&pipe!=INVALID_HANDLE_VALUE&&GetFileType(pipe)==FILE_TYPE_PIPE&&
                query(pipe,0,basic,sizeof(basic),&length)==0&&length==sizeof(basic)&&
                (basic[1]&FILE_READ_DATA)&&!(basic[1]&(FILE_WRITE_DATA|FILE_APPEND_DATA)),
                "resident inputs must be independent read-only pipes");
    }
    require(!same_object(pipes[0],pipes[1]),"resident inputs must be independent pipes");
    auto owned=[&](){
        string head;
        auto state=store.load(&head);
        require(state.owner==build_name&&state.owner_hash==local_binary_hash()&&!state.pending&&state.staged_copy.empty(),
                "resident obligation requires active managed owner");
        return pair{move(state),move(head)};
    };
    const auto [initial,initial_head]=owned();
    string last_scheduled=initial_head;
    auto agenda_report=[](const Continuity& current,const string& head){
        // A follow-up evaluation failure cannot turn a committed approval into a failed ACK.
        try{return discover_agenda(current,head).json(current,head);}
        catch(const exception& ex){return "{\"schema\":\"pcgm-work-agenda-error-v1\",\"actor\":"+quote_json(current.id)+
            ",\"revision_sha256\":"+quote_json(head)+",\"error\":"+quote_json(ex.what())+",\"writes_state\":false}";}
    };
    cout<<unitbuf<<"{\"schema\":"<<quote_json(schedule_agenda?"pcgm-resident-agenda-v1":"pcgm-resident-obligation-v2")
        <<",\"actor\":"<<quote_json(initial.id)<<",\"head_sha256\":"<<quote_json(initial_head);
    if(schedule_agenda)cout<<",\"agenda\":"<<agenda_report(initial,initial_head);
    cout<<"}\n";
    struct Frame {string bytes;bool overflow=false;};
    Frame frames[2];
    auto handle=[&](unsigned channel,const string& row,bool overflow){
        const string name=channel?"approval":"read";
        try{
            require(!overflow,"resident frame exceeds length limit");
            istringstream arg(row);
            string op,actor,head,from,to,review,pin,extra,payload;
            require(bool(arg>>op),"empty resident frame");
            if(schedule_agenda&&!channel&&op=="agenda"){
                require(row==op,"expected agenda without a supplied target or route");
                const auto [current,key]=owned();payload=agenda_report(current,key);
            }else if(schedule_agenda&&((!channel&&op=="agenda_receipt")||(channel&&op=="enroll_agenda"))){
                require(bool(arg>>actor>>head>>review>>pin)&&!(arg>>extra)&&
                        row==op+" "+actor+" "+head+" "+review+" "+pin,"expected ACTOR HEAD REVIEW APPROVAL_SHA256");
                const auto approval=agenda_approval(actor,head,review);
                require(sha256(approval)==pin,"agenda approval pin mismatch");
                if(channel){
                    payload=enroll_anchored_review(store,approval,pin,true);payload.pop_back();
                }else{
                    const auto [current,key]=owned();
                    require(current.id==actor,"agenda receipt addressed to another individual");
                    const auto receipt=current.obligation_enrollments.find(pin);
                    string ticket="null";
                    if(receipt!=current.obligation_enrollments.end()){
                        const auto& [proof,basis,id]=receipt->second;
                        require(proof==review&&basis==head&&current.questions.contains(id),"agenda receipt identity differs");
                        ticket=quote_json(id);
                    }
                    payload="{\"schema\":\"pcgm-agenda-enrollment-receipt-v1\",\"actor\":"+quote_json(actor)+
                        ",\"head_sha256\":"+quote_json(key)+",\"approval_sha256\":"+quote_json(pin)+
                        ",\"status\":"+quote_json(ticket=="null"?"not_recorded":"recorded")+",\"ticket\":"+ticket+
                        ",\"writes_state\":false}";
                }
            }else if(!channel&&op=="review"){
                require(bool(arg>>from>>to)&&!(arg>>extra)&&row==op+" "+from+" "+to,
                        "expected canonical review FROM TO");
                for(const auto& label:{from,to}){Parser p{label};require(p.name()==label,"invalid review route");p.end();}
                const auto [current,key]=owned();
                payload=anchored_goal_obligation(current,key,from,to);
            } else if(!channel&&op=="answer_receipt"){
                string ticket,request,artifact,package,snapshot,proof;
                require(bool(arg>>actor>>ticket>>request>>artifact>>package>>snapshot>>proof)&&!(arg>>extra)&&
                    row==op+" "+actor+" "+ticket+" "+request+" "+artifact+" "+package+" "+snapshot+" "+proof,
                    "expected canonical answer_receipt ACTOR TICKET REQUEST ARTIFACT PACKAGE SNAPSHOT PROOF");
                for(const auto& digest:{request,artifact,package,snapshot,proof})
                    require(digest.size()==64&&hex_chars(digest),"answer receipt requires exact digest pins");
                const auto [current,key]=owned();
                require(current.id==actor,"answer receipt addressed to another individual");
                const auto id=exact_frozen_observation_id(actor,ticket,request,artifact,package,snapshot,proof);
                string status="not_recorded";
                if(const auto saved=current.frozen_receipts.find(id);saved!=current.frozen_receipts.end()){
                    const auto& match=current.bundle_receipts.at(id);
                    require(saved->second==pair{artifact,snapshot}&&match.ticket==ticket&&match.request==request&&
                        match.package==package&&match.proof==proof,"frozen answer receipt identity differs");
                    status=current.inactive.contains(id)?"withdrawn":"recorded";
                }
                payload="{\"schema\":\"pcgm-resident-frozen-receipt-v1\",\"actor\":"+quote_json(actor)+
                    ",\"ticket\":"+quote_json(ticket)+",\"observation\":"+(status=="not_recorded"?"null":quote_json(id))+
                    ",\"head_sha256\":"+quote_json(key)+",\"status\":"+quote_json(status)+",\"writes_state\":false}";
            } else if(channel&&op=="enroll"){
                require(bool(arg>>actor>>head>>from>>to>>review>>pin)&&!(arg>>extra)&&
                    row==op+" "+actor+" "+head+" "+from+" "+to+" "+review+" "+pin,
                    "expected canonical enroll ACTOR HEAD FROM TO REVIEW APPROVAL_SHA256");
                payload=enroll_anchored_review(store,
                    "PCGM-LOCAL-OBLIGATION-APPROVAL-1\n"+actor+"\n"+head+"\n"+from+" "+to+"\n"+review+"\n",pin);
                payload.pop_back();
            } else if(channel&&op=="answer"){
                string ticket,request,member,artifact,package,snapshot,proof;
                require(bool(arg>>actor>>head>>ticket>>request>>member>>artifact>>package>>snapshot>>proof)&&!(arg>>extra)&&
                    row==op+" "+actor+" "+head+" "+ticket+" "+request+" "+member+" "+artifact+" "+package+" "+snapshot+" "+proof,
                    "expected canonical answer ACTOR HEAD TICKET REQUEST MEMBER ARTIFACT PACKAGE SNAPSHOT PROOF");
                auto [current,key]=owned();
                require(current.id==actor&&key==head,"resident answer scope is stale or addressed to another individual");
                auto program=compile_active(current);
                auto table=run(program,current.inactive);
                const auto receipt=admit_frozen_exact(store,current,program,table,ticket,request,member,artifact,package,snapshot,proof);
                payload="{\"schema\":\"pcgm-resident-frozen-answer-v1\",\"actor\":"+quote_json(actor)+
                    ",\"ticket\":"+quote_json(ticket)+",\"observation\":"+quote_json(receipt.id)+
                    ",\"head_sha256\":"+quote_json(sha256(encode(current)))+
                    ",\"proof_sha256\":"+quote_json(proof)+",\"writes_state\":"+(receipt.committed?"true":"false")+
                    ",\"outbound\":false}";
            } else require(false,"operation is not enabled on this resident channel");
            if(schedule_agenda&&channel){
                const auto [current,key]=owned();
                if(key!=last_scheduled){
                    payload.pop_back();
                    payload+=",\"next_agenda\":"+agenda_report(current,key)+"}";
                    last_scheduled=key;
                }
            }
            cout<<"{\"channel\":"<<quote_json(name)<<",\"ok\":true,\"payload\":"<<payload<<"}\n";
        }catch(const exception& ex){
            cout<<"{\"channel\":"<<quote_json(name)<<",\"ok\":false,\"error\":"<<quote_json(ex.what())<<"}\n";
        }
    };
    // A single consumer owns both independent byte streams. Never block reading an
    // empty approval channel while an ordinary query is available, or the reverse.
    while(pipes[0]||pipes[1]){
        bool progress=false;
        for(unsigned i=0;i<2;++i){
            auto& pipe=pipes[i];auto& frame=frames[i];
            if(!pipe)continue;
            DWORD available=0,count=0;
            char bytes[4096];
            const BOOL ok=PeekNamedPipe(pipe,nullptr,0,nullptr,&available,nullptr);
            if(!ok){
                const DWORD err=GetLastError();
                require(err==ERROR_BROKEN_PIPE||err==ERROR_PIPE_NOT_CONNECTED,"resident input pipe failed");
            } else if(!available){continue;}
            else require(ReadFile(pipe,bytes,min<DWORD>(available,sizeof(bytes)),&count,nullptr)!=0,
                         "resident input read failed");
            progress=true;
            if(!count){
                if(!frame.bytes.empty()||frame.overflow)
                    cout<<"{\"channel\":"<<quote_json(i?"approval":"read")
                        <<",\"ok\":false,\"error\":\"unterminated resident frame\"}\n";
                pipe=nullptr;
                continue;
            }
            for(DWORD k=0;k<count;++k){
                if(bytes[k]=='\n'){handle(i,frame.bytes,frame.overflow);frame=Frame{};}
                else if(frame.bytes.size()<1024)frame.bytes+=bytes[k];
                else frame.overflow=true;
            }
        }
        if(!progress)Sleep(2);
    }
    return 0;
}
