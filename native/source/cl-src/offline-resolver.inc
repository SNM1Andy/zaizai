using ResolveVersion=std::array<unsigned,3>;
ResolveVersion numeric_release_version(const string& text){
    ResolveVersion result{};
    string canonical;
    size_t start=0;
    for(size_t i=0;i<result.size();++i){
        const auto end=i+1==result.size()?text.size():text.find('.',start);
        require(end!=string::npos&&end>start&&end-start<=5&&start<text.size(),"invalid CL numeric release version");
        const auto value=from_chars(text.data()+start,text.data()+end,result[i]);
        require(value.ec==errc{}&&value.ptr==text.data()+end&&result[i]<=65535,"invalid CL numeric release version");
        if(i)canonical+='.';
        canonical+=to_string(result[i]);start=end+1;
    }
    require(canonical==text,"noncanonical CL numeric release version");
    return result;
}
bool resolver_module(const string& module){
    Parser p{module};const auto parsed=p.name();p.end();return parsed==module&&valid_module(module);
}
bool resolver_policy(const string& scope){return scope=="-"||workspace_digest(scope);}
struct ResolveEntry {
    string module,filename,pin,scope,label;
    ResolveVersion version;
};
struct ResolveNeed {string module,scope;ResolveVersion min,max;};
vector<ResolveEntry> read_resolve_catalog(const string& bytes){
    istringstream input(bytes);
    string line,expected="CLCAT-1\n";
    require(bool(getline(input,line))&&line=="CLCAT-1","invalid CL dependency catalog header");
    vector<ResolveEntry> result;
    set<string> filenames;
    while(getline(input,line)){
        ResolveEntry entry;
        istringstream record(line);string extra;
        require(result.size()<64&&bool(record>>entry.module>>entry.label>>entry.filename>>entry.pin>>entry.scope)&&!(record>>extra)
                &&resolver_module(entry.module)&&package_filename(entry.filename)&&entry.filename.ends_with(".clpkg")
                &&workspace_digest(entry.pin)&&resolver_policy(entry.scope)&&filenames.insert(entry.filename).second,
                "invalid or duplicate CL catalog entry");
        entry.version=numeric_release_version(entry.label);
        if(!result.empty())require(std::tie(result.back().module,result.back().version)<std::tie(entry.module,entry.version),
                                   "duplicate or out-of-order CL catalog version");
        expected+=entry.module+" "+entry.label+" "+entry.filename+" "+entry.pin+" "+entry.scope+'\n';
        result.push_back(move(entry));
    }
    require(!result.empty()&&expected==bytes,"empty or noncanonical CL dependency catalog");
    return result;
}
vector<ResolveNeed> read_resolve_requirements(const string& bytes){
    istringstream input(bytes);
    string line,canonical="CLREQ-1\n";
    require(bool(getline(input,line))&&line=="CLREQ-1","invalid CL dependency requirements header");
    vector<ResolveNeed> result;
    while(getline(input,line)){
        ResolveNeed row;string lo,hi,extra;
        istringstream fields(line);
        require(result.size()<16&&bool(fields>>row.module>>lo>>hi>>row.scope)&&!(fields>>extra)&&resolver_module(row.module)
                &&resolver_policy(row.scope)&&(result.empty()||result.back().module<row.module),"invalid CL workspace requirement");
        row.min=numeric_release_version(lo);row.max=numeric_release_version(hi);
        require(row.min<row.max,"empty or reversed CL version interval");
        canonical+=row.module+" "+lo+" "+hi+" "+row.scope+'\n';
        result.push_back(move(row));
    }
    require(!result.empty()&&bytes==canonical,"empty or noncanonical CL requirements");
    return result;
}
string resolve_workspace_lock(const string& app,const string& app_pin,const string& requirement_bytes,
       const string& requirement_pin,const string& catalog_bytes,const string& catalog_pin,
       int catalog_dir,const optional<string>& data){
    require(workspace_digest(app_pin)&&sha256(app)==app_pin,"CL resolution app digest mismatch");
    require(workspace_digest(requirement_pin)&&sha256(requirement_bytes)==requirement_pin,"CL resolution requirements digest mismatch");
    require(workspace_digest(catalog_pin)&&sha256(catalog_bytes)==catalog_pin,"CL resolution catalog digest mismatch");
    const auto need=read_resolve_requirements(requirement_bytes);
    const auto all=read_resolve_catalog(catalog_bytes);
    const auto app_unit=LinkedProject::load_text("/clresolver/app.cl",app);
    require(app_unit.imports.size()==need.size()&&
            std::ranges::all_of(need,[&](const auto& item){return app_unit.imports.contains(item.module);}),
            "CL requirements must cover exactly the application's direct imports");
    struct Eligible {
        const ResolveEntry* entry;
        string bytes;
        map<string,string> embedded;
    };
    vector<vector<Eligible>> slots(need.size());
    size_t loaded=0;
    for(size_t i=0;i<need.size();++i){
        const auto& visible=need[i];
        for(auto it=all.rbegin();it!=all.rend();++it){
            if(it->module!=visible.module||it->version<visible.min||!(it->version<visible.max)||it->scope!=visible.scope)continue;
            const auto& item=*it;
            auto raw=native_os::read_confined_component(catalog_dir,item.filename,package_limit,{
                "cannot read CL catalog directory","cannot read eligible CL package","eligible CL package is not regular",
                "cannot read eligible CL package bytes","eligible CL package exceeds limit"});
            require(raw.size()<=32*1024*1024-loaded,"CL resolver candidate byte budget");
            loaded+=raw.size();
            require(sha256(raw)==item.pin,"CL resolver package digest mismatch: "+item.filename);
            const auto pkg=decode_package(raw);
            require((pkg.scope_policy.empty()?string("-"):sha256(pkg.scope_policy))==item.scope,
                    "CL resolver package scope differs: "+item.filename);
            const auto compiled=verify_package(pkg);
            require(compiled.goals.empty()&&pkg.data_name.empty(),"CL dependency is not a reusable library: "+item.filename);
            require(LinkedProject::load_text(pkg.entry,pkg.files.at(pkg.entry)).name==item.module,
                    "CL resolver package root module differs: "+item.filename);
            Eligible eligible{&item,move(raw),{}};
            for(const auto& [path,content]:pkg.files){
                const auto module=LinkedProject::load_text(path,content).name;
                require(eligible.embedded.emplace(module,sha256(content)).second,"duplicate module in verified CL candidate");
            }
            slots[i].push_back(move(eligible));
        }
        require(!slots[i].empty(),"no CL catalog version meets required interval and scope: "+visible.module);
    }
    size_t branches=0,final_attempts=0;
    map<string,pair<string,string>> members;
    vector<const Eligible*> picked;
    string result,why;
    function<bool(size_t)> inspect=[&](size_t depth){
        if(depth==slots.size()){
            require(++final_attempts<=16,"CL resolver local composition attempt budget");
            WorkspaceInput input;
            input.app=app;input.data=data;input.lock="CLWORK-1\n";
            for(const auto* chosen:picked){
                const auto& e=*chosen->entry;
                input.lock+=e.module+" "+e.filename+" "+e.pin+" "+e.scope+'\n';
                input.packages.emplace(e.filename,chosen->bytes);
            }
            try{
                const auto compiled=assemble_workspace_bytes(input,sha256(input.lock));
                (void)package_workspace(input,to_image(compiled.program,{}),sha256(compiled.receipt));
                result=move(input.lock);
                return true;
            }catch(const runtime_error& e){
                why=string(e.what()).substr(0,240);
                return false;
            }
        }
        for(const auto& item:slots[depth]){
            require(++branches<=2048,"CL resolver branch budget");
            vector<string> inserted;bool compatible=true;
            const auto author=item.entry->module+"@"+item.entry->label;
            for(const auto& [module,content]:item.embedded){
                const auto [seen,fresh]=members.emplace(module,make_pair(content,author));
                if(fresh)inserted.push_back(module);
                else if(seen->second.first!=content){
                    why="conflicting embedded module "+module+" in "+seen->second.second+" and "+author;
                    compatible=false;break;
                }
                if(module==app_unit.name||members.size()>31){
                    why="embedded workspace module closure overlaps app or exceeds limit";
                    compatible=false;break;
                }
            }
            if(compatible){
                picked.push_back(&item);
                if(inspect(depth+1))return true;
                picked.pop_back();
            }
            for(const auto& module:inserted)members.erase(module);
        }
        return false;
    };
    const bool solved=inspect(0);
    require(solved,"no compatible CL dependency selection: "+why);
    return result;
}
