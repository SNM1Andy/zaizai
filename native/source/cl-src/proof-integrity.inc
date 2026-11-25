void require_integrity_scope(const Program& program){
    for (const auto& rule:program.rules)
        for (const auto& atom:rule.body)
            require(!fold_calculation(atom.pred)&&!unit_conversion(atom.pred),
                    "proof integrity v1 does not cover closed folds or observed unit conversion");
}

string integrity_report(const Program& program,const vector<Atom>& goals,const Table& raw,const string& context,bool* clean_single=nullptr){
    auto opposite=[](Atom a){
        if(a.pred.starts_with('!'))a.pred.erase(0,1);else a.pred.insert(0,1,'!');
        return a;
    };
    set<Atom> disputed;
    for(const auto& [a,_]:raw.facts)
        if(raw.facts.contains(opposite(a)))disputed.insert(a);
    optional<Table> filtered;
    if(!disputed.empty()){
        RoundEvaluator evaluator(program,{},JoinLimit{},nullptr,nullptr,&disputed);
        while(!evaluator.advance()){}
        filtered.emplace(evaluator.take());
        for(const auto& [a,_]:filtered->facts)
            require(raw.facts.contains(a),"integrity evaluation derived outside signed closure");
    }
    const auto& clean=filtered?*filtered:raw;
    auto status=[&](const Atom& a){
        return !raw.facts.contains(a)?"NO_SUPPORT":
               disputed.contains(a)?"DIRECT_DISPUTE":
               clean.facts.contains(a)?"CLEAN_WITNESS":"DISPUTED_ANCESTRY";
    };
    if(clean_single){
        require(goals.size()==1,"single-goal integrity advisory requires one goal");
        const auto& g=goals.front();
        const auto n=opposite(g);
        *clean_single=(raw.facts.contains(g)!=raw.facts.contains(n))&&
                      (clean.facts.contains(g)||clean.facts.contains(n));
    }
    ostringstream out;
    out<<context<<",\"results\":[";
    bool first=true;
    for(const auto& a:goals){
        if(!first)out<<',';
        first=false;
        const auto n=opposite(a);
        out<<"{\"goal\":";json_atom(out,a);
        out<<",\"positive_status\":"<<quote_json(status(a))<<",\"negative_status\":"<<quote_json(status(n))
           <<",\"positive_witness\":";json_branch(out,clean,a);
        out<<",\"negative_witness\":";json_branch(out,clean,n);
        out<<'}';
    }
    out<<"]}\n";
    require(out.tellp()<=4*1024*1024,"CL proof integrity receipt exceeds size limit");
    return out.str();
}

string exact_package_integrity(const string& bytes,const string& pin,const string& query_bytes) {
    require(pin.size()==64&&pin.find_first_not_of("0123456789abcdef")==string::npos,
            "a separately trusted lowercase package SHA-256 is required");
    require(sha256(bytes)==pin,"package does not match supplied SHA-256");
    const auto bundle=decode_package(bytes);
    const auto program=verify_package(bundle);
    const auto goals=offline_goals(program,query_bytes);
    require_integrity_scope(program);
    const auto raw=run(program);
    return integrity_report(program,goals,raw,"{\"schema\":\"cl-package-proof-integrity-v1\",\"package_sha256\":"+
        quote_json(pin)+",\"ir_sha256\":"+quote_json(sha256(bundle.ir))+
        ",\"goals_sha256\":"+quote_json(sha256(query_bytes)));
}
