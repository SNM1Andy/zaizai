map<string,QuantityRecipeScope> compound_scope(const string& encoded,bool multisource=false,bool mixed=false){
    istringstream lines(encoded);string line,prior;map<string,QuantityRecipeScope> slots;
    string canonical="CLWRECIPE-2\n";
    require(bool(getline(lines,line))&&line=="CLWRECIPE-2","invalid compound workspace scope");
    while(getline(lines,line)){
        Parser p{line};
        require(p.take("slot "),"compound recipe requires a named slot");
        const auto name=p.name();
        require(name>prior&&slots.size()<8&&p.i<line.size()&&line[p.i]==' ',"noncanonical compound recipe slot list");
        prior=name;
        const auto details=line.substr(p.i+1);
        auto slot=read_quantity_scope("CLWRECIPE-1\n"+details+"\n");
        if(!slots.empty()){
            const auto& first=slots.begin()->second;
            require((multisource||slot.evidence==first.evidence)&&(mixed||literal_type(slot.prior)==literal_type(first.prior)),
                    "compound recipe must share typed evidence predicate and quantity unit");
        }
        canonical+="slot "+name+" "+details+"\n";
        slots.emplace(name,std::move(slot));
    }
    require(slots.size()>=2&&encoded==canonical,"compound scope needs two or more exact named slots");
    return slots;
}
string materialize_compound_quantity(const string& original,const map<string,QuantityRecipeScope>& slots,
                                     const map<string,string>& choices){
    map<size_t,pair<size_t,string>,std::greater<size_t>> changes;
    for(const auto& [name,scope]:slots){
        const auto sites=locate_quantity(original,scope);
        require(sites.size()==1,"compound recipe slot has no unique exact location");
        require(changes.emplace(sites[0].first,make_pair(sites[0].second,choices.at(name))).second,
                "compound recipe slots overlap");
    }
    string text=original;
    for(const auto& [start,slot]:changes)
        text.replace(start,slot.first-start,slot.second);
    return text;
}
string apply_compound_quantity(const string& original,const string& policy,const map<string,QuantityRecipeScope>& slots,
                               const string& unit,string loaded,bool multisource){
    const auto shape=instantiate_stage(policy,{});
    const map<string,vector<Kind>> ports{{"scope_slot",{"sym",unit}},
        {multisource?"evidence_slot":"evidence_value",multisource?vector<Kind>{"sym",unit}:vector<Kind>{unit}}};
    for(const auto& [name,kinds]:ports){
        require(shape.signatures.contains(name)&&shape.signatures.at(name)==kinds,"compound recipe input ABI mismatch");
        for(const auto& rule:shape.rules)require(base_name(rule.head)!=name,"compound recipe cannot derive its owned evidence");
        for(const auto& [_,datum]:shape.observations)require(base_name(datum)!=name,"compound recipe cannot manufacture input observations");
    }
    require(shape.signatures.contains("rewrite_slot")&&shape.signatures.at("rewrite_slot")==vector<Kind>{"sym",unit,unit},
            "compound recipe declaration missing rewrite slot output");
    for(const auto& [name,scope]:slots)loaded+="& recipe_slot_"+name+" scope_slot("+name+","+scope.prior+").\n";
    const auto table=run(instantiate_stage(policy,loaded));
    map<string,string> choices;
    for(const auto& [a,_]:table.facts){
        if(a.pred!="rewrite_slot")continue;
        const auto& name=a.args.at(0);
        const auto& amount=a.args.at(2);
        const auto location=slots.find(name);
        require(location!=slots.end()&&a.args.at(1)==location->second.prior&&
                !table.facts.contains({"!rewrite_slot",a.args}),"compound recipe output is unknown, conflicting, or bound to stale value");
        const auto& scope=location->second;
        const auto number=[](const string& n){return integer(n.substr(0,n.find('@')));};
        require(amount!=scope.prior&&literal_type(amount)==unit&&number(scope.low)<=number(amount)&&number(amount)<=number(scope.high),
                "compound recipe output outside exact slot range");
        require(choices.emplace(name,amount).second,"compound recipe gave multiple positive proposals for one slot");
    }
    require(slots.size()==choices.size(),"compound recipe did not prove one positive change for every slot");
    return materialize_compound_quantity(original,slots,choices);
}

string rewrite_compound_quantity(const string& original,const string& policy,const string& encoded,const string& input){
    const auto slots=compound_scope(encoded);
    const auto& first=slots.begin()->second;
    Parser sensor{input};const auto observation=sensor.atom();sensor.end();
    require(observation.pred==first.evidence&&observation.args.size()==1&&!variable(observation.args[0])&&
            show(observation)==input&&literal_type(observation.args[0])==literal_type(first.prior),
            "compound recipe requires its exact typed ground evidence");
    const auto unit=literal_type(first.prior);
    return apply_compound_quantity(original,policy,slots,unit,"& recipe_evidence evidence_value("+observation.args[0]+").\n",false);
}
