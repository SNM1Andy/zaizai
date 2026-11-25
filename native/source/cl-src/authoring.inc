struct Case { size_t line; optional<Atom> atom; string expected; set<string> frontier; };
string atom_truth(const Table& t,Atom a){
    const auto pos=t.facts.contains(a);a.pred="!"+a.pred;
    const auto neg=t.facts.contains(a);
    return pos?(neg?"CONFLICT":"POSITIVE"):(neg?"NEGATIVE":"UNKNOWN");
}
vector<Case> test_cases(const Program& p,const fs::path& file){
    istringstream in(input_file(file));string line;size_t lineno=0;
    vector<Case> list;set<Atom> unique;bool used_frontier=false;
    while(getline(in,line)){
        ++lineno;
        Parser parser{line};parser.ws();
        if(parser.i==line.size()||line[parser.i]=='#')continue;
        try{
            require(list.size()<256,"test count limit");
            if(parser.take("frontier:")){
                require(!used_frontier,"duplicate frontier expectation");used_frontier=true;
                set<string> expected;
                if(!parser.take(".")){
                    do {
                        const auto name=parser.name();
                        require(expected.insert(name).second,"duplicate frontier symbol");
                    }while(parser.take(","));
                    parser.expect(".");
                }
                parser.end();
                require(p.arity.contains("feasible")&&p.arity.at("feasible")==1&&p.arity.contains("dominates")&&p.arity.at("dominates")==2,
                        "frontier test requires feasible/1 and dominates/2");
                list.push_back({lineno,{}, "frontier",expected});continue;
            }
            const auto a=parser.atom();
            require(!a.pred.starts_with("!")&&std::ranges::none_of(a.args,variable),
                    "test must use a ground unsigned predicate");
            require(p.arity.contains(a.pred)&&p.arity.at(a.pred)==a.args.size(),"test predicate missing or wrong arity");
            map<string,Kind> vars;check_type(p,a,vars);
            parser.ws();
            const auto value=parser.s.substr(parser.i);
            istringstream tokens(value);string expected,tail;
            require(bool(tokens>>expected)&&!(tokens>>tail)&&
                    (expected=="POSITIVE"||expected=="NEGATIVE"||expected=="CONFLICT"||expected=="UNKNOWN"),
                    "expected POSITIVE, NEGATIVE, CONFLICT or UNKNOWN");
            require(unique.insert(a).second,"duplicate tested atom");
            list.push_back({lineno,a,expected,{}});
        }catch(const exception& e){throw runtime_error(file.string()+":"+to_string(lineno)+": "+e.what());}
    }
    require(!list.empty(),"no expectations found");
    return list;
}

string show_set(const set<string>& s){
    string out;
    for(const auto& x:s)out+=(out.empty()?"":",")+x;
    return out.empty()?"(none)":out;
}
int run_tests(const Program& p,const Table& t,const fs::path& file){
    const auto list=test_cases(p,file);
    // Generate the full list before printing; a broken program or inconsistent comparison is not a partial suite.
    vector<pair<bool,string>> lines;
    for(const auto& c:list){
        const auto want=c.atom?c.expected:show_set(c.frontier);
        const auto got=c.atom?atom_truth(t,*c.atom):show_set(frontier_set(t));
        lines.emplace_back(want==got, (c.atom?show(*c.atom):"frontier")+
                           " expected="+want+" actual="+got+" line="+to_string(c.line));
    }
    cout<<"TAP version 13\n1.."<<lines.size()<<'\n';
    size_t failures=0;
    for(size_t i=0;i<lines.size();++i){
        const auto& [ok,desc]=lines[i];
        failures+=!ok;
        cout<<(ok?"ok ":"not ok ")<<i+1<<" - "<<desc<<'\n';
    }
    return failures?2:0;
}
void init_project(const fs::path& target){
    require(fs::create_directory(target),"project target already exists; choose a new directory");
    try{
        require(fs::create_directory(target/"modules"),"cannot create module directory");
        auto write=[&](const string& file,const string& bytes){
            const auto path=target/file;
            require(!fs::exists(path),"initializer will not overwrite "+file);
            ofstream out(path,ios::binary);
            require(bool(out.write(bytes.data(),static_cast<streamsize>(bytes.size()))),"cannot write "+file);
            out.close();require(bool(out),"cannot close "+file);
        };
        write("main.cl",R"(module example_app.
use policy.
allowed($x) <- policy::allowed($x).
!allowed($x) <- !policy::allowed($x).
? allowed(amber).
? allowed(blue).
? allowed(green).
? allowed(gray).
)");
        write("modules/policy.cl",R"(module policy.
: allowed(sym).
: reviewed(sym).
input reviewed.
export allowed.
allowed($x) <- reviewed($x).
!allowed($x) <- !reviewed($x).
)");
        write("data.cl",R"(& alpha_review policy::reviewed(amber).
& blue_review !policy::reviewed(blue).
& green_ok policy::reviewed(green).
& green_hold !policy::reviewed(green).
)");
        write("main.cases",R"(allowed(amber) POSITIVE
allowed(blue) NEGATIVE
allowed(green) CONFLICT
allowed(gray) UNKNOWN
)");
        write("README.txt",R"(Run the generated project with a CL 0.6 executable:
cl project-run main.cl main.lock data.cl
cl project-test main.cl main.lock main.cases data.cl
Change data.cl to see test failures; update a rule only after review:
cl lock main.cl > main.lock
)");
        LinkedProject project(target/"main.cl");
        project.compile_project(target/"data.cl");
        write("main.lock",project.lock_text());
    }catch(const exception& e){throw runtime_error(string(e.what())+"; newly created project may be incomplete");}
    cout<<"project_initialized "<<target.string()<<'\n';
}
