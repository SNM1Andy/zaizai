#ifndef CL_PORTABLE_MEMORY_CORE
std::string read_receipt_input(const fs::path& path,size_t cap){
    return native_os::read_regular_input(path,cap,{"cannot open receipt directory",
        "cannot open receipt input","receipt input must be a regular file",
        "cannot read receipt input","receipt input exceeds size limit"});
}
#endif
vector<Atom> offline_goals(const Program& program,const string& queries){
    vector<Atom> goals;
    istringstream in(queries);
    string line;
    while(getline(in,line)){
        Parser q{line};q.ws();
        if(q.i==line.size()||line[q.i]=='#')continue;
        auto a=q.atom();q.end();
        require(goals.size()<64,"receipt goal count limit");
        require(!a.pred.starts_with('!')&&std::ranges::none_of(a.args,variable),"receipt asks unsigned ground goals");
        require(program.arity.contains(a.pred)&&program.arity.at(a.pred)==a.args.size(),
                "unknown or mismatched receipt goal relation");
        map<string,Kind> vars;check_type(program,a,vars);
        goals.push_back(move(a));
    }
    require(!goals.empty(),"receipt needs at least one goal");
    return goals;
}
string offline_receipt(const string& package,const string& expected,const string& queries,const JoinLimit& budget={},EvidenceSign* qualification=nullptr){
    require(expected.size()==64 && expected.find_first_not_of("0123456789abcdef")==string::npos,
            "a separately trusted lowercase package SHA-256 is required");
    require(sha256(package)==expected,"package does not match supplied SHA-256");
    const auto bundle=decode_package(package);
    auto program=verify_package(bundle);
    const auto goals=offline_goals(program,queries);
    const auto result=run(program,{},nullptr,budget);
    if(qualification){
        require(goals.size()==1,"evidence intake requires one exact CL goal");
        auto negative=goals[0];negative.pred="!"+negative.pred;
        const bool pos=result.facts.contains(goals[0]),neg=result.facts.contains(negative);
        *qualification=pos?(neg?EvidenceSign::Conflict:EvidenceSign::Positive):
                          (neg?EvidenceSign::Negative:EvidenceSign::Unknown);
    }
    return json_report(result,goals,"cl",
        "{\"protocol\":\"cl-offline-proof-v1\",\"package_sha256\":\""+expected+
        "\",\"ir_sha256\":\""+sha256(bundle.ir)+"\",\"goals_sha256\":\""+sha256(queries)+"\"}")+"\n";
}
