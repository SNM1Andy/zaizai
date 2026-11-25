constexpr size_t round_checkpoint_cap=8*1024*1024;
constexpr const char* checkpoint_format="CLCPT-1\n";
string checkpoint_bytes(const RoundCheckpoint& value,const string& pin,const string& queries,const JoinLimit& limits){
    IRWriter w;
    w.text(pin);w.text(queries);
    w.number(limits.rounds);w.number(limits.facts);w.number(limits.probes);w.number(limits.indexed);
    w.number(value.counts.rounds);w.number(value.counts.probes);w.number(value.counts.indexed);
    w.number(value.facts.facts.size());
    for(const auto& [fact,proof]:value.facts.facts){
        w.atom(fact);w.text(proof.origin);
        w.number(proof.parents.size());for(const auto& f:proof.parents)w.atom(f);
        w.number(proof.checks.size());for(const auto& p:proof.checks)w.atom(p);
        require(w.bytes.size()<=round_checkpoint_cap,"CL round checkpoint size limit");
    }
    w.number(value.frontier.size());for(const auto& f:value.frontier)w.atom(f);
    w.number(value.masks.size());for(const auto& [p,mask]:value.masks){w.text(p);w.number(mask);}
    const auto output=string(checkpoint_format)+sha256(w.bytes)+"\n"+w.bytes;
    require(output.size()<=round_checkpoint_cap,"CL round checkpoint size limit");
    return output;
}
RoundCheckpoint inspect_checkpoint(const string& bytes,const string& trusted,const string& pin,const string& queries,
                                   const JoinLimit& limits,const Program& program){
    require(trusted.size()==64 && trusted.find_first_not_of("0123456789abcdef")==string::npos && sha256(bytes)==trusted,
            "checkpoint does not match supplied SHA-256");
    const auto n=string(checkpoint_format).size();
    require(bytes.size()>=n+65&&bytes.size()<=round_checkpoint_cap&&bytes.starts_with(checkpoint_format)
            &&bytes[n+64]=='\n',"invalid CL round checkpoint header");
    const auto contents=bytes.substr(n+65);
    require(sha256(contents)==bytes.substr(n,64),"CL round checkpoint body checksum mismatch");
    IRReader r{contents};
    require(r.text()==pin,"CL checkpoint package mismatch");
    require(r.text()==queries,"CL checkpoint goals mismatch");
    const JoinLimit recorded={r.number(128),r.number(12000),r.number(2000000),r.number(2000000)};
    require(recorded.rounds==limits.rounds&&recorded.facts==limits.facts&&recorded.probes==limits.probes
            &&recorded.indexed==limits.indexed,"CL checkpoint resource limits mismatch");
    RoundCheckpoint state;
    state.counts={r.number(limits.rounds),r.number(limits.probes),r.number(limits.indexed)};
    require(state.counts.rounds>0&&state.counts.rounds<limits.rounds,"CL checkpoint requires usable remaining rounds");
    auto count=r.number(limits.facts);
    optional<Atom> prior;
    while(count--){
        const auto f=r.atom();auto why=r.text();
        require(!prior||*prior<f,"CL checkpoint facts are not strictly ordered");
        prior=f;
        const auto arity=program.arity.find(base_name(f));
        require(arity!=program.arity.end()&&arity->second==f.args.size()&&
                std::ranges::none_of(f.args,variable)&&!why.empty(),"CL checkpoint has invalid fact");
        map<string,Kind> vars;check_type(program,f,vars);
        Proof proof{move(why),{},{}};
        auto parents=r.number(512);while(parents--)proof.parents.push_back(r.atom());
        auto checks=r.number(8);
        while(checks--){
            auto a=r.atom();
            require(comparison(a.pred)&&std::ranges::none_of(a.args,variable),"CL checkpoint has invalid calculation witness");
            proof.checks.push_back(move(a));
        }
        state.facts.facts.emplace(f,move(proof));
    }
    count=r.number(state.facts.facts.size());prior.reset();
    while(count--){
        const auto f=r.atom();
        require(!prior||*prior<f,"CL checkpoint frontier is not strictly ordered");
        prior=f;state.frontier.push_back(f);
    }
    count=r.number(min(state.counts.indexed,static_cast<size_t>(8192)));
    optional<pair<string,unsigned>> mask_prior;
    while(count--){
        auto relation=r.text();
        const auto mask=r.number(15);
        const pair current(move(relation),mask);
        require(!mask_prior||*mask_prior<current,"CL checkpoint masks are not strictly ordered");
        mask_prior=current;state.masks.push_back(current);
    }
    require(r.offset==contents.size(),"trailing CL round checkpoint bytes");
    for(const auto& [_,why]:state.facts.facts)
        for(const auto& parent:why.parents)require(state.facts.facts.contains(parent),"CL checkpoint witness missing");
    return state;
}
std::unique_ptr<RoundEvaluator> recompute_checkpoint(const string& saved,const string& pin,
                         const string& package,const string& goals,const JoinLimit& limits,const Program& program){
    const auto elapsed=inspect_checkpoint(saved,pin,package,goals,limits,program).counts.rounds;
    auto native=make_unique<RoundEvaluator>(program,set<string>{},limits,nullptr);
    for(size_t i=0;i<elapsed;++i)
        require(!native->advance(),"CL checkpoint claims an unfinished prefix at or after fixpoint");
    require(checkpoint_bytes(native->checkpoint(),package,goals,limits)==saved,
            "CL checkpoint does not match the independently recomputed prefix");
    return native;
}
#ifndef CL_PORTABLE_MEMORY_CORE
void save_checkpoint(const fs::path& path,const string& bytes){
    const auto dest=fs::absolute(path);
    native_os::Descriptor folder(native_os::open_directory(dest.parent_path()));
    require(folder.fd>=0,"cannot open CL checkpoint directory");
    native_os::atomic_local_commit(dest.filename().string(),folder.fd,bytes,".cl-frontier-",true,{
        "cannot open CL checkpoint temporary file","cannot write CL checkpoint","cannot flush CL checkpoint",
        "checkpoint path already exists or is invalid","cannot replace CL checkpoint",
        "checkpoint commit outcome unknown; inspect existing bytes before retry"});
}

#endif
