class ScopeDeclined : public runtime_error {
public: ScopeDeclined():runtime_error("CL-authored module scope declined"){}
};
pair<bool,string> audit_module_scope(const LinkedProject& project,const string& stage,const string& policy){
    string generated;
    set<string> host_ids;
    auto add=[&](const string& atom){
        require(host_ids.size()<3600,"CL module scope input fact limit");
        const auto id="scope_input_"+to_string(host_ids.size()+1);
        host_ids.insert(id);
        generated+="& "+id+" "+atom+".\n";
    };
    for(const auto& [_,unit]:project.units){
        add("scope_module("+unit.name+")");
        for(const auto& target:unit.imports)add("scope_direct("+unit.name+","+target+")");
        for(const auto& pred:unit.public_names)add("scope_public("+unit.name+","+pred+")");
        for(const auto& pred:unit.input_names)add("scope_input("+unit.name+","+pred+")");
    }
    for(size_t i=0;i<project.scope_sites.size();++i){
        const auto& s=project.scope_sites[i];
        const auto id=to_string(i+1);
        add("scope_call("+id+","+s.caller+","+s.provider+","+s.symbol+")");
        add("scope_role("+id+","+s.role+")");
    }
    const auto authored=instantiate_stage(stage,generated);
    const map<string,vector<Kind>> inputs={
        {"scope_module",{"sym"}},{"scope_direct",{"sym","sym"}},{"scope_public",{"sym","sym"}},
        {"scope_input",{"sym","sym"}},{"scope_call",{"i64","sym","sym","sym"}},{"scope_role",{"i64","sym"}}
    };
    for(const auto& [name,types]:inputs){
        require(authored.signatures.contains(name)&&authored.signatures.at(name)==types,
                "CL module scope missing input "+name);
        for(const auto& rule:authored.rules)require(base_name(rule.head)!=name,"scope profile cannot manufacture graph facts");
    }
    for(const auto& [id,atom]:authored.observations)
        if(inputs.contains(base_name(atom)))require(host_ids.contains(id),"scope profile cannot supply graph facts");
    require(authored.signatures.contains("scope_allow")&&authored.signatures.at("scope_allow")==vector<Kind>{"i64"},
            "CL module scope missing scope_allow output ABI");
    const auto proof=run(authored);
    bool passed=true;
    ostringstream out;
    out<<"{\"schema\":\"cl-authored-module-scope-v1\",\"profile_sha256\":"<<quote_json(policy)
       <<",\"lock_sha256\":"<<quote_json(sha256(project.lock_text()))<<",\"sites\":[";
    for(size_t i=0;i<project.scope_sites.size();++i){
        if(i)out<<',';
        const auto& s=project.scope_sites[i];
        Atom expected{"scope_allow",{to_string(i+1)}};
        const bool positive=proof.facts.contains(expected);
        expected.pred="!scope_allow";
        const bool negative=proof.facts.contains(expected);
        passed=passed&&positive&&!negative;
        out<<"{\"id\":"<<i+1<<",\"file\":"<<quote_json(s.file)<<",\"line\":"<<s.line
           <<",\"caller\":"<<quote_json(s.caller)<<",\"provider\":"<<quote_json(s.provider)
           <<",\"symbol\":"<<quote_json(s.symbol)<<",\"role\":"<<quote_json(s.role)
           <<",\"permission\":"<<quote_json(positive?(negative?"CONFLICT":"ALLOWED"):(negative?"DENIED":"NO_PROOF"))<<"}";
    }
    out<<"],\"passed\":"<<(passed?"true":"false")<<"}";
    return {passed,out.str()};
}
