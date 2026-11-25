struct JoinLimit {size_t rounds=128, facts=12000, probes=2000000, indexed=2000000;};
struct JoinWork { size_t rounds=0, probes=0, indexed=0; };
struct RuleCost {size_t rounds=0,probes=0,indexed=0,queued=0;};
struct CostLedger {vector<RuleCost> rules;size_t initial_facts=0;};
struct JoinIndex {
    using Rows=vector<const Atom*>;
    using Key=vector<string>;
    using Indexes=map<unsigned,map<Key,Rows>>;
    map<string,Rows> by_predicate;
    map<string,Indexes> indexes;
    size_t& build_budget;
    JoinWork* work;
    size_t row_limit;
    Rows empty;
    JoinIndex(size_t& budget,JoinWork* counts,size_t row_cap):build_budget(budget),work(counts),row_limit(row_cap){}
    static void ordered_insert(Rows& rows,const Atom* fact){
        if(rows.empty()||*rows.back()<*fact){rows.push_back(fact);return;}
        rows.insert(lower_bound(rows.begin(),rows.end(),fact,[](const Atom* a,const Atom* b){return *a<*b;}),fact);
    }
    void count_index(){
        if(++build_budget>row_limit)throw EvaluationLimit("join index budget");
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
    vector<pair<string,unsigned>> written_masks()const{
        vector<pair<string,unsigned>> result;
        for(const auto& [predicate,set]:indexes)
            for(const auto& [mask,_]:set)result.emplace_back(predicate,mask);
        return result;
    }
    void recover_masks(const vector<pair<string,unsigned>>& saved_masks,size_t limit){
        size_t regenerated=0;
        for(const auto& [p,mask]:saved_masks){
            const auto bucket=by_predicate.find(p);
            require(mask>0&&bucket!=by_predicate.end()&&!bucket->second.empty()&&
                    mask<(1U<<bucket->second.front()->args.size()),"checkpoint join index mask invalid");
            auto [index,first]=indexes[p].try_emplace(mask);
            require(first,"checkpoint duplicate join index mask");
            for(size_t i=0;i<bucket->second.size();++i)
                require(++regenerated<=limit,"checkpoint join index reconstruction budget");
            native_projection::build(bucket->second,mask,index->second,project);
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
