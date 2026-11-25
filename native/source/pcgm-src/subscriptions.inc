string proof_digest(const Table& t,Atom a){
    string full="PCGM-PROOF-ID-2\n";
    for(int polarity=0;polarity<2;++polarity){
        if(polarity)a.pred="!"+a.pred;
        full+=polarity?"-\n":"+\n";
        if(!t.facts.contains(a))continue;
        vector<Atom> queue{a};set<Atom> entered{a};
        for(size_t i=0;i<queue.size();++i){
            const auto fact=queue[i];
            const auto& proof=t.facts.at(fact);
            full+=show(fact)+"="+proof.identity+"\n";
            for(const auto& check:proof.checks)full+="checked "+show(check)+"\n";
            for(const auto& premise:proof.parents)full+="input "+show(premise)+"\n";
            for(const auto& premise:proof.parents)
                if(entered.insert(premise).second)queue.push_back(premise);
        }
    }
    return sha256(full);
}
void add_notices(Continuity& next,const Table& before,const Table& after){
    for(const auto& [name,fact]:next.watches){
        const auto a=proof_digest(before,fact),b=proof_digest(after,fact);
        if(a==b)continue;
        const auto old=truth_state(before,fact),fresh=truth_state(after,fact);
        const auto id=static_cast<unsigned>(next.events.size()+1);
        next.events.push_back("notice2 "+name+" "+show(fact)+" "+old+" "+fresh+" "+a+" "+b);
        next.notices.push_back({id,name,fact,old,fresh,a,b,2});
    }
}
string notice_report(const Continuity& state,unsigned from,const string& name){
    unsigned after=static_cast<unsigned>(state.events.size());
    size_t found=0;
    bool more=false;
    ostringstream out,body;
    for(const auto& n:state.notices){
        if(n.event<=from||(!name.empty()&&name!=n.watch))continue;
        if(found==64){more=true;break;}
        if(found++)body<<',';
        after=n.event;
        body<<"{\"event\":"<<n.event<<",\"watch\":"<<quote_json(n.watch)
            <<",\"kind\":"<<quote_json(n.before==n.after?"proof":"truth")<<",\"goal\":";
        json_atom(body,n.fact);
        body<<",\"before\":"<<quote_json(n.before)<<",\"after\":"<<quote_json(n.after)
            <<",\"proof_identity_version\":"<<n.identity_version<<",\"prior_sha256\":"<<quote_json(n.source_before)<<",\"current_sha256\":"<<quote_json(n.source_after)<<'}';
    }
    if(!more)after=static_cast<unsigned>(state.events.size());
    out<<"{\"schema\":\"pcgm-notice-v1\",\"from\":"<<from<<",\"cursor\":"<<after<<",\"more\":"
       <<(more?"true":"false")<<",\"results\":["<<body.str()<<"]}";
    return out.str();
}
