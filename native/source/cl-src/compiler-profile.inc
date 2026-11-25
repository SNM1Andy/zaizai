struct CompilerProfile { string grammar,types,lower,digest; };
CompilerProfile compiler_profile(const string& grammar,const string& types,const string& lower){
    require(grammar.starts_with("CLIR-")&&types.starts_with("CLIR-")&&lower.starts_with("CLIR-"),
            "compiler profile requires verified stage images");
    const auto g=from_image(grammar).first,t=from_image(types).first,l=from_image(lower).first;
    require(g.signatures.contains("lex")&&g.signatures.contains("span")&&g.signatures.contains("accept"),
            "compiler profile has no usable grammar ABI");
    require(t.signatures.contains("tsig")&&t.signatures.contains("bound_before")&&t.signatures.contains("type_error"),
            "compiler profile has no usable numeric type ABI");
    require(l.signatures.contains("lsite")&&l.signatures.contains("emit_site"),"compiler profile has no usable lowering ABI");
    return {grammar,types,lower,{}};
}
string encode_profile(const CompilerProfile& value){
    IRWriter out;
    for(const auto& stage:{value.grammar,value.types,value.lower})package_cell(out,stage,256*1024);
    const auto bytes="CLCP-1\n"+sha256(out.bytes)+"\n"+out.bytes;
    require(bytes.size()<=1024*1024,"compiler profile size limit");
    return bytes;
}
CompilerProfile decode_profile(const string& bytes){
    const string header="CLCP-1\n";
    require(bytes.starts_with(header)&&bytes.size()>=header.size()+65&&bytes.size()<=1024*1024,
            "unsupported or oversized compiler profile");
    const auto payload=bytes.substr(header.size()+65);
    require(bytes[header.size()+64]=='\n'&&sha256(payload)==bytes.substr(header.size(),64),"compiler profile digest mismatch");
    IRReader read{payload};
    const auto grammar=package_get(read,256*1024);
    const auto types=package_get(read,256*1024);
    const auto lower=package_get(read,256*1024);
    require(read.offset==payload.size(),"trailing compiler profile bytes");
    auto profile=compiler_profile(grammar,types,lower);
    profile.digest=sha256(bytes);
    return profile;
}
string profile_build(const CompilerProfile& profile,const string& source){
    const auto normalized=normalize_line_local(profile.grammar,source);
    const auto [trace,passed]=audit_types(profile.types,normalized,true);
    require(passed,"CL profile type audit rejected the candidate: "+trace);
    return direct_lower(normalized,profile.lower).second;
}

string profile_words_digest(istringstream& in){
    string out;
    require(bool(in>>out)&&out.size()==64&&out.find_first_not_of("0123456789abcdef")==string::npos,
            "expected lowercase SHA-256");
    return out;
}
fs::path local_profile_item(const fs::path& root,const string& name,const string& suffix){
    Parser q{name};const auto clean=q.name();q.end();
    const auto path=root/(clean+suffix);
    require(fs::is_regular_file(fs::symlink_status(path))&&fs::canonical(path).parent_path()==root,
            "compiler workspace file missing or outside workspace");
    return path;
}
CompilerProfile verify_self_compilation(const CompilerProfile& active,const string& g,const string& t,const string& l,
                                        const string& smoke,const string& expected){
    auto compiled=compiler_profile(profile_build(active,g),profile_build(active,t),profile_build(active,l));
    compiled.digest=sha256(encode_profile(compiled));
    require(compiled.digest!=active.digest,"self-compiled profile already active");
    try{
        require(profile_build(compiled,g)==compiled.grammar&&profile_build(compiled,t)==compiled.types&&
                profile_build(compiled,l)==compiled.lower,"compiler stages did not reach an exact fixed point");
        require(sha256(profile_build(compiled,smoke))==expected,"self-compiled profile failed the pinned smoke build");
    }catch(const exception& e){throw runtime_error("candidate stage self-check failed: "+string(e.what()));}
    return compiled;
}
struct CompileBackground {
    string base_digest;
    shared_ptr<atomic<bool>> running;
    future<CompilerProfile> result;
};
struct CompilerSnapshot {
    string active,smoke,expected;
    size_t epoch=0;
    map<string,CompilerProfile> retained;
};
struct CompilerCommitUnknown : runtime_error { using runtime_error::runtime_error; };
using CompilerSave=function<void(const CompilerSnapshot&)>;
int run_compiler_session(CompilerProfile active,const fs::path& directory,const string& smoke,const string& expected,
                         optional<CompilerSnapshot> recovery={},CompilerSave durable={}){
    const auto files=fs::canonical(directory);
    require(fs::is_directory(files),"compiler session needs a working directory");
    require(sha256(profile_build(active,smoke))==expected,"initial compiler profile failed the pinned smoke build");
    map<string,CompilerProfile> retained;
    if(recovery)retained=std::move(recovery->retained);
    else retained.emplace(active.digest,active);
    optional<CompilerProfile> staged;
    optional<CompileBackground> pending;
    size_t epoch=recovery?recovery->epoch:0;
    auto status=[&](){
        return "{\"active_profile_sha256\":"+quote_json(active.digest)+",\"epoch\":"+to_string(epoch)+
            ",\"staged_profile_sha256\":"+(staged?quote_json(staged->digest):string("null"))+
            ",\"profiles_retained\":"+to_string(retained.size())+
            (pending?",\"background\":"+quote_json(pending->result.wait_for(chrono::seconds(0))==future_status::ready?"ready":"building"):"")+"}";
    };
    cout<<unitbuf;
    string line;
    bool overflow=false;
    while(workspace_read(cin,line,overflow)){
        string id;
        try{
            require(!overflow,"compiler session line exceeds 4096 bytes");
            Parser q{line};id=q.name();const auto cmd=q.name();
            string body;
            if(cmd=="status"){q.end();body=status();}
            else if(cmd=="stage"||cmd=="stage_retained"){
                require(!staged&&!pending,"finish the existing staged or background profile first");
                istringstream words(q.s.substr(q.i));
                string item,extra;
                if(cmd=="stage")require(bool(words>>item),"expected a compiler profile name");
                const auto prior=profile_words_digest(words),target=profile_words_digest(words);
                require(!(words>>extra),"unexpected compiler staging input");
                require(prior==active.digest&&target!=prior,"compiler profile revision changed or candidate already active");
                CompilerProfile c;
                if(cmd=="stage"){
                    const auto file=local_profile_item(files,item,".clcp");
                    const auto bytes=read_image(file);
                    require(sha256(bytes)==target,"candidate compiler profile digest mismatch");
                    c=decode_profile(bytes);
                }else{
                    require(retained.contains(target),"compiler profile not retained");
                    c=retained.at(target);
                }
                require(sha256(profile_build(c,smoke))==expected,"candidate compiler profile failed the pinned smoke build");
                require(retained.size()<4||retained.contains(c.digest),"compiler profile retention limit");
                staged=move(c);body=status();
            }else if(cmd=="self_stage"||cmd=="self_stage_async"){
                require(!staged&&!pending,"finish the existing staged or background profile first");
                istringstream args(q.s.substr(q.i));
                string g_name,t_name,l_name,extra;
                require(bool(args>>g_name>>t_name>>l_name),"expected three compiler stage source names");
                const auto prior=profile_words_digest(args),g_hash=profile_words_digest(args),
                    t_hash=profile_words_digest(args),l_hash=profile_words_digest(args);
                require(!(args>>extra)&&prior==active.digest,"compiler profile revision changed");
                const auto g=input_file(local_profile_item(files,g_name,".cl"));
                const auto t=input_file(local_profile_item(files,t_name,".cl"));
                const auto l=input_file(local_profile_item(files,l_name,".cl"));
                require(sha256(g)==g_hash&&sha256(t)==t_hash&&sha256(l)==l_hash,"compiler source digest mismatch");
                if(cmd=="self_stage_async"){
                    auto running=make_shared<atomic<bool>>(false);
                    auto result=async(launch::async,[old=active,g,t,l,smoke,expected,running](){
                        running->store(true);
                        try{
                            auto next=verify_self_compilation(old,g,t,l,smoke,expected);
                            running->store(false);return next;
                        }catch(...){running->store(false);throw;}
                    });
                    pending.emplace(CompileBackground{active.digest,move(running),move(result)});
                }else{
                    auto compiled=verify_self_compilation(active,g,t,l,smoke,expected);
                    require(retained.size()<4||retained.contains(compiled.digest),"compiler profile retention limit");
                    staged=move(compiled);
                }
                body=status();
            }else if(cmd=="collect"){
                q.end();require(pending.has_value(),"no compiler background build exists");
                if(pending->result.wait_for(chrono::seconds(0))==future_status::ready){
                    auto finished=move(*pending);pending.reset();
                    auto next=finished.result.get();
                    require(!staged&&finished.base_digest==active.digest,"background compiler context changed");
                    require(retained.size()<4||retained.contains(next.digest),"compiler profile retention limit");
                    staged=move(next);
                }
                body=status();
            }else if(cmd=="export_profile"){
                q.end();const auto pack=encode_profile(active);
                body="{\"profile_sha256\":"+quote_json(active.digest)+",\"profile_hex\":"+quote_json(workspace_hex(pack))+"}";
            }else if(cmd=="activate"){
                istringstream words(q.s.substr(q.i));
                const auto target=profile_words_digest(words);
                string extra;
                require(!(words>>extra)&&staged&&staged->digest==target,"staged compiler digest changed");
                auto remembered=retained;
                remembered.try_emplace(target,*staged);
                if(durable)durable(CompilerSnapshot{target,smoke,expected,epoch+1,remembered});
                retained=std::move(remembered);
                active=move(*staged);staged.reset();++epoch;
                body=status();
            }else if(cmd=="abort"){
                q.end();require(staged.has_value(),"no compiler profile is staged");staged.reset();body=status();
            }else if(cmd=="build"){
                const auto item=q.name();q.end();
                const auto source=input_file(local_profile_item(files,item,".cl"));
                const bool concurrent=pending&&pending->running->load();
                const auto output=profile_build(active,source);
                require(output.size()<=256*1024,"compiler session response limit; use profile-build for larger artifacts");
                body="{\"profile_sha256\":"+quote_json(active.digest)+",\"ir_sha256\":"+quote_json(sha256(output))+
                     ",\"ir_hex\":"+quote_json(workspace_hex(output))+(concurrent?",\"background_profile_in_flight\":true":"")+"}";
            }else throw runtime_error("unknown compiler session operation");
            cout<<"{\"schema\":\"cl-compiler-session-v1\",\"id\":"<<quote_json(id)<<",\"ok\":true,\"payload\":"<<body<<"}\n";
        }catch(const CompilerCommitUnknown&){throw;}catch(const exception& error){
            cout<<"{\"schema\":\"cl-compiler-session-v1\",\"id\":"<<(id.empty()?"null":quote_json(id))
                <<",\"ok\":false,\"error\":"<<quote_json(error.what())<<"}\n";
        }
    }
    return 0;
}
