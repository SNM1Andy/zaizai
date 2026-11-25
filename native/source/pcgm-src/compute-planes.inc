struct ComputePlane {vector<size_t> goals;size_t relations=0,rules=0,observations=0;};
set<string> dependency_relations(const Program& program,const Atom& goal){
    map<string,vector<size_t>> producers;
    for(size_t i=0;i<program.rules.size();++i)
        producers[base_name(program.rules[i].head)].push_back(i);
    set<string> result;
    vector<string> todo;
    auto add=[&](const string& name){if(result.insert(name).second)todo.push_back(name);};
    add(base_name(goal));
    for(size_t i=0;i<todo.size();++i)
        if(const auto origin=producers.find(todo[i]);origin!=producers.end())
            for(auto ri:origin->second){
                for(const auto& term:program.rules[ri].body)
                    if(sealed_calculation(term.pred))add(term.args.at(0));
                    else if(!comparison(term.pred))add(base_name(term));
#ifdef PCGM_SLICE_GUARDS
                if(const auto guard=program.live_guards.find(ri);guard!=program.live_guards.end())
                    add(base_name({guard->second,{}}));
#endif
            }
    return result;
}
vector<ComputePlane> plan_planes(const Program& p,const vector<Atom>& goals){
    require(!goals.empty()&&goals.size()<=64,"compute batch goal count limit");
    vector<size_t> parent(goals.size());
    for(size_t i=0;i<parent.size();++i)parent[i]=i;
    auto root=[&](size_t index){
        while(index!=parent[index]){parent[index]=parent[parent[index]];index=parent[index];}
        return index;
    };
    map<string,size_t> relation_owner;
    for(size_t i=0;i<goals.size();++i)
        for(const auto& name:dependency_relations(p,goals[i])){
            const auto [it,own]=relation_owner.emplace(name,i);
            if(!own){
                const auto a=root(i),b=root(it->second);
                parent[max(a,b)]=min(a,b);
            }
        }
    map<size_t,ComputePlane> groups;
    for(size_t i=0;i<goals.size();++i)groups[root(i)].goals.push_back(i);
    vector<ComputePlane> plans;
    for(auto& [_,plan]:groups)plans.push_back(move(plan));
    return plans;
}
struct ComputeBatch {
    vector<ComputePlane> planes;
    vector<string> results;
    size_t workers=0,peak=0;
};
ComputeBatch evaluate_planes(const Program& p,const vector<Atom>& goals,const set<string>& inactive,
                             size_t ceiling,const function<Table(const Program&,const set<string>&)>& solve){
    require(ceiling<=4,"compute worker ceiling is four");
    ComputeBatch result;
    result.planes=plan_planes(p,goals);
    result.results.resize(goals.size());
    const auto detected=max(1U,thread::hardware_concurrency());
    const size_t chosen=ceiling?ceiling:min(detected,4U);
    result.workers=min(chosen,result.planes.size());
    vector<exception_ptr> faults(result.planes.size());
    atomic<size_t> next{0},active{0},maximum{0};
    auto worker=[&](){
        for(size_t i;(i=next.fetch_add(1))<result.planes.size();){
            const auto concurrent=active.fetch_add(1)+1;
            auto previous=maximum.load();
            while(previous<concurrent&&!maximum.compare_exchange_weak(previous,concurrent)){}
            try{
                auto& plane=result.planes[i];
                vector<Atom> selected;
                for(auto index:plane.goals)selected.push_back(goals[index]);
                SliceStats counts;
                const auto projection=query_slice(p,selected,counts);
                const auto table=solve(projection,inactive);
                plane.relations=counts.relations;plane.rules=counts.rules;plane.observations=counts.observations;
                for(auto index:plane.goals){
                    ostringstream row;
                    json_fact(row,table,goals[index]);
                    result.results[index]=row.str();
                }
            }catch(...){faults[i]=current_exception();}
            active.fetch_sub(1);
        }
    };
    vector<jthread> workers;
    for(size_t i=1;i<result.workers;++i)workers.emplace_back(worker);
    worker();
    for(auto& item:workers)item.join();
    for(const auto& f:faults)if(f)rethrow_exception(f);
    result.peak=maximum.load();
    return result;
}
string render_planes(const ComputeBatch& result,const string& context){
    ostringstream out;
    out<<"{\"schema\":\"cl-compute-batch-v1\",\"backend\":\"cpu\",\"workers\":"<<result.workers
       <<",\"peak_active\":"<<result.peak<<",\"context\":"<<context<<",\"planes\":[";
    bool first=true;
    for(const auto& plane:result.planes){
        if(!first)out<<',';
        first=false;
        out<<"{\"goals\":[";
        for(size_t j=0;j<plane.goals.size();++j){if(j)out<<',';out<<plane.goals[j];}
        out<<"],\"relations\":"<<plane.relations<<",\"rules\":"<<plane.rules<<",\"observations\":"<<plane.observations<<'}';
    }
    out<<"],\"results\":[";
    for(size_t i=0;i<result.results.size();++i){if(i)out<<',';out<<result.results[i];}
    out<<"]}";
    const auto body=out.str();
    require(body.size()<=2*1024*1024,"compute batch proof response exceeds 2 MiB");
    return body;
}
