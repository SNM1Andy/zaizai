struct IRWriter {
    string bytes;
    void number(size_t n){
        require(n<=0xffffffffU,"IR count overflow");
        for(int i=24;i>=0;i-=8)bytes+=static_cast<char>((n>>i)&255U);
    }
    void text(const string& s){
        require(s.size()<=4096,"IR cell limit");
        number(s.size());bytes+=s;
    }
    void atom(const Atom& a){
        text(a.pred);number(a.args.size());
        for(const auto& s:a.args)text(s);
    }
};
struct IRReader {
    const string& bytes;size_t offset=0;
    unsigned number(size_t max){
        require(bytes.size()-offset>=4,"truncated IR count");
        unsigned n=0;
        for(int i=0;i<4;++i)n=(n<<8)|static_cast<unsigned char>(bytes[offset++]);
        require(n<=max,"IR count exceeds bound");
        return n;
    }
    string text(){
        const auto n=number(4096);
        require(bytes.size()-offset>=n,"truncated IR cell");
        auto s=bytes.substr(offset,n);offset+=n;
        require(s.find('\0')==string::npos,"NUL in IR cell");
        return s;
    }
    Atom atom(){
        Atom a;
        const auto name=text();
        Parser p{name};const bool negative=p.take("!");const auto pred=p.name();p.end();
        require(name==(negative?"!":"")+pred,"noncanonical IR predicate");
        a.pred=name;
        const auto count=number(4);
        require(count>0,"IR atom must have one or more arguments");
        for(unsigned i=0;i<count;++i){
            const auto word=text();
            Parser q{word};const auto resolved=q.term();q.end();
            require(word==resolved,"noncanonical IR term");
            a.args.push_back(word);
        }
        return a;
    }
};

bool uses_text_symbols(const Program& p){
    const auto has=[](const Atom& a){
        return std::ranges::any_of(a.args,[](const string& t){return cl_text_symbol::is_wire(t);});
    };
    for(const auto& rule:p.rules)if(has(rule.head)||std::ranges::any_of(rule.body,has))return true;
    for(const auto& [_,value]:p.observations)if(has(value))return true;
    return std::ranges::any_of(p.goals,has);
}
constexpr size_t ir_size_limit=2*1024*1024;
string to_image(const Program& p,const string& csv){
    IRWriter w;
    w.text(csv);
    w.number(p.signatures.size());
    for(const auto& [name,kinds]:p.signatures){
        w.text(name);w.number(kinds.size());
        for(const auto& k:kinds)w.text(k);
    }
    w.number(p.rules.size());
    for(size_t i=0;i<p.rules.size();++i){
        const auto& r=p.rules[i];
        w.atom(r.head);w.number(r.body.size());
        for(const auto& b:r.body)w.atom(b);
    }
    w.number(p.rule_labels.size());
    for(const auto& where:p.rule_labels)w.text(where);
    w.number(p.observations.size());
    for(const auto& [id,fact]:p.observations){w.text(id);w.atom(fact);}
    w.number(p.observation_labels.size());
    for(const auto& [id,note]:p.observation_labels){w.text(id);w.text(note);}
    w.number(p.goals.size());
    for(const auto& a:p.goals)w.atom(a);
    bool extends=false,proportional=false,folds=false,extended_folds=false,conversions=false,symbol_guards=false;
    for(const auto& rule:p.rules)
        for(const auto& literal:rule.body){
            extends=extends||calculation(literal.pred);
            proportional=proportional||proportional_calculation(literal.pred);
            folds=folds||fold_calculation(literal.pred);
            extended_folds=extended_folds||extended_fold_calculation(literal.pred);
            conversions=conversions||unit_conversion(literal.pred);
            symbol_guards=symbol_guards||cl_text_symbol::comparison_name(literal.pred);
        }
    const auto output=string(symbol_guards?"CLIR-8\n":uses_text_symbols(p)?"CLIR-7\n":conversions?"CLIR-6\n":extended_folds?"CLIR-5\n":folds?"CLIR-4\n":proportional?"CLIR-3\n":extends?"CLIR-2\n":"CLIR-1\n")+sha256(w.bytes)+"\n"+w.bytes;
    require(output.size()<=ir_size_limit,"IR image exceeds 2 MiB");
    return output;
}
string read_image(const fs::path& path){
    ifstream f(path,ios::binary);require(bool(f),"cannot open CL IR image");
    string s(ir_size_limit+1,'\0');f.read(s.data(),s.size());
    require(!f.bad()&&f.gcount()<static_cast<streamsize>(s.size()),"IR image exceeds 2 MiB or cannot be read");
    s.resize(static_cast<size_t>(f.gcount()));
    return s;
}
string ir_name(const string& label){
    Parser p{label};const auto v=p.name();p.end();require(v==label,"noncanonical IR name");return v;
}
pair<Program,string> from_image(const string& full){
    const bool symbol_guard_image=full.starts_with("CLIR-8\n");
    const bool text_image=symbol_guard_image||full.starts_with("CLIR-7\n");
#ifdef PCGM_NO_CLOSED_FOLDS
    const bool fold_image=false,extended_fold_image=false,conversion_image=false;
#else
    const bool conversion_image=text_image||full.starts_with("CLIR-6\n");
    const bool extended_fold_image=conversion_image||full.starts_with("CLIR-5\n");
    const bool fold_image=extended_fold_image||full.starts_with("CLIR-4\n");
#endif
    const bool proportional_image=full.starts_with("CLIR-3\n");
    const bool arithmetic_image=fold_image||proportional_image||full.starts_with("CLIR-2\n");
    const string version=symbol_guard_image?"CLIR-8\n":text_image?"CLIR-7\n":conversion_image?"CLIR-6\n":extended_fold_image?"CLIR-5\n":fold_image?"CLIR-4\n":proportional_image?"CLIR-3\n":arithmetic_image?"CLIR-2\n":"CLIR-1\n";
    require(full.starts_with(version)&&full.size()>=version.size()+65,"unsupported or truncated CL IR image");
    const auto pos=version.size()+64;
    require(full[pos]=='\n',"bad CL IR digest header");
    const auto payload=full.substr(pos+1);
    require(full.substr(version.size(),64)==sha256(payload),"CL IR digest mismatch");
    IRReader r{payload};
    Program p;
    string csv=r.text();
    auto count=r.number(1024);
    for(unsigned i=0;i<count;++i){
        const auto name=ir_name(r.text());
        const auto n=r.number(4);require(n>0,"empty IR signature");
        vector<Kind> types;
        for(unsigned j=0;j<n;++j){
            const auto k=r.text();
            require(k=="sym"||k=="i64"||k.starts_with("qty:"),"invalid IR type");
            if(k.starts_with("qty:"))ir_name(k.substr(4));
            types.push_back(k);
        }
        declare(p,{name,vector<string>(n,"x")});
        require(p.signatures.emplace(name,types).second,"duplicate IR signature");
    }
    bool arithmetic_present=false,proportional_present=false,fold_present=false,extended_fold_present=false,conversion_present=false,symbol_guard_present=false;
    count=r.number(512);
    for(unsigned i=0;i<count;++i){
        Rule rule{r.atom(),{}};
        const auto n=r.number(8);
        set<string> bound;
        for(unsigned j=0;j<n;++j){
            auto prem=r.atom();
            if(comparison(prem.pred)){
                if(cl_text_symbol::comparison_name(prem.pred)){
                    require(symbol_guard_image,"exact symbolic conditions require CLIR-8");
                    symbol_guard_present=true;
                }
                if(calculation(prem.pred)){
                    require(arithmetic_image,"arithmetic requires CLIR-2 or later");
                    if(proportional_calculation(prem.pred)){
                        require(proportional_image||fold_image,"proportional arithmetic requires CLIR-3");
                        proportional_present=true;
                    }
                    if(unit_conversion(prem.pred)){
                        require(conversion_image,"unit conversion requires CLIR-6");
                        conversion_present=true;
                    }
                    if(fold_calculation(prem.pred)){
                        require(fold_image,"closed folds require CLIR-4");
                        fold_present=true;
                        if(extended_fold_calculation(prem.pred)){
                            require(extended_fold_image,"extended closed folds require CLIR-5");
                            extended_fold_present=true;
                        }
                    }
                    arithmetic_present=true;
                }
                check_builtin_binding(prem,bound);
            }else{
                declare(p,prem);
                for(const auto& v:prem.args)if(variable(v))bound.insert(v);
            }
            rule.body.push_back(std::move(prem));
        }
        for(const auto& v:rule.head.args)require(!variable(v)||bound.contains(v),"unbound IR head variable");
        declare(p,rule.head);
        p.rules.push_back(std::move(rule));
    }
    count=r.number(512);
    require(!count||count==p.rules.size(),"IR source location count mismatch");
    for(unsigned i=0;i<count;++i)p.rule_labels.push_back(r.text());
    count=r.number(4096);
    for(unsigned i=0;i<count;++i){
        auto id=ir_name(r.text());auto a=r.atom();
        require(std::ranges::none_of(a.args,variable),"IR observation must be ground");
        declare(p,a);
        require(p.observations.emplace(id,a).second,"duplicate IR observation");
    }
    count=r.number(4096);
    for(unsigned i=0;i<count;++i){
        auto id=ir_name(r.text()), label=r.text();
        require(p.observations.contains(id)&&p.observation_labels.emplace(id,label).second,"invalid IR observation location");
    }
    count=r.number(64);
    for(unsigned i=0;i<count;++i){
        auto a=r.atom();
        require(!a.pred.starts_with("!")&&std::ranges::none_of(a.args,variable),"invalid IR goal");
        declare(p,a);require(p.goals.insert(a).second,"duplicate IR goal");
    }
    require(r.offset==payload.size(),"trailing IR bytes");
    require(version==(symbol_guard_present?"CLIR-8\n":uses_text_symbols(p)?"CLIR-7\n":conversion_present?"CLIR-6\n":extended_fold_present?"CLIR-5\n":fold_present?"CLIR-4\n":proportional_present?"CLIR-3\n":arithmetic_present?"CLIR-2\n":"CLIR-1\n"),
            "noncanonical arithmetic image version");
    for(const auto& rule:p.rules){
        map<string,Kind> params;check_type(p,rule.head,params);
        for(const auto& premise:rule.body)check_type(p,premise,params);
    }
    for(const auto& [_,fact]:p.observations){
        map<string,Kind> params;check_type(p,fact,params);
    }
    for(const auto& goal:p.goals){
        map<string,Kind> params;check_type(p,goal,params);
    }
    validate_calculation_cycles(p.rules);
#ifndef PCGM_NO_CLOSED_FOLDS
    validate_closed_folds(p);
#endif
    return {std::move(p),std::move(csv)};
}
