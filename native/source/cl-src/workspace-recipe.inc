struct QuantityRecipeScope {string head,builtin,prior,low,high,evidence;unsigned position=0;};
QuantityRecipeScope read_quantity_scope(const string& bytes){
    istringstream input(bytes);
    string version,head,op,position,prior,low,high,evidence,rest;
    require(bool(input>>version>>head>>op>>position>>prior>>low>>high>>evidence)&&!(input>>rest)&&version=="CLWRECIPE-1",
            "invalid CL workspace recipe scope");
    Parser h{head};h.name();h.end();
    Parser observed{evidence};observed.name();observed.end();
    require(op=="qty_le"||op=="qty_lt","workspace recipe scope only permits typed quantity comparison");
    require(position=="1"||position=="2","workspace recipe operand must be a comparison input");
    auto exact_term=[](const string& value){
        Parser p{value};const auto checked=p.term();p.end();
        require(checked==value&&!variable(checked)&&literal_type(checked).starts_with("qty:"),
                "workspace recipe scope requires canonical quantities");
    };
    for(const auto& value:{prior,low,high})exact_term(value);
    require(literal_type(prior)==literal_type(low)&&literal_type(prior)==literal_type(high),"workspace recipe scope units differ");
    const auto number=[](const string& n){return integer(n.substr(0,n.find('@')));};
    require(number(low)<=number(prior)&&number(prior)<=number(high),"workspace recipe scope bounds do not include previous value");
    require(bytes=="CLWRECIPE-1\n"+head+" "+op+" "+position+" "+prior+" "+low+" "+high+" "+evidence+"\n","workspace recipe scope is not canonical");
    return {head,op,prior,low,high,evidence,position=="1"?1U:2U};
}
string guided_amount(const string& rule,const QuantityRecipeScope& scope,const string& e){
    Parser term{e};const auto observation=term.atom();term.end();
    require(observation.pred==scope.evidence&&observation.args.size()==1,
            "workspace recipe evidence predicate does not match its exact scope");
    const auto& amount=observation.args.front();
    require(show(observation)==e&&!variable(amount)&&literal_type(amount)==literal_type(scope.prior),
            "workspace recipe evidence has wrong quantity unit or shape");
    const auto baseline=instantiate_stage(rule,{});
    const vector<Kind> kind{literal_type(scope.prior)};
    const map<string,vector<Kind>> contracts{{"scope_value",kind},{"evidence_value",kind}};
    const vector<Kind> output{kind[0],kind[0]};
    require(baseline.signatures.contains("rewrite_amount")&&baseline.signatures.at("rewrite_amount")==output,
            "workspace recipe missing typed rewrite output");
    for(const auto& [port,sig]:contracts){
        require(baseline.signatures.contains(port)&&baseline.signatures.at(port)==sig,"workspace recipe input port type mismatch");
        for(const auto& r:baseline.rules)
            require(base_name(r.head)!=port,"workspace recipe cannot derive its input evidence");
        for(const auto& [_,a]:baseline.observations)
            require(base_name(a)!=port,"workspace recipe cannot manufacture input observations");
    }
    const auto loaded=instantiate_stage(rule,"& recipe_before scope_value("+scope.prior+").\n& recipe_evidence evidence_value("+amount+").\n");
    const auto table=run(loaded);
    string selected;
    for(const auto& [a,_]:table.facts){
        if(a.pred!="rewrite_amount")continue;
        require(a.args.at(0)==scope.prior&&!table.facts.contains({"!rewrite_amount",a.args}),
                "workspace recipe output is conflicting or mismatches active value");
        require(selected.empty(),"workspace recipe yielded more than one positive proposal");
        selected=a.args.at(1);
    }
    require(!selected.empty(),"workspace recipe did not propose an approved positive change");
    const auto number=[](const string& n){return integer(n.substr(0,n.find('@')));};
    require(selected!=scope.prior&&literal_type(selected)==literal_type(scope.prior)&&
            number(scope.low)<=number(selected)&&number(selected)<=number(scope.high),
            "workspace recipe change outside its exact scoped range");
    return selected;
}
vector<pair<size_t,size_t>> locate_quantity(const string& source,const QuantityRecipeScope& scope){
    vector<pair<size_t,size_t>> targets;
    for(size_t offset=0;offset<source.size();){
        auto end=source.find('\n',offset);
        if(end==string::npos)end=source.size();
        string line=source.substr(offset,end-offset);
        Parser p{line};
        p.ws();
        if(p.i<line.size()&&line[p.i]>='a'&&line[p.i]<='z'&&p.name()==scope.head){
            p.i=0;
            (void)p.atom();
            if(p.take("<-")){
                do{
                    const auto neg=p.take("!");
                    auto predicate=p.name();
                    bool local=true;
                    if(p.take("::")){predicate=p.name();local=false;}
                    p.expect("(");
                    unsigned index=0;
                    do{
                        ++index;p.ws();const auto first=p.i;const auto literal=p.term();
                        if(!neg&&local&&predicate==scope.builtin&&scope.position==index&&literal==scope.prior)
                            targets.emplace_back(offset+first,offset+p.i);
                    }while(p.take(","));
                    p.expect(")");
                }while(p.take("&"));
                p.expect(".");p.end();
            }
        }
        offset=end==source.size()?end:end+1;
    }
    return targets;
}
string rewrite_one_quantity(const string& source,const QuantityRecipeScope& scope,const string& wanted){
    const auto targets=locate_quantity(source,scope);
    require(targets.size()==1,"workspace recipe requires exactly one unchanged scoped source location");
    string candidate=source;
    candidate.replace(targets[0].first,targets[0].second-targets[0].first,wanted);
    return candidate;
}
