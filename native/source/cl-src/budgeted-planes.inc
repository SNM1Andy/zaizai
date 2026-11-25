struct PlaneOutcome {
    JoinLimit quota;
    std::string exhausted;
    std::vector<std::string> proof;
};
string render_budgeted_planes(const Program& program,const vector<Atom>& goals,const JoinLimit& total,
                             size_t workers,const string& package,const string& ir,const string& requested){
    const auto plans=plan_planes(program,goals);
    vector<PlaneOutcome> outcomes(plans.size());
    vector<exception_ptr> faults(plans.size());
    const auto grant=[&](size_t cap,size_t i){return cap/plans.size()+(i<cap%plans.size()?1:0);};
    atomic<size_t> next_index{0};
    auto evaluate=[&](){
        for(size_t i;(i=next_index.fetch_add(1))<plans.size();){
            try{
                auto& outcome=outcomes[i];
                outcome.quota={grant(total.rounds,i),grant(total.facts,i),grant(total.probes,i),grant(total.indexed,i)};
                if(!outcome.quota.rounds||!outcome.quota.facts||!outcome.quota.probes||!outcome.quota.indexed){
                    outcome.exhausted="no allocated quota";continue;
                }
                vector<Atom> selected;
                for(const auto j:plans[i].goals)selected.push_back(goals[j]);
                SliceStats counts;
                const auto projection=query_slice(program,selected,counts);
                const auto table=run(projection,{},nullptr,outcome.quota);
                for(const auto& a:selected){
                    ostringstream item;json_fact(item,table,a);outcome.proof.push_back(item.str());
                }
            }catch(const EvaluationLimit& e){outcomes[i].exhausted=e.what();}
            catch(...){faults[i]=current_exception();}
        }
    };
    vector<jthread> pool;
    for(size_t i=1;i<min(workers,plans.size());++i)pool.emplace_back(evaluate);
    evaluate();
    for(auto& w:pool)w.join();
    for(const auto& fault:faults)if(fault)rethrow_exception(fault);
    size_t completed=0;
    for(const auto& result:outcomes)if(result.exhausted.empty())++completed;
    ostringstream out;
    out<<"{\"schema\":\"cl-budgeted-planes-v1\",\"package_sha256\":"<<quote_json(package)
       <<",\"ir_sha256\":"<<quote_json(ir)<<",\"goals_sha256\":"<<quote_json(requested)
       <<",\"complete\":"<<(completed==plans.size()?"true":"false")<<",\"planes\":[";
    for(size_t i=0;i<plans.size();++i){
        if(i)out<<',';
        const auto& one=outcomes[i];
        out<<"{\"goals\":[";
        for(size_t j=0;j<plans[i].goals.size();++j){if(j)out<<',';out<<plans[i].goals[j];}
        out<<"],\"quota\":{\"rounds\":"<<one.quota.rounds<<",\"facts\":"<<one.quota.facts
           <<",\"probes\":"<<one.quota.probes<<",\"indexed\":"<<one.quota.indexed
           <<"},\"status\":"<<quote_json(one.exhausted.empty()?"complete":"exhausted")
           <<",\"exhaustion\":"<<(one.exhausted.empty()?"null":quote_json(one.exhausted))<<",\"results\":[";
        for(size_t j=0;j<one.proof.size();++j){if(j)out<<',';out<<one.proof[j];}
        out<<"]}";
    }
    out<<"]}";
    auto bytes=out.str();
    require(bytes.size()<=4*1024*1024,"CL plane proof receipt exceeds size limit");
    return bytes;
}
