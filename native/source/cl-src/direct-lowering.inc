pair<Program,string> direct_lower(const string& source,const string& spec){
    const auto source_terms=audit_collect(source,true);
    string feed;
    set<string> generated;
    auto add=[&](string id,const string& atom){
        require(generated.insert(id).second,"duplicate generated lowering site");
        feed+="& "+id+" "+atom+".\n";
    };
    for(const auto& d:source_terms.signatures){
        const auto number=to_string(d.clause);
        add("lower_decl_"+number,"ldecl("+number+")");
    }
    for(const auto& row:source_terms.uses){
        const auto id=to_string(row.id),clause=to_string(row.clause);
        add("lower_site_"+id,"lsite("+id+","+clause+")");
        add("lower_form_"+id,"lform("+id+","+row.form+")");
    }
    const auto plan=instantiate_stage(spec,feed);
    const map<string,vector<Kind>> abi{
        {"ldecl",{"i64"}},{"lsite",{"i64","i64"}},{"lform",{"i64","sym"}},
        {"emit_declaration",{"i64"}},{"emit_site",{"i64","i64","sym"}}
    };
    for(const auto& [name,types]:abi)
        require(plan.signatures.contains(name)&&plan.signatures.at(name)==types,"lowering spec ABI mismatch in "+name);
    const set<string> managed{"ldecl","lsite","lform"};
    for(const auto& rule:plan.rules)require(!managed.contains(base_name(rule.head)),"lowering spec cannot manufacture input");
    for(const auto& [id,fact]:plan.observations)if(managed.contains(base_name(fact)))
        require(generated.contains(id),"lowering spec cannot supply extra input");
    const auto proofs=run(plan);
    Program program;
    size_t declarations=0,sites=0;
    for(const auto& [fact,_]:proofs.facts){
        if(fact.pred=="emit_declaration")++declarations;
        if(fact.pred=="emit_site")++sites;
    }
    require(declarations==source_terms.signatures.size()&&sites==source_terms.uses.size(),"lowering plan does not cover exact source");
    for(const auto& d:source_terms.signatures){
        require(atom_truth(proofs,{"emit_declaration",{to_string(d.clause)}})=="POSITIVE","declaration lacks a unique plan");
        require(d.types.size()>0&&d.types.size()<=4,"invalid direct signature arity");
        declare(program,{d.name,vector<string>(d.types.size(),"x")});
        require(program.signatures.emplace(d.name,d.types).second,"duplicate direct declaration");
    }
    map<size_t,Rule> rule_bodies;
    for(const auto& row:source_terms.uses){
        const Atom emit{"emit_site",{to_string(row.id),to_string(row.clause),row.form}};
        require(atom_truth(proofs,emit)=="POSITIVE","statement has no exact positive lowering placement");
        if(row.form=="query"){
            require(program.goals.size()<64&&program.goals.insert(row.atom).second,"invalid or duplicate direct goal");
        }else if(row.form=="observation"){
            require(program.observations.size()<4096&&program.observations.emplace(row.label,row.atom).second,
                    "invalid or duplicate direct observation");
        }else if(row.form=="fact"||row.form=="head"){
            require(rule_bodies.size()<512&&rule_bodies.emplace(row.clause,Rule{row.atom,{}}).second,
                    "duplicate or excessive direct rule");
        }else if(row.form=="body"){
            const auto head=rule_bodies.find(row.clause);
            require(head!=rule_bodies.end()&&head->second.body.size()<8,"malformed or excessive body");
            head->second.body.push_back(row.atom);
        }else throw runtime_error("unsupported direct lowering form");
    }
    for(auto& [_,r]:rule_bodies)program.rules.push_back(move(r));
    const auto bytes=to_image(program,{});
    // Keep a separately implemented, native IR reader as an independent closed gate.
    auto decoded=from_image(bytes);
    return {move(decoded.first),bytes};
}
