bool workspace_read(istream& in,string& line,bool& overflow){
    overflow=false;line.clear(); bool seen=false;char c;
    while(in.get(c)){
        seen=true;
        if(c=='\n')return true;
        if(line.size()<4096)line+=c;else overflow=true;
    }
    return seen;
}
string workspace_tail(Parser& q){
    q.ws();
    require(q.i<q.s.size(),"expected source line");
    auto s=q.s.substr(q.i);
    require(s.find('\0')==string::npos,"NUL is not source text");
    return s;
}
size_t workspace_line(Parser& p){
    p.ws();const auto start=p.i;
    while(p.i<p.s.size()&&p.s[p.i]>='0'&&p.s[p.i]<='9')++p.i;
    const auto number=p.s.substr(start,p.i-start);
    require(!number.empty(),"expected source line number");
    size_t n=0;
    const auto end=number.data()+number.size();
    const auto result=from_chars(number.data(),end,n);
    require(result.ec==errc()&&result.ptr==end&&n>0&&to_string(n)==number,"invalid line number");
    return n;
}
pair<size_t,size_t> line_span(const string& source,size_t number){
    size_t first=0;
    for(size_t i=1;i<number;++i){
        const auto split=source.find('\n',first);
        require(split!=string::npos&&split+1<source.size(),"source line does not exist");
        first=split+1;
    }
    require(first<source.size(),"source line does not exist");
    const auto limit=source.find('\n',first);
    return {first,limit==string::npos?source.size():limit};
}
string workspace_hex(const string& source){
    constexpr char digits[]="0123456789abcdef";
    string hex;hex.reserve(2*source.size());
    for(unsigned char x:source){hex+=digits[x>>4];hex+=digits[x&15];}
    return hex;
}
struct WorkspaceProgram {
    string source,digest;
    Program code;
    Table facts;
    explicit WorkspaceProgram(string bytes)
        :source(std::move(bytes)),digest(sha256(source)),code(compile(source)),facts(run(code)){}
};
int workspace_repl(string base){
    WorkspaceProgram active(std::move(base));
    optional<string> draft;
    optional<WorkspaceProgram> verified;
    size_t revision=0;
    auto render_status=[&](){
        return "{\"revision\":"+to_string(revision)+",\"source_sha256\":"+quote_json(active.digest)+
            ",\"staged\":"+(draft?"true":"false")+",\"draft_verified\":"+(verified?"true":"false")+"}";
    };
    cout<<unitbuf;
    string line;
    bool overflow=false;
    while(workspace_read(cin,line,overflow)){
        string id;
        try{
            require(!overflow,"workspace line exceeds 4096 bytes");
            Parser q{line};
            id=q.name();const auto operation=q.name();
            string payload;
            if(operation=="status"){q.end();payload=render_status();}
            else if(operation=="begin"){
                require(!draft,"a workspace transaction already exists");
                const auto digest=workspace_tail(q);
                require(digest==active.digest,"workspace revision changed");
                draft=active.source;
                payload=render_status();
            }else if(operation=="append"||operation=="replace"||operation=="remove"){
                require(draft.has_value(),"begin a workspace transaction first");
                auto edited=*draft;
                if(operation=="append"){
                    const auto source=workspace_tail(q);
                    if(!edited.empty()&&!edited.ends_with('\n'))edited+='\n';
                    edited+=source+"\n";
                }else{
                    const auto from=workspace_line(q);
                    const auto [first,last]=line_span(edited,from);
                    if(operation=="remove"){q.end();edited.erase(first,last-first+(last<edited.size()));}
                    else edited.replace(first,last-first,workspace_tail(q));
                }
                require(edited.size()<=256*1024,"workspace source size limit");
                draft=move(edited);verified.reset();payload=render_status();
            }else if(operation=="validate"){
                q.end();
                require(draft.has_value(),"begin a workspace transaction first");
                verified.emplace(*draft);
                payload="{\"draft_sha256\":"+quote_json(verified->digest)+",\"rules\":"+to_string(verified->code.rules.size())+
                    ",\"facts\":"+to_string(verified->facts.facts.size())+"}";
            }else if(operation=="commit"){
                require(draft&&verified,"validate the active draft first");
                require(workspace_tail(q)==verified->digest,"workspace draft digest changed");
                const bool changed=verified->digest!=active.digest;
                if(changed){active=move(*verified);++revision;}
                draft.reset();verified.reset();
                payload=render_status();
            }else if(operation=="abort"){
                q.end();require(draft.has_value(),"no workspace transaction to abort");
                draft.reset();verified.reset();payload=render_status();
            }else if(operation=="source"){
                q.end();payload="{\"sha256\":"+quote_json(active.digest)+",\"source\":"+quote_json(active.source)+",\"source_hex\":"+quote_json(workspace_hex(active.source))+"}";
            }else if(operation=="query"||operation=="preview"){
                const auto& version=operation=="preview"?(require(verified.has_value(),"validate the active draft first"),*verified):active;
                auto target=q.atom();q.end();
                require(!target.pred.starts_with('!')&&std::ranges::none_of(target.args,variable),"ask an unsigned ground goal");
                require(version.code.arity.contains(target.pred)&&version.code.arity.at(target.pred)==target.args.size(),"unknown or mismatched relation");
                map<string,Kind> vars;check_type(version.code,target,vars);
                payload=json_report(version.facts,{target},"cl",
                    "{\"source_sha256\":"+quote_json(version.digest)+",\"preview\":"+(operation=="preview"?"true":"false")+"}");
            }else throw runtime_error("unknown workspace operation");
            cout<<"{\"schema\":\"cl-workspace-v1\",\"id\":"<<quote_json(id)<<",\"ok\":true,\"payload\":"<<payload<<"}\n";
        }catch(const exception& error){
            cout<<"{\"schema\":\"cl-workspace-v1\",\"id\":"<<(id.empty()?"null":quote_json(id))
                <<",\"ok\":false,\"error\":"<<quote_json(error.what())<<"}\n";
        }
    }
    return 0;
}
