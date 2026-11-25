struct SourceUnit{
    fs::path path;
    string bytes,name;
    set<string> imports,public_names,input_names,signatures;
    vector<string> lines;
    map<string,size_t> declaration_lines;
};

bool identifier_head(char c){return c>='a'&&c<='z';}
bool identifier_tail(char c){return identifier_head(c)||(c>='0'&&c<='9')||c=='_';}
bool valid_module(const string& s){return s.size()<=18 && !s.ends_with('_') && s.find("__")==string::npos;}

struct ScopeSite {size_t line;string file,caller,provider,symbol,role;};
struct LinkedProject{
    fs::path root;
    map<fs::path,SourceUnit> units;
    map<string,fs::path> registry;
    set<fs::path> active,done;
    vector<fs::path> order;
    vector<pair<fs::path,size_t>> locations;
    string linked;
    mutable vector<ScopeSite> scope_sites;
    function<void(const LinkedProject&)> scope_verifier;
    bool namespace_observation_ids=false;

    LinkedProject()=default;

    explicit LinkedProject(const fs::path& entry):root(fs::canonical(entry)){
        require(root.filename().string().find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789_.-")==string::npos,
                "project entry filename must be lower-case ASCII");
        visit(root,"");
    }

    static SourceUnit load(const fs::path& path){
        return load_text(path,input_file(path));
    }
    static SourceUnit load_text(const fs::path& path,const string& bytes){
        SourceUnit u;
        u.path=path;u.bytes=bytes;
        istringstream in(u.bytes);string line;size_t n=0;
        while(getline(in,line)){
            ++n;Parser p{line};p.ws();
            try{
                for(const auto* kw:{"module ","use ","export ","input "}){
                    if(!p.take(kw))continue;
                    const auto item=p.name();p.expect(".");p.end();
                    require(item.find("__")==string::npos,"double underscore is reserved");
                    const string k=kw;
                    if(k=="module "){
                        require(u.name.empty()&&valid_module(item),"invalid or duplicate module name");
                        u.name=item;
                    }else if(k=="use "){
                        require(valid_module(item)&&u.imports.insert(item).second,"invalid or duplicate import");
                    }else{
                        require(u.public_names.insert(item).second,"duplicate public predicate");
                        if(k=="input ")u.input_names.insert(item);
                    }
                    line.clear();break;
                }
                if(line.starts_with(":")||(p.i<line.size()&&line[p.i]==':')){
                    Parser decl{line};decl.expect(":");
                    const auto relation=decl.name();
                    u.signatures.insert(relation);
                    u.declaration_lines.try_emplace(relation,n);
                }
                u.lines.push_back(line);
            }catch(const exception& e){throw runtime_error(path.string()+":"+to_string(n)+": "+e.what());}
        }
        require(!u.name.empty(),"project module header missing: "+path.string());
        for(const auto& symbol:u.public_names)
            require(u.signatures.contains(symbol),"public predicate needs a signature: "+u.name+"::"+symbol);
        return u;
    }

    void visit(const fs::path& path,const string& expect){
        if(done.contains(path))return;
        require(active.insert(path).second,"module dependency cycle: "+path.filename().string());
        require(units.size()<32,"module count limit");
        auto u=load(path);
        require(expect.empty()||u.name==expect,"module name does not match import: "+expect);
        require(registry.emplace(u.name,path).second,"duplicate module name: "+u.name);
        for(const auto& name:u.imports){
            const auto child=root.parent_path()/"modules"/(name+".cl");
            require(fs::canonical(child)==child,"module paths cannot leave project or use symlinks");
            visit(child,name);
        }
        active.erase(path);
        units.emplace(path,std::move(u));
        order.push_back(path); done.insert(path);
    }

    string lock_text() const{
        string out="CL-LOCK-1\n";
        for(const auto& [p,u]:units)
            out+=sha256(u.bytes)+"  "+p.lexically_relative(root.parent_path()).generic_string()+"\n";
        return out;
    }

    string transform(const SourceUnit& u,const string& line,bool data,const fs::path& filename={},size_t number=0) const{
        Parser scan{line};scan.ws();
        if(scan.i==line.size()||line[scan.i]=='#')return line;
        const bool observation=line[scan.i]=='&';
        require(!data||observation,"data may only contain source-labelled observations");
        require(data||u.path==root||line[scan.i]!='?',"only the entry module may declare report goals");
        const bool in_rule_head=line[scan.i]!='?'&&!observation;
        const auto scope=[&](const SourceUnit* target,const string& symbol,const string& role){
            if(!scope_verifier)return;
            require(scope_sites.size()<512,"authored module scope site limit");
            scope_sites.push_back({number,filename.lexically_relative(root.parent_path()).generic_string(),u.name,target->name,symbol,role});
        };
        string out;
        size_t placement=0;
        if(namespace_observation_ids&&observation){
            Parser obs{line};obs.expect("&");const auto id=obs.name();
            require(id.find("__")==string::npos,"double underscore is reserved in workspace observation IDs");
            if(u.path!=root){
                const auto qualified=u.name+"__"+id;
                require(qualified.size()<=48,"workspace observation identifier exceeds limit");
                out="& "+qualified;
                placement=obs.i;
            }
        }
        bool first=true;
        for(size_t i=placement;i<line.size();){
            if(line[i]=='"'){out+=cl_text_symbol::term(line,i);continue;}
            if(!identifier_head(line[i])){out+=line[i++];continue;}
            const auto start=i++;
            while(i<line.size()&&identifier_tail(line[i]))++i;
            auto pred=line.substr(start,i-start);
            string package;
            if(line.compare(i,2,"::")==0){
                package=pred;i+=2;
                const auto k=i;
                require(i<line.size()&&identifier_head(line[i]),"expected imported predicate");
                while(i<line.size()&&identifier_tail(line[i]))++i;
                pred=line.substr(k,i-k);
            }
            auto after=i;
            while(after<line.size()&&(line[after]==' '||line[after]=='\t'))++after;
            if(after==line.size()||line[after]!='('){
                require(package.empty(),"qualified names are only valid for predicates");
                out+=line.substr(start,i-start);
                continue;
            }
            if(!first&&line[scan.i]==':'&&package.empty()&&pred=="qty"){
                out+=pred;
                continue;
            }
            if(package.empty()&&sealed_calculation(pred)){
                out+=pred+line.substr(i,after-i+1);
                i=after+1;
                Parser operand{line.substr(i)};
                auto relation=operand.name();
                const SourceUnit* target=&u;
                if(operand.take("::")){
                    const auto imported=relation;
                    require(u.imports.contains(imported),"fold source module not directly imported: "+imported);
                    target=&units.at(registry.at(imported));
                    relation=operand.name();
                    require(target->public_names.contains(relation),"private fold source: "+imported+"::"+relation);
                }
                require(relation.find("__")==string::npos,"double underscore is reserved in fold operands");
                operand.expect(",");
                scope(target,relation,"fold");
                if(target->path!=root)out+=target->name+"__";
                out+=relation+",";
                i+=operand.i;
                first=false;continue;
            }
            require(pred.find("__")==string::npos,"double underscore is reserved");
            const SourceUnit* target=&u;
            if(!package.empty()){
                require(u.imports.contains(package),"module not directly imported: "+package);
                target=&units.at(registry.at(package));
                require(target->public_names.contains(pred),"private predicate: "+package+"::"+pred);
                require(!first||!in_rule_head,"cannot define an imported predicate");
                require(!observation||data,"module observations must target local predicates");
            }
            if(data)require(target->input_names.contains(pred),"data can only write declared input predicate: "+pred);
            if(!comparison(pred))scope(target,pred,data?"data":first&&(in_rule_head||observation)?"write":"read");
            if(target->path==root||comparison(pred)) out+=pred;
            else out+=target->name+"__"+pred;
            first=false;
        }
        return out;
    }
    void push(const SourceUnit& u,const fs::path& file,const vector<string>& lines,bool data,const vector<size_t>* rownums=nullptr){
        for(size_t i=0;i<lines.size();++i){
            const auto line=rownums?rownums->at(i):i+1;
            try{linked+=transform(u,lines[i],data,file,line)+"\n";}
            catch(const exception& e){throw runtime_error(file.string()+":"+to_string(line)+": "+e.what());}
            locations.emplace_back(file,line);
        }
    }
    Program compile_project(const fs::path& data, const vector<string>* generated=nullptr,
                            const vector<size_t>* rownums=nullptr){
        for(const auto& p:order)push(units.at(p),p,units.at(p).lines,false);
        if(generated)push(units.at(root),data,*generated,true,rownums);
        else if(!data.empty()){
            istringstream in(input_file(data));string line;vector<string> lines;
            while(getline(in,line))lines.push_back(line);
            push(units.at(root),fs::canonical(data),lines,true);
        }
        if(scope_verifier)scope_verifier(*this);
        try{
            auto program=compile(linked);
            for(unsigned line:program.rule_lines){
                const auto& [file,local]=locations.at(line-1);
                program.rule_labels.push_back(file.lexically_relative(root.parent_path()).generic_string()+":"+to_string(local));
            }
            return program;
        }
        catch(const exception& e){
            const string msg=e.what();
            if(msg.starts_with("line ")){
                const auto at=msg.find(':');if(at!=string::npos){
                    const auto n=integer(msg.substr(5,at-5));
                    if(n>=1&&static_cast<size_t>(n)<=locations.size()){
                        const auto& [file,line]=locations[n-1];
                        throw runtime_error(file.string()+":"+to_string(line)+msg.substr(at));
                    }
                }
            }
            throw;
        }
    }
};
