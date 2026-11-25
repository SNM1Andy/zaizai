struct AtomRow{
    optional<Atom> predicate;
    map<unsigned,Atom> arguments;
};
string render_multivariable(const Program& p,const Table& table){
    if(p.multi_policy.empty())return {};
    map<string,map<unsigned,AtomRow>> records;
    for(const auto& [meta,proof]:table.facts){
        if(meta.pred!="ir_atom"&&meta.pred!="ir_arg")continue;
        require(proof.origin.starts_with("r")&&!proof.parents.empty()&&proof_without_conflict(table,meta),
                "unproved or conflicted multivariable IR: "+show(meta));
        auto& rec=records[meta.args[0]];
        require(records.size()<=16,"multivariable rule count limit");
        const auto line=sequence_number(meta.args[1]);
        require(line<=8,"multivariable atom index must be 0..8");
        auto& row=rec[line];
        if(meta.pred=="ir_atom"){
            require(!row.predicate,"ambiguous IR predicate");
            row.predicate=meta;
        }else{
            const auto slot=sequence_number(meta.args[2]);
            require(slot>=1&&slot<=4&&row.arguments.emplace(slot,meta).second,"invalid or duplicate IR argument");
        }
    }
    set<Rule> dedup;
    string patch;
    for(const auto& [id,rows]:records){
        require(rows.size()>=2&&rows.contains(0)&&rows.at(0).predicate,"incomplete multivariable rule: "+id);
        const auto& head=rows.at(0).predicate->args[2];
        require(p.multi_policy.contains(head),"multivariable output outside authorization: "+head);
        unsigned position=0;
        Rule new_rule;
        string witness;
        for(const auto& [n,row]:rows){
            require(n==position++&&row.predicate.has_value(),"IR atom order or predicate missing");
            const auto& predicate=row.predicate->args[2];
            if(n>0)require(p.multi_policy.at(head).contains(predicate),"multivariable premise outside authorization: "+predicate);
            const auto slots=p.signatures.at(predicate).size();
            require(row.arguments.size()==slots,"IR argument count disagrees with signature");
            Atom atom{predicate,{}};
            unsigned expected=1;
            witness+="# CL join IR "+show(*row.predicate)+" <= "+describe(table.facts.at(*row.predicate))+"\n";
            for(const auto& [slot,arg]:row.arguments){
                require(slot==expected++,"IR argument positions must be consecutive");
                atom.args.push_back("$"+arg.args[3]);
                witness+="# CL join IR "+show(arg)+" <= "+describe(table.facts.at(arg))+"\n";
            }
            if(n==0)new_rule.head=std::move(atom);
            else new_rule.body.push_back(std::move(atom));
        }
        if(find(p.rules.begin(),p.rules.end(),new_rule)!=p.rules.end()||!dedup.insert(new_rule).second)continue;
        patch+=witness+show(new_rule.head)+" <- ";
        for(size_t i=0;i<new_rule.body.size();++i)patch+=(i?" & ":"")+show(new_rule.body[i]);
        patch+=".\n";
    }
    return patch;
}
