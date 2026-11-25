string printable_label(const string& raw){
    constexpr char digits[]="0123456789abcdef";
    string out;
    for(unsigned char ch:raw){
        if(ch>=32&&ch<127)out+=static_cast<char>(ch);
        else{out+='%';out+=digits[ch>>4];out+=digits[ch&15];}
    }
    return out;
}
string normalize_artifact(const Program& host,const Program& bundle,const string& alias,const string& digest){
    const string ns="artifact_"+alias+"__";
    const auto scoped=[&](const Atom& a){
        if(sealed_calculation(a.pred)){
            auto copy=a;
            copy.args.at(0)=ns+copy.args.at(0);
            require(copy.args[0].size()<=48,"artifact qualified fold input too long");
            return copy;
        }
        if(comparison(a.pred))return a;
        const auto prefix=base_name(a);
        Atom result=a;
        result.pred=(a.pred.starts_with("!")?"!":"")+ns+prefix;
        require(base_name(result).size()<=48,"artifact qualified predicate too long");
        return result;
    };
    for(const auto& [pred,arity]:bundle.arity){
        const auto qualified=ns+pred;
        if(!host.arity.contains(qualified))continue;
        require(host.arity.at(qualified)==arity&&!host.signatures.contains(qualified)&&
            std::ranges::none_of(host.rules,[&](const Rule& r){return base_name(r.head)==qualified;})&&
            std::ranges::none_of(host.observations,[&](const auto& row){return base_name(row.second)==qualified;}),
            "artifact namespace collides with current definitions");
    }
    string out="# installed CLIR "+alias+" "+digest+"\n";
    for(const auto& [pred,kinds]:bundle.signatures){
        out+=": "+ns+pred+"(";
        for(size_t i=0;i<kinds.size();++i)out+=(i?",":"")+type_text(kinds[i]);
        out+=").\n";
    }
    for(const auto& [id,a]:bundle.observations){
        const auto key=ns+id;
        require(key.size()<=48&&!host.observations.contains(key),"artifact observation identifier collision or limit");
        out+="& "+key+" "+show(scoped(a))+".\n";
        const auto location=bundle.observation_labels.contains(id)?bundle.observation_labels.at(id):id;
        out+="# pcgm_artifact_ref "+key+" CLIR:"+digest+":"+printable_label(location).substr(0,350)+"\n";
    }
    for(size_t i=0;i<bundle.rules.size();++i){
        const auto& r=bundle.rules.at(i);
        const auto location=bundle.rule_labels.empty()?"r"+to_string(i+1):bundle.rule_labels.at(i);
        out+="# pcgm_artifact_rule CLIR:"+digest+":"+printable_label(location).substr(0,350)+"\n";
        out+=show(scoped(r.head));
        for(size_t j=0;j<r.body.size();++j)out+=(j?" & ":" <- ")+show(scoped(r.body[j]));
        out+=".\n";
    }
    for(const auto& g:bundle.goals)out+="? "+show(scoped(g))+".\n";
    return out;
}

void check_artifact_interface(const Program& previous,const Program& next,const string& prefix,int growth=0){
    auto abi=[&](const Program& p){
        map<string,vector<Kind>> result;
        for(const auto& [name,arity]:p.arity){
            if(!name.starts_with(prefix))continue;
            const auto entry=p.signatures.find(name);
            if(growth&&entry==p.signatures.end()&&
                std::ranges::none_of(p.rules,[&](const Rule& r){return base_name(r.head)==name;})&&
                std::ranges::none_of(p.observations,[&](const auto& one){return base_name(one.second)==name;}))continue;
            result.emplace(name,entry==p.signatures.end()?vector<Kind>(arity,"sym"):entry->second);
        }
        return result;
    };
    const auto a=abi(previous),b=abi(next);
    const auto includes=[](const auto& small,const auto& large){
        return std::ranges::all_of(small,[&](const auto& item){
            return large.contains(item.first)&&large.at(item.first)==item.second;
        });
    };
    if(growth==1)require(a.size()<b.size()&&includes(a,b),"artifact additive branch would change an existing signature");
    else if(growth==-1)require(b.size()<a.size()&&includes(b,a),"artifact rollback is not the inverse of an additive branch");
    else require(a==b,"artifact predicate signatures changed");
    auto sources=[&](const Program& p){
        map<string,Atom> result;
        for(const auto& [id,fact]:p.observations)if(id.starts_with(prefix))result.emplace(id,fact);
        return result;
    };
    require(sources(previous)==sources(next),"artifact revision cannot replace observation evidence");
}
Continuity prepare_artifact_switch(const Continuity& current,const Program& host,const StateStore& store,
                                  const string& alias,const string& previous,const string& digest,const string* supplied=nullptr,
                                  bool scope_verified=false){
    require(current.artifacts.contains(alias)&&current.artifacts.at(alias)==previous,
            "artifact active digest changed");
    if(current.scope_policies.contains(alias)){
        const auto& versions=current.package_versions.at(alias);
        const auto& origins=current.scope_origins.at(alias);
        const bool retained=std::ranges::any_of(versions,[&](const auto& old){
            return old.second==digest&&origins.contains(old.first);
        });
        require(retained||(supplied&&scope_verified),"candidate has no attested required CL module policy");
    }
    if(current.workspace_locks.contains(alias)){
        const auto& versions=current.package_versions.at(alias);
        const auto& origins=current.workspace_origins.at(alias);
        const bool retained=std::ranges::any_of(versions,[&](const auto& item){
            return item.second==digest&&origins.contains(item.first);
        });
        require(retained||(supplied&&scope_verified),"candidate has no attested required CL workspace lock");
    }
    artifact_span(current.source,alias,previous);
    auto next=current;
    auto& retained=next.artifact_versions[alias];
    retained.insert(previous);
    if(!retained.contains(digest)){
        require(retained.size()<artifact_version_limit,"retained artifact version limit");
        const auto raw=supplied?*supplied:read_transfer_file(store.dst.parent_path()/"imports",alias+".clir",ir_size_limit);
        require(sha256(raw)==digest,"artifact byte digest mismatch");
        const auto program=from_image(raw);
        const string prefix="artifact_"+alias+"__";
        auto namespace_base=host;
        erase_if(namespace_base.arity,[&](const auto& row){return row.first.starts_with(prefix);});
        erase_if(namespace_base.signatures,[&](const auto& row){return row.first.starts_with(prefix);});
        erase_if(namespace_base.observations,[&](const auto& row){return row.first.starts_with(prefix);});
        next.source+="\n"+normalize_artifact(namespace_base,program.first,alias,digest)+artifact_marker("end",alias,digest);
        retained.insert(digest);
    }
    next.artifacts[alias]=digest;
    ++next.epoch;
    next.events.push_back("artifact_switch "+alias+" "+previous+" "+digest);
    return next;
}
int workspace_growth_direction(const Continuity& state,const string& alias,const string& from,const string& to){
    const auto edges=state.workspace_additive_edges.find(alias);
    if(edges==state.workspace_additive_edges.end())return 0;
    if(edges->second.contains({from,to}))return 1;
    if(edges->second.contains({to,from}))return -1;
    return 0;
}
void append_artifact_choices(vector<Option>& options,const Continuity& current,const Program& program,
                             const Table& table,const StateStore& store,const set<string>* allowed=nullptr,
                             size_t workers=1,DecisionWork* stats=nullptr){
    const auto context=experience_context(program,table);
    const auto prior=read_experiences(current);
    struct Branch {string alias,active,proposed;};
    vector<Branch> work;
    for(const auto& [name,versions]:current.artifact_versions){
        if(allowed&&!allowed->contains(name))continue;
        for(const auto& candidate:versions){
            const auto& active=current.artifacts.at(name);
            if(candidate==active)continue;
            require(options.size()+work.size()<15,"version decision candidate budget exceeded");
            work.push_back({name,active,candidate});
        }
    }
    const auto start=options.size();
    options.reserve(start+work.size());
    for(size_t i=0;i<work.size();++i)options.emplace_back("artifact");
    evaluate_options(work.size(),workers,stats,[&](size_t i){
        const auto& task=work[i];
        auto& o=options[start+i];
        o.revision=task.alias+":"+task.proposed;
        o.evidence.push_back("artifact "+task.alias+" current="+task.active+" proposed="+task.proposed);
        try{
            auto state=prepare_artifact_switch(current,program,store,task.alias,task.active,task.proposed);
            auto plan=compile_active(state);
            const auto growth=workspace_growth_direction(current,task.alias,task.active,task.proposed);
            require(!growth||!allowed,"source-triggered selection has no additive workspace authority");
            if(!growth&&current.workspace_locks.contains(task.alias))
                require(workspace_contract_by_image(current,task.alias,task.active)==
                        workspace_contract_by_image(current,task.alias,task.proposed),
                        "no admitted transition between these workspace API generations");
            check_artifact_interface(program,plan,"artifact_"+task.alias+"__",growth);
            auto expected=run(plan,state.inactive);
            score(o,program,table,expected);
            o.remembered=memory_value(current,program,table,"artifact:"+o.revision,context,prior);
            o.state=std::move(state);o.program=std::move(plan);o.table=std::move(expected);
        }catch(const runtime_error& error){o.error=error.what();}
    });
}

optional<Option> fresh_synthesis_choice(const NativeSynthesisPolicy& policy,const Continuity& current,
                          const Program& program,const Table& table,StateStore& store,const vector<Atom>& packet){
    set<Atom> clean;
    for(const auto& atom:packet)if(base_name(atom)==policy.evidence){
        require(atom.pred==policy.evidence&&proof_without_conflict(table,atom),"new synthesis evidence is contradicted or negative");
        clean.insert(atom);
    }
    if(clean.empty())return {};
    require(clean.size()<=16&&current.generated_artifacts.contains(policy.alias),"native synthesis not ready for this alias");
    string evidence;
    size_t index=0;
    for(const auto& atom:clean)evidence+="& native_evidence_"+to_string(++index)+" "+show(atom)+".\n";
    const auto root=store.dst.parent_path()/"build_inputs";
    const auto name=policy.alias;
    auto product=cl_native::synthesize_profile_bytes(
        read_transfer_file(root,name+".clcp",1024*1024),policy.profile,
        read_transfer_file(root,name+".cl",256*1024),policy.base,
        read_transfer_file(root,name+".generator.cl",256*1024),policy.generator,
        read_transfer_file(root,name+".scope",32768),policy.scope,evidence);
    const auto target=product.product.ir_sha256;
    const auto prior=current.artifacts.at(name);
    if(target==prior||current.generated_artifacts.at(name).contains(target))return {};
    auto next=prepare_artifact_switch(current,program,store,name,prior,target,&product.product.ir);
    auto& history=next.generated_artifacts.at(name);
    require(history.size()<artifact_version_limit&&history.emplace(target,
         CompilerOrigin{policy.profile,product.product.source_sha256,target}).second,"generated artifact provenance limit");
    next.events.push_back("artifact_generated_revision "+name+" "+policy.profile+" "+product.product.source_sha256+" "+target);
    next.synthesized_artifacts[name].emplace(target,SynthesisOrigin{product.generator_sha256,product.scope_sha256,product.evidence_sha256});
    next.events.push_back("artifact_synthesized "+name+" "+target+" "+product.generator_sha256+" "+product.scope_sha256+" "+product.evidence_sha256);
    auto updated=compile_active(next);
    check_artifact_interface(program,updated,"artifact_"+name+"__");
    auto outcomes=run(updated,next.inactive);
    Option option("artifact");
    option.revision=name+":"+target;
    option.evidence.push_back("compiled from packet evidence "+product.evidence_sha256);
    score(option,program,table,outcomes);
    option.remembered=memory_value(current,program,table,"artifact:"+option.revision,experience_context(program,table),read_experiences(current));
    option.state=move(next);option.program=move(updated);option.table=move(outcomes);
    return option;
}
