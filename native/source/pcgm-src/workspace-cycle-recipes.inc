string committed_workspace_evidence(const vector<cl_native::WorkspaceEvidencePort>& ports,const WorkspaceRecipePolicy& policy,
                                    const string& trigger,const Continuity& state,const Program& program,const Table& proof){
    require(std::ranges::any_of(ports,[&](const auto& port){return port.source==trigger&&port.predicate==policy.evidence;}),
            "workspace recipe trigger is not a required evidence port");
    string bundle="CLWPROOFS-1\n";
    for(const auto& port:ports){
        const auto permitted=program.sensor_policy.find(port.source);
        require(permitted!=program.sensor_policy.end()&&permitted->second.contains(port.predicate)&&
                !state.autopause.contains(port.source),"workspace recipe evidence source is not currently authorized");
        const auto latest=state.last_cycle.find(port.source);
        require(latest!=state.last_cycle.end(),"workspace recipe is waiting for a required source receipt");
        const auto receipt=state.cycles.find({port.source,latest->second});
        require(receipt!=state.cycles.end(),"workspace recipe source receipt missing");
        const Atom* fact=nullptr;string chosen;
        for(unsigned j=1;j<=receipt->second.observations;++j){
            const auto id=cycle_obs_id(port.source,latest->second,j);
            const auto seen=program.observations.find(id);
            require(seen!=program.observations.end(),"workspace recipe receipt observation missing");
            if(base_name(seen->second)!=port.predicate||state.inactive.contains(id))continue;
            require(!fact&&seen->second.pred==port.predicate&&seen->second.args.size()==1&&
                    literal_type(seen->second.args.front())==port.unit&&proof_without_conflict(proof,seen->second),
                    "workspace recipe latest source evidence is ambiguous, contradicted, or mistyped");
            fact=&seen->second;chosen=id;
        }
        require(fact,"workspace recipe latest source receipt lacks active positive evidence");
        bundle+=port.name+" "+port.source+" "+to_string(latest->second)+" "+receipt->second.digest+" "+chosen+" "+show(*fact)+"\n";
    }
    return bundle;
}

string retain_workspace_from_cycle(const WorkspaceRecipePolicy& policy,Continuity& current,Program& program,Table& table,
                                   StateStore& store,const string& trigger,const vector<Atom>& observations,bool named_phase=false){
    vector<Atom> eligible;
    bool seen=false;
    for(const auto& fact:observations)if(base_name(fact)==policy.evidence){
        seen=true;
        if(fact.pred==policy.evidence&&proof_without_conflict(table,fact))eligible.push_back(fact);
    }
    if(!seen)return {};
    require(eligible.size()==1,"workspace cycle recipe needs exactly one new clean signed fact");
    const auto alias=policy.alias;
    require(current.workspace_locks.contains(alias),"workspace cycle recipe has no prepared registered family");
    const auto& history=current.package_versions.at(alias);
    const auto prior=current.artifacts.at(alias);
    require(history.contains(policy.base)&&history.at(policy.base)==prior,"workspace cycle recipe is pinned to an inactive baseline");
    const auto lock=workspace_active_lock(current,alias);
    const auto boundary=pinned_recipe_member(store,named_phase?alias+"."+policy.scope+".scope":alias+".recipe.scope",policy.scope,16*1024);
    const auto ports=cl_native::workspace_evidence_ports(boundary);
    const auto evidence=ports.empty()?show(eligible.front()):committed_workspace_evidence(ports,policy,trigger,current,program,table);
    const auto evidence_sha=sha256(evidence);
    const auto synthesized=cl_native::synthesize_workspace_quantity(
        read_retained_workspace(store,alias,policy.base),policy.base,lock,
        pinned_recipe_member(store,named_phase?alias+"."+policy.recipe+".clir":alias+".recipe.clir",policy.recipe,256*1024),policy.recipe,
        boundary,policy.scope,evidence);
    const auto& product=synthesized.product;
    if(const auto prior_result=history.find(product.package_sha256);prior_result!=history.end()){
        require(prior_result->second==product.ir_sha256,"saved workspace recipe candidate differs");
        return "workspace_recipe_unchanged "+alias+" "+product.ir_sha256;
    }
    require(product.api_sha256==workspace_contract_by_image(current,alias,prior)&&history.size()<artifact_version_limit,
            "workspace cycle recipe public API or version capacity denied");
    require(std::ranges::none_of(history,[&](const auto& row){return row.second==product.ir_sha256;}),
            "workspace cycle recipe does not produce a different rule version");
    auto alternative=prepare_artifact_switch(current,program,store,alias,prior,product.ir_sha256,&product.ir,true);
    auto proposed=compile_active(alternative);
    check_artifact_interface(program,proposed,"artifact_"+alias+"__");
    (void)run(proposed,alternative.inactive);
    auto retained=current;
    retained.source=std::move(alternative.source);
    retained.artifact_versions[alias].insert(prior);
    retained.artifact_versions[alias].insert(product.ir_sha256);
    retained.package_versions[alias].emplace(product.package_sha256,product.ir_sha256);
    retained.workspace_origins[alias].emplace(product.package_sha256,ScopeOrigin{lock,product.workspace_audit_sha256});
    retained.workspace_source_origins[alias].emplace(product.package_sha256,synthesized.source_sha256);
    retained.workspace_recipe_origins[alias].emplace(product.package_sha256,RecipeOrigin{policy.recipe,policy.scope,evidence_sha});
    retained.events.push_back("artifact_workspace_source "+alias+" "+prior+" "+lock+" "+lock+
        " "+product.package_sha256+" "+product.ir_sha256+" "+product.workspace_audit_sha256+" "+synthesized.source_sha256);
    retain_workspace_contract(retained,alias,product.package_sha256,product.api_sha256);
    retained.events.push_back("workspace_recipe_origin "+alias+" "+product.package_sha256+" "+policy.recipe+" "+policy.scope+" "+evidence_sha);
    if(!ports.empty()){
        retained.workspace_proof_origins[alias].emplace(product.package_sha256,WorkspaceProofOrigin{policy.base,evidence,{}});
        retained.events.push_back("workspace_recipe_proof "+alias+" "+product.package_sha256+" "+policy.base+" "+to_hex(evidence));
    }
    require(encode(retained).size()<=state_limit,"workspace cycle recipe storage bound");
    auto unchanged=compile_active(retained);
    auto proof=run(unchanged,retained.inactive);
    const auto diff=changes(program,table,proof);
    require(diff.added.empty()&&diff.removed.empty(),"workspace cycle recipe retention changed live proofs");
    keep_workspace_archive(store,product.package_sha256,synthesized.archive);
    current=std::move(retained);program=std::move(unchanged);table=std::move(proof);
    return "workspace_recipe_retained "+alias+" "+product.ir_sha256;
}

string route_workspace_cycle(const vector<WorkspaceRecipePolicy>& phases,Continuity& current,Program& program,Table& table,
                             StateStore& store,const string& trigger,const vector<Atom>& observations){
    if(phases.size()==1)return retain_workspace_from_cycle(phases.front(),current,program,table,store,trigger,observations);
    const auto& first=phases.front();
    if(std::ranges::none_of(observations,[&](const auto& ob){return base_name(ob)==first.evidence;}))return {};
    require(current.workspace_locks.contains(first.alias),"workspace phase has no verified family");
    const auto& versions=current.package_versions.at(first.alias);
    const auto active=current.artifacts.at(first.alias);
    for(const auto& phase:phases)
        if(versions.contains(phase.base)&&versions.at(phase.base)==active)
            return retain_workspace_from_cycle(phase,current,program,table,store,trigger,observations,true);
    throw runtime_error("no workspace recipe phase applies to the exact active archive");
}
pair<string,string> choose_workspace_cycle_variant(const WorkspaceRecipePolicy& policy,Continuity& basis,Program& program,
                                                  Table& current,StateStore& store,const string& sensor,unsigned sequence){
    require(policy.choose,"workspace evolution requires explicit choice authorization");
    const set<string> allowed{policy.alias};
    auto options=compare_choices(basis,program,current,&sensor,nullptr,4);
    append_artifact_choices(options,basis,program,current,store,&allowed,4);
    const auto selected=best_choice(options);
    if(!selected)return {"undecided","no uniquely superior admissible workspace alternative"};
    auto& winner=options.at(*selected);
    if(winner.name=="stay")return {"stay","no admissible improvement on the current workspace"};
    require(winner.name=="artifact"&&winner.revision.starts_with(policy.alias+":"),"workspace policy selected an unapproved action");
    const auto receipt=render_decision(basis,options,selected,true,"workspace_event:"+sensor+":"+to_string(sequence));
    auto changed=std::move(*winner.state);
    changed.events.push_back("decision artifact "+winner.revision+" "+revision_snapshot(basis)+" "+
        to_string(winner.wishes)+" "+to_string(winner.risk)+" "+to_string(winner.changes));
    const auto id="e"+to_string(changed.events.size());
    record_experience_context(changed,program,current);
    retain_decision(changed,id,receipt);
    basis=std::move(changed);program=std::move(*winner.program);current=std::move(*winner.table);
    return {"version_switched",winner.revision};
}
