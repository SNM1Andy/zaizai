struct Generated {
    optional<Atom> header;
    map<int,Atom> body;
};
bool proof_without_conflict(const Table& t,const Atom& root,bool* limited){
    if(limited)*limited=false;
    vector<Atom> queue{root};set<Atom> seen;
    for(size_t i=0;i<queue.size();++i){
        const auto a=queue[i];
        if(!seen.insert(a).second)continue;
        if(seen.size()>512){if(limited)*limited=true;return false;}
        if(!t.facts.contains(a)||t.facts.contains(opposite_of(a)))return false;
        const auto& proof=t.facts.at(a);
        for(const auto& f:proof.parents){
            if(!seen.contains(f))queue.push_back(f);
            if(queue.size()>4096){if(limited)*limited=true;return false;}
        }
    }
    return true;
}
string render_synth(const Program& p,const Table& t){
    if(p.synth_policy.empty())return {};
    map<string,Generated> records;
    for(const auto& [fact,_]:t.facts){
        if(fact.pred!="gen_head"&&fact.pred!="gen_body")continue;
        const auto& producer=t.facts.at(fact);
        require(producer.origin.starts_with("r")&&!producer.parents.empty(),"synthesis output must be derived: "+show(fact));
        require(proof_without_conflict(t,fact),"conflicted or unreviewable synthesis evidence: "+show(fact));
        auto& entry=records[fact.args[0]];
        require(records.size()<=16,"generated rule count limit");
        if(fact.pred=="gen_head"){
            require(!entry.header,"ambiguous generated rule head");
            entry.header=fact;
        }else{
            const auto& seq=fact.args[1];
            require(seq.size()==1 && seq[0]>='1'&&seq[0]<='8',"generated premise position out of range");
            const int index=seq[0]-'0';
            require(entry.body.emplace(index,fact).second,"ambiguous generated rule premise");
        }
    }
    string patch;
    set<Rule> output;
    for(const auto& [id,entry]:records){
        require(entry.header && !entry.body.empty(),"incomplete generated rule: "+id);
        const auto& head=*entry.header;
        const auto& name=head.args[1];
        const auto& var=head.args[2];
        const auto allowed=p.synth_policy.find(name);
        require(allowed!=p.synth_policy.end(),"generated output not authorized: "+name);
        Rule rule{{name,{"$"+var}},{}};
        int step=0;
        for(const auto& [position,fact]:entry.body){
            const auto& premise=fact.args[2];
            require(position==++step,"generated premise sequence gap");
            require(fact.args[3]==var,"generated premise variable mismatch");
            require(allowed->second.contains(premise),"generated premise not authorized: "+premise);
            rule.body.push_back({premise,{"$"+var}});
        }
        if(find(p.rules.begin(),p.rules.end(),rule)!=p.rules.end() || !output.insert(rule).second)continue;
        patch+="# CL IR origin "+show(head)+" <= "+describe(t.facts.at(head))+"\n";
        for(const auto& [_,premise]:entry.body)
            patch+="# CL IR premise "+show(premise)+" <= "+describe(t.facts.at(premise))+"\n";
        patch+=show(rule.head)+" <- ";
        for(size_t i=0;i<rule.body.size();++i)patch+=(i?" & ":"")+show(rule.body[i]);
        patch+=".\n";
    }
    return patch;
}
#include "multivar.inc"
string combined_patch(const Program& p,const Table& t,bool multi=true){
    return propose(p,t)+render_synth(p,t)+(multi?render_multivariable(p,t):"");
}
