string apply_mixed_quantity(const string& original,const string& policy,const map<string,QuantityRecipeScope>& slots,
                            const map<string,string>& evidence){
    const auto shape=instantiate_stage(policy,{});
    string loaded;
    for(const auto& [name,scope]:slots){
        const auto unit=literal_type(scope.prior);
        for(const string& port:{"scope_"+name,"evidence_"+name}){
            require(shape.signatures.contains(port)&&shape.signatures.at(port)==vector<Kind>{unit},
                    "mixed recipe input port does not match declared unit");
            for(const auto& rule:shape.rules)require(base_name(rule.head)!=port,"mixed recipe cannot derive its external inputs");
            for(const auto& [_,datum]:shape.observations)require(base_name(datum)!=port,"mixed recipe cannot manufacture input observations");
        }
        const auto output="rewrite_"+name;
        require(shape.signatures.contains(output)&&shape.signatures.at(output)==vector<Kind>{unit,unit},
                "mixed recipe output port does not match declared unit");
        loaded+="& old_"+name+" scope_"+name+"("+scope.prior+").\n";
        loaded+="& input_"+name+" evidence_"+name+"("+evidence.at(name)+").\n";
    }
    const auto table=run(instantiate_stage(policy,loaded));
    map<string,string> choices;
    for(const auto& [fact,certificate]:table.facts){
        if(!fact.pred.starts_with("rewrite_"))continue;
        const auto name=fact.pred.substr(8);
        const auto slot=slots.find(name);
        require(slot!=slots.end(),"mixed recipe attempted to change an unknown slot");
        const auto& scope=slot->second;
        require(fact.args.at(0)==scope.prior&&certificate.origin.starts_with("r")&&!certificate.parents.empty(),
                "mixed recipe needs an inferred output from the exact prior value");
        const auto& amount=fact.args.at(1);
        const auto number=[](const string& n){return integer(n.substr(0,n.find('@')));};
        require(amount!=scope.prior&&literal_type(amount)==literal_type(scope.prior)&&
                number(scope.low)<=number(amount)&&number(amount)<=number(scope.high),
                "mixed recipe output outside typed slot boundary");
        vector<Atom> frontier{fact};
        set<Atom> lineage;
        for(size_t i=0;i<frontier.size();++i){
            const auto current=frontier[i];
            if(!lineage.insert(current).second)continue;
            require(lineage.size()<=512&&table.facts.contains(current)&&
                    !table.facts.contains({current.pred.starts_with("!")?current.pred.substr(1):"!"+current.pred,current.args}),
                    "mixed recipe proof is conflicting or exceeds the evidence bound");
            for(const auto& parent:table.facts.at(current).parents){
                if(!lineage.contains(parent))frontier.push_back(parent);
                require(frontier.size()<=4096,"mixed recipe lineage exceeds evidence bound");
            }
        }
        require(lineage.contains({"scope_"+name,{scope.prior}})&&lineage.contains({"evidence_"+name,{evidence.at(name)}}),
                "mixed recipe output was not proved from its own exact authorized inputs");
        require(choices.emplace(name,amount).second,"mixed recipe proved more than one proposal for a slot");
    }
    require(choices.size()==slots.size(),"mixed recipe must prove each typed change");
    return materialize_compound_quantity(original,slots,choices);
}
