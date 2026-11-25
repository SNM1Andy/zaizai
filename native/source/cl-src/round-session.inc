string session_status(const RoundEvaluator& eval,const string& package,const string& goals){
    const auto& counters=eval.counters();
    return "{\"schema\":\"cl-round-state-v1\",\"status\":"+
        quote_json(eval.rejected()?(eval.exhausted()?"exhausted":"failed"):eval.complete()?"complete":"running")+
        ",\"package_sha256\":"+quote_json(package)+",\"goals_sha256\":"+quote_json(goals)+
        ",\"rounds\":"+to_string(counters.rounds)+",\"facts\":"+to_string(eval.facts())+
        ",\"probes\":"+to_string(counters.probes)+",\"indexed\":"+to_string(counters.indexed)+"}";
}
void round_session(const string& bytes,const string& package,const string& input,const JoinLimit& limits,
                   const fs::path& save_to,const string& saved,const optional<string>& trusted,bool checked){
    require(package.size()==64 && package.find_first_not_of("0123456789abcdef")==string::npos && sha256(bytes)==package,
            "package does not match supplied SHA-256");
    const auto bundle=decode_package(bytes);
    const auto program=verify_package(bundle);
    const auto goals=offline_goals(program,input);
    const auto digest=sha256(input);
    auto active=!trusted?
        make_unique<RoundEvaluator>(program,set<string>{},limits,nullptr):
        checked?recompute_checkpoint(saved,*trusted,package,digest,limits,program):
        make_unique<RoundEvaluator>(program,limits,inspect_checkpoint(saved,*trusted,package,digest,limits,program));
    auto& eval=*active;
    auto status=[&](){cout<<session_status(eval,package,digest)<<'\n';};
    cout<<std::unitbuf;
    status();
    auto read_instruction=[](string& row,bool& long_line){
        row.clear();long_line=false;
        char c;size_t scanned=0;
        while(cin.get(c)){
            if(c=='\n')return true;
            require(++scanned<=65536,"CL round frame exceeds absolute size limit");
            if(row.size()<40)row+=c;
            else long_line=true;
        }
        return scanned>0;
    };
    string line;
    bool long_line=false;
    while(read_instruction(line,long_line)){
        try{
            require(!long_line,"CL round instruction exceeds size limit");
            if(line=="status"){status();continue;}
            if(line=="abort"){cout<<"{\"schema\":\"cl-round-state-v1\",\"status\":\"aborted\"}\n";return;}
            if(line=="checkpoint"){
                require(!save_to.empty(),"CL session was not started with a checkpoint destination");
                require(eval.rounds()>0&&eval.rounds()<limits.rounds,"CL checkpoint requires usable remaining rounds");
                const auto content=checkpoint_bytes(eval.checkpoint(),package,digest,limits);
                save_checkpoint(save_to,content);
                cout<<"{\"schema\":\"cl-round-checkpoint-v1\",\"sha256\":"<<quote_json(sha256(content))
                    <<",\"state\":"<<session_status(eval,package,digest)<<"}\n";
                continue;
            }
            if(line=="proof"){
                const auto receipt=json_report(eval.result(),goals,"cl",
                    "{\"protocol\":\"cl-offline-proof-v1\",\"package_sha256\":"+quote_json(package)+
                    ",\"ir_sha256\":"+quote_json(sha256(bundle.ir))+",\"goals_sha256\":"+quote_json(digest)+"}");
                require(receipt.size()<=4*1024*1024,"CL receipt exceeds size limit");
                cout<<receipt<<'\n';continue;
            }
            require(line=="finish"||line.starts_with("step "),"unknown CL round instruction");
            const size_t cap=line=="finish"?128:integer(line.substr(5));
            require(cap>0&&cap<=128,"CL round instruction count out of range");
            for(size_t i=0;i<cap&&!eval.complete();++i)eval.advance();
            status();
        }catch(const exception& e){
            cout<<"{\"schema\":\"cl-round-error-v1\",\"state\":"<<session_status(eval,package,digest)
                <<",\"error\":"<<quote_json(e.what())<<"}\n";
        }
    }
}
