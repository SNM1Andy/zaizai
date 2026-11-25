struct JoinWork { size_t rounds=0, probes=0, indexed=0; };
struct JoinIndex {
    using Rows=vector<const Atom*>;
    using Key=vector<string>;
    using Indexes=map<unsigned,map<Key,Rows>>;
    map<string,Rows> by_predicate;
    map<string,Indexes> indexes;
    size_t& build_budget;
    JoinWork* work;
    Rows empty;
    JoinIndex(size_t& budget,JoinWork* counts):build_budget(budget),work(counts){}
    static void ordered_insert(Rows& rows,const Atom* fact){
        if(rows.empty()||*rows.back()<*fact){rows.push_back(fact);return;}
        rows.insert(lower_bound(rows.begin(),rows.end(),fact,[](const Atom* a,const Atom* b){return *a<*b;}),fact);
    }
    void count_index(){
        require(++build_budget<=2000000,"join index budget");
        if(work)++work->indexed;
    }
    static Key project(const Atom& row,unsigned mask){
        Key result;
        for(size_t i=0;i<row.args.size();++i)if(mask&(1U<<i))result.push_back(row.args[i]);
        return result;
    }
    void add(const Atom* fact){
        ordered_insert(by_predicate[fact->pred],fact);
        const auto previous=indexes.find(fact->pred);
        if(previous==indexes.end())return;
        for(auto& [mask,keys]:previous->second){
            count_index();
            ordered_insert(keys[project(*fact,mask)],fact);
        }
    }
    bool has(const string& pred)const{return by_predicate.contains(pred);}
    const Rows& lookup(const Atom& pattern,const map<string,string>& bindings){
        const auto all=by_predicate.find(pattern.pred);
        if(all==by_predicate.end())return empty;
        Key key;
        unsigned mask=0;
        for(size_t i=0;i<pattern.args.size();++i){
            const auto& term=pattern.args[i];
            if(!variable(term)){mask|=1U<<i;key.push_back(term);}
            else if(const auto p=bindings.find(term);p!=bindings.end()){
                mask|=1U<<i;key.push_back(p->second);
            }
        }
        if(!mask)return all->second;
        auto [part,built]=indexes[pattern.pred].try_emplace(mask);
        if(built){
            for(size_t i=0;i<all->second.size();++i)count_index();
            native_projection::build(all->second,mask,part->second,project);
        }
        const auto selected=part->second.find(key);
        return selected==part->second.end()?empty:selected->second;
    }
};
