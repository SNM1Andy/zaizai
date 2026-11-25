struct AuditUse {size_t clause,id;Atom atom;string role,form,label;};
struct AuditSignature {size_t clause;string name;vector<Kind> types;};
struct AuditInput {
    vector<AuditUse> uses;
    vector<AuditSignature> signatures;
};
AuditInput audit_collect(const string& canonical,bool numeric){
    AuditInput result;
    istringstream in(canonical);
    string line;size_t clause=0;
    auto capture=[&](Atom a,string role,string form,string label={}){
        require(result.uses.size()<384,"CL-authored type audit occurrence limit");
        if(!numeric&&comparison(base_name(a)))
            throw runtime_error("CL-authored type profile does not include numeric builtin "+a.pred);
        result.uses.push_back({clause,result.uses.size()+1,std::move(a),std::move(role),std::move(form),std::move(label)});
    };
    while(getline(in,line)){
        Parser p{line};p.ws();
        if(p.i==line.size())continue;
        ++clause;
        if(p.take(":")){
            auto name=p.name();
            require(!comparison(name),"CL-authored type profile does not include builtin declarations");
            vector<Kind> types;
            p.expect("(");
            do{
                auto kind=p.name();
                if(kind=="qty"){p.expect("(");kind+=":"+p.name();p.expect(")");}
                require(kind=="sym"||kind=="i64"||kind.starts_with("qty:"),
                        "CL-authored type profile encountered unsupported type "+kind);
                types.push_back(std::move(kind));
            }while(p.take(","));
            p.expect(")");p.expect(".");p.end();
            result.signatures.push_back({clause,std::move(name),std::move(types)});
        }else if(p.take("?")){
            capture(p.atom(),"ground","query");p.expect(".");p.end();
        }else if(p.take("&")){
            const auto label=p.name();capture(p.atom(),"ground","observation",label);p.expect(".");p.end();
        }else{
            auto head=p.atom();
            if(p.take("<-")){
                capture(std::move(head),"head","head");
                do{capture(p.atom(),"body","body");}while(p.take("&"));
            }else capture(std::move(head),"ground","fact");
            p.expect(".");p.end();
        }
    }
    return result;
}

pair<string,bool> audit_types(const string& checker,const string& canonical,bool numeric=false){
    const auto input=audit_collect(canonical,numeric);
    const bool may_compare_symbols=std::ranges::any_of(input.uses,[](const auto& row){
        return cl_text_symbol::comparison_name(base_name(row.atom));
    });
    const bool may_convert=std::ranges::any_of(input.uses,[](const auto& row){return unit_conversion(base_name(row.atom));});
    if(may_convert){
        const auto declared=instantiate_stage(checker,{});
        require(declared.signatures.contains("conversion_abi")&&declared.signatures.at("conversion_abi")==vector<Kind>{"sym"},
                "CL-authored type profile does not support observed unit conversions");
    }
    const bool may_fold=std::ranges::any_of(input.uses,[](const auto& row){return fold_calculation(base_name(row.atom));});
    const bool extended_folds=std::ranges::any_of(input.uses,[](const auto& row){
        return extended_fold_calculation(base_name(row.atom));
    });
    if(may_fold){
        const auto declared=instantiate_stage(checker,{});
        require(declared.signatures.contains("fold_abi")&&declared.signatures.at("fold_abi")==vector<Kind>{"sym"},
                "CL-authored type profile does not support closed folds");
    }
    string facts;
    bool ratios=false,folds=false;
    set<string> written;
    unsigned serial=0;
    set<string> managed;
    map<Kind,unsigned> kind_numbers;
    auto kind_code=[&](const Kind& kind){
        if(!kind_numbers.contains(kind))kind_numbers.emplace(kind,kind_numbers.size()+1);
        return to_string(kind_numbers.at(kind));
    };
    auto add=[&](const string& atom){
        const auto id="audit_"+to_string(++serial);managed.insert(id);
        facts+="& "+id+" "+atom+".\n";
    };
    for(const auto& s:input.signatures){
        const auto line=to_string(s.clause);
        add("tsig("+line+","+s.name+","+to_string(s.types.size())+")");
        for(size_t i=0;i<s.types.size();++i)
            add("tslot("+line+","+to_string(i+1)+","+kind_code(s.types[i])+")");
    }
    for(const auto& row:input.uses)
        if(row.form=="head"||row.form=="fact")written.insert(base_name(row.atom));
    if(numeric&&(may_fold||may_convert))for(const auto& row:input.signatures)
        if(!written.contains(row.name))add("tclosed("+row.name+")");
    for(const auto& use:input.uses){
        const auto site=to_string(use.id),clause=to_string(use.clause);
        add("tuse("+site+","+clause+","+base_name(use.atom)+","+to_string(use.atom.args.size())+")");
        add("trole("+site+","+use.role+")");
        if(numeric){
            const auto op=base_name(use.atom);
            add("tsign("+site+","+(use.atom.pred.starts_with('!')?"negative":"positive")+")");
            if(comparison(op)){
                const bool qty=quantity_comparison(op)||quantity_calculation(op);
                const bool ratio=proportional_calculation(op),fold=fold_calculation(op),convert=unit_conversion(op);
                ratios=ratios||ratio;folds=folds||fold;
                const auto family=cl_text_symbol::comparison_name(op)?string("sym_cmp"):convert?string("qty_conversion"):fold?string(op=="qty_fold_count"?"qty_fold_count":"qty_fold"):ratio?string("qty_ratio"):string(qty?"qty_":"int_")+(calculation(op)?"calc":"cmp");
                add("toperator("+site+","+family+","+(ratio||convert?"4":calculation(op)?"3":"2")+")");
                if(fold&&!use.atom.args.empty()&&!variable(use.atom.args[0])&&literal_type(use.atom.args[0])=="sym")
                    add("tfold("+site+","+use.atom.args[0]+")");
                if(convert&&use.atom.args.size()==4&&!variable(use.atom.args[0])&&!variable(use.atom.args[2])&&
                         literal_type(use.atom.args[0])=="sym"&&literal_type(use.atom.args[2])=="sym")
                    add("tconvert("+site+","+use.atom.args[0]+","+kind_code("qty:"+use.atom.args[2])+")");
            }else add("tplain("+site+")");
        }
        for(size_t i=0;i<use.atom.args.size();++i){
            const auto& word=use.atom.args[i];
            const auto position=to_string(i+1);
            if(variable(word))add("tvar("+site+","+position+","+clause+","+word.substr(1)+")");
            else add("tlit("+site+","+position+","+kind_code(literal_type(word))+")");
        }
    }
    if(numeric){
        (void)kind_code("i64");
        if(may_compare_symbols)(void)kind_code("sym");
        for(const auto& [kind,code]:kind_numbers)
            add("tclass("+to_string(code)+","+(kind=="i64"?"integer":kind=="sym"?"symbol":"quantity")+")");
    }
    const auto program=instantiate_stage(checker,facts);
    map<string,vector<Kind>> contracts{
        {"tsig",{"i64","sym","i64"}},{"tslot",{"i64","i64","i64"}},
        {"tuse",{"i64","i64","sym","i64"}},{"trole",{"i64","sym"}},
        {"tvar",{"i64","i64","i64","sym"}},{"tlit",{"i64","i64","i64"}}
    };
    if(numeric){
        contracts.emplace("toperator",vector<Kind>{"i64","sym","i64"});
        contracts.emplace("tclass",vector<Kind>{"i64","sym"});
        contracts.emplace("tplain",vector<Kind>{"i64"});
        contracts.emplace("tsign",vector<Kind>{"i64","sym"});
    }
    if(folds){
        require(program.signatures.contains("fold_abi")&&program.signatures.at("fold_abi")==vector<Kind>{"sym"},
                "CL-authored type profile does not support closed folds");

        contracts.emplace("tfold",vector<Kind>{"i64","sym"});
    }
    if(folds||may_convert)contracts.emplace("tclosed",vector<Kind>{"sym"});
    if(may_convert)contracts.emplace("tconvert",vector<Kind>{"i64","sym","i64"});
    for(const auto& [pred,types]:contracts){
        require(program.signatures.contains(pred)&&program.signatures.at(pred)==types,"missing type audit input ABI "+pred);
        for(const auto& rule:program.rules)require(base_name(rule.head)!=pred,"checker cannot derive type input facts");
    }
    for(const auto& [id,point]:program.observations)
        if(contracts.contains(base_name(point)))require(managed.contains(id),"checker cannot supply extra type input facts");
    map<string,vector<Kind>> outputs{
        {"known_site",{"i64"}},{"bound_var",{"i64","sym"}},
        {"type_error",{"i64","i64","sym"}},{"declaration_error",{"i64","sym"}}
    };
    if(numeric){
        outputs.emplace("bound_before",vector<Kind>{"i64","i64","sym"});
        outputs.emplace("quantity_known",vector<Kind>{"i64"});
    }
    if(folds)outputs.emplace("fold_known",vector<Kind>{"i64"});
    if(may_convert)outputs.emplace("conversion_known",vector<Kind>{"i64"});
    for(const auto& [key,type]:outputs)require(program.signatures.contains(key)&&program.signatures.at(key)==type,
                                              "missing type audit output ABI "+key);
    const auto evidence=run(program);
    if(may_compare_symbols)require(program.signatures.contains("symbol_guard_abi")&&
                         program.signatures.at("symbol_guard_abi")==vector<Kind>{"sym"}&&
                         atom_truth(evidence,{"symbol_guard_abi",{"v1"}})=="POSITIVE",
                         "CL-authored type profile does not support exact symbolic comparisons");
    if(ratios)require(program.signatures.contains("ratio_abi")&&program.signatures.at("ratio_abi")==vector<Kind>{"sym"}&&
                      atom_truth(evidence,{"ratio_abi",{"v1"}})=="POSITIVE",
                      "CL-authored type profile does not support proportional arithmetic");
    if(folds)require(atom_truth(evidence,{"fold_abi",{"v1"}})=="POSITIVE","CL authored fold ABI has no positive proof");
    if(extended_folds)require(atom_truth(evidence,{"fold_abi",{"v2"}})=="POSITIVE",
                               "CL-authored type profile does not support extended closed folds");
    if(may_convert)require(atom_truth(evidence,{"conversion_abi",{"v1"}})=="POSITIVE",
                           "CL authored conversion ABI has no positive proof");
    vector<tuple<size_t,size_t,string,Atom>> findings;
    for(const auto& [observation,_]:evidence.facts){
        if(observation.pred=="type_error"){
            const auto site=integer(observation.args.at(0));
            require(site>0&&static_cast<uint64_t>(site)<=input.uses.size(),"checker emitted invalid diagnostic occurrence");
            const auto item=input.uses[static_cast<size_t>(site-1)];
            findings.emplace_back(item.clause,item.id,observation.args.at(2),observation);
        }else if(observation.pred=="declaration_error"){
            const auto clause=integer(observation.args.at(0));
            require(clause>0&&std::ranges::any_of(input.signatures,[&](const auto& s){return s.clause==static_cast<uint64_t>(clause);}),
                    "checker emitted invalid diagnostic declaration");
            findings.emplace_back(static_cast<size_t>(clause),0,observation.args.at(1),observation);
        }
    }
    for(const auto& occurrence:input.uses){
        Atom declaration{"known_site",{to_string(occurrence.id)}};
        if(atom_truth(evidence,declaration)!="POSITIVE")
            findings.emplace_back(occurrence.clause,occurrence.id,"relation_missing_proof",declaration);
        if(numeric&&occurrence.role=="body"&&comparison(occurrence.atom.pred)){
            if(quantity_comparison(occurrence.atom.pred)||quantity_calculation(occurrence.atom.pred)){
                Atom support{"quantity_known",{to_string(occurrence.id)}};
                if(atom_truth(evidence,support)!="POSITIVE")
                    findings.emplace_back(occurrence.clause,occurrence.id,"quantity_dimension_missing_proof",support);
            }
            if(fold_calculation(occurrence.atom.pred)){
                Atom support{"fold_known",{to_string(occurrence.id)}};
                if(atom_truth(evidence,support)!="POSITIVE")
                    findings.emplace_back(occurrence.clause,occurrence.id,"sealed_fold_source_missing_proof",support);
            }
            if(unit_conversion(occurrence.atom.pred)){
                Atom support{"conversion_known",{to_string(occurrence.id)}};
                if(atom_truth(evidence,support)!="POSITIVE")
                    findings.emplace_back(occurrence.clause,occurrence.id,"observed_conversion_source_missing_proof",support);
            }
            const auto inputs=(proportional_calculation(occurrence.atom.pred)||unit_conversion(occurrence.atom.pred))?3U:2U;
            for(size_t i=0;i<min<size_t>(inputs,occurrence.atom.args.size());++i){
                const auto& term=occurrence.atom.args[i];
                if(variable(term)){
                    Atom binding{"bound_before",{to_string(occurrence.id),to_string(occurrence.clause),term.substr(1)}};
                    if(atom_truth(evidence,binding)!="POSITIVE")
                        findings.emplace_back(occurrence.clause,occurrence.id,"operator_input_binding_missing_proof",binding);
                }
            }
        }
        if(occurrence.role=="head")
            for(const auto& v:occurrence.atom.args)if(variable(v)){
                Atom bound{"bound_var",{to_string(occurrence.clause),v.substr(1)}};
                if(atom_truth(evidence,bound)!="POSITIVE")
                    findings.emplace_back(occurrence.clause,occurrence.id,"head_binding_missing_proof",bound);
            }
    }
    sort(findings.begin(),findings.end());
    findings.erase(unique(findings.begin(),findings.end()),findings.end());
    require(findings.size()<=128,"type audit diagnostic count limit");
    ostringstream out;
    out<<"{\"schema\":\"cl-authored-type-audit-v1\",\"profile\":"<<quote_json(numeric?"explicit-numeric-v2":"explicit-relations-v1")<<",\"checker_sha256\":"
       <<quote_json(sha256(checker))<<",\"normalized_source_sha256\":"<<quote_json(sha256(canonical))
       <<",\"passed\":"<<(findings.empty()?"true":"false")<<",\"occurrences\":"<<input.uses.size()<<",\"types\":[";
    bool first_type=true;
    for(const auto& [kind,code]:kind_numbers){
        if(!first_type)out<<',';
        first_type=false;
        out<<"{\"id\":"<<code<<",\"kind\":"<<quote_json(type_text(kind))<<'}';
    }
    out<<"],\"diagnostics\":[";
    bool first=true;
    for(const auto& [clause,site,reason,proof]:findings){
        if(!first)out<<',';
        first=false;
        out<<"{\"statement\":"<<clause<<",\"occurrence\":"<<site<<",\"reason\":"<<quote_json(reason)
           <<",\"evidence\":";
        json_fact(out,evidence,proof);
        out<<'}';
    }
    out<<"]}";
    auto text=out.str();
    require(text.size()<=2*1024*1024,"type audit summary size limit");
    return {move(text),findings.empty()};
}
