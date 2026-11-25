struct SourceRecipe {
    map<string,QuantityRecipeScope> slots;
    vector<WorkspaceEvidencePort> ports;
    bool mixed=false;
};
SourceRecipe parse_source_recipe(const string& encoded){
    istringstream lines(encoded);string line,old="CLWRECIPE-2\n";
    require(bool(getline(lines,line))&&(line=="CLWRECIPE-3"||line=="CLWRECIPE-4"),"invalid source recipe scope");
    const bool mixed=line=="CLWRECIPE-4";
    string canonical=line+"\n";
    while(getline(lines,line)&&line.starts_with("slot ")){old+=line+"\n";canonical+=line+"\n";}
    auto slots=compound_scope(old,true,mixed);
    vector<WorkspaceEvidencePort> inputs;
    set<string> sources;
    for(const auto& [name,scope]:slots){
        Parser p{line};const auto prefix="via "+name+" ";
        require(!mixed||name.size()<=30,"mixed-quantity slot name exceeds typed port length");
        require(p.take(prefix),"source recipes need one exact ordered source per slot");
        const auto source=p.name();p.end();
        require(line==prefix+source,"noncanonical recipe source declaration");
        sources.insert(source);
        inputs.push_back({name,source,scope.evidence,literal_type(scope.prior)});
        canonical+=line+"\n";
        if(!getline(lines,line))line.clear();
    }
    require(line.empty()&&encoded==canonical&&sources.size()>=2,"source recipe must bind at least two distinct sources canonically");
    return {std::move(slots),std::move(inputs),mixed};
}
string rewrite_source_quantity(const string& original,const string& recipe,const string& scope,const string& input){
    const auto plan=parse_source_recipe(scope);
    istringstream lines(input);string line,canonical="CLWPROOFS-1\n",loaded;
    require(bool(getline(lines,line))&&line=="CLWPROOFS-1","source recipe needs a typed evidence bundle");
    map<string,pair<string,string>> proofs;map<string,string> exact;
    set<string> observed_ids;
    for(const auto& port:plan.ports){
        require(bool(getline(lines,line)),"source recipe proof bundle is incomplete");
        istringstream row(line);string name,source,seq,digest,id,fact,extra;
        require(bool(row>>name>>source>>seq>>digest>>id>>fact)&&!(row>>extra)&&name==port.name&&source==port.source&&
                workspace_digest(digest),"evidence source identity or receipt digest does not match its port");
        const auto serial=integer(seq);
        require(serial>=1&&serial<=1000000000&&to_string(serial)==seq,"invalid source receipt sequence");
        const string obs_prefix="sensor_"+source+"_"+seq+"_";
        require(id.starts_with(obs_prefix),"evidence identifier does not belong to the declared receipt");
        const auto pos=id.substr(obs_prefix.size());
        const auto index=integer(pos);
        require(index>=1&&index<=4096&&to_string(index)==pos&&observed_ids.insert(id).second,"invalid or reused source observation");
        auto [it,inserted]=proofs.emplace(source,make_pair(seq,digest));
        require(inserted||it->second==make_pair(seq,digest),"one source cannot combine receipt generations");
        Parser term{fact};const auto ob=term.atom();term.end();
        require(show(ob)==fact&&ob.pred==port.predicate&&ob.args.size()==1&&!variable(ob.args[0])&&
                literal_type(ob.args[0])==port.unit,"evidence fact shape or unit differs from the exact port");
        canonical+=name+" "+source+" "+seq+" "+digest+" "+id+" "+fact+"\n";
        exact.emplace(name,ob.args[0]);
        if(!plan.mixed)loaded+="& recipe_evidence_"+name+" evidence_slot("+name+","+ob.args[0]+").\n";
    }
    require(!(getline(lines,line))&&input==canonical,"unexpected or noncanonical evidence bundle data");
    if(plan.mixed)return apply_mixed_quantity(original,recipe,plan.slots,exact);
    return apply_compound_quantity(original,recipe,plan.slots,plan.ports.front().unit,std::move(loaded),true);
}
