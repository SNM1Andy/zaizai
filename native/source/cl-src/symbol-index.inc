struct ScopeEntry {
    string module,name,visibility,file;
    size_t line;
};
using SymbolScope=map<string,ScopeEntry>;
SymbolScope symbol_scope(const LinkedProject& project){
    SymbolScope scopes;
    for(const auto& [path,unit]:project.units){
        const auto file=path.lexically_relative(project.root.parent_path()).generic_string();
        for(const auto& name:unit.signatures){
            const auto canonical=path==project.root?name:unit.name+"__"+name;
            scopes.emplace(canonical,ScopeEntry{unit.name,name,
                unit.input_names.contains(name)?"input":unit.public_names.contains(name)?"export":"private",file,unit.declaration_lines.at(name)});
        }
    }
    return scopes;
}
SymbolScope local_symbol_scope(const Program& program,const string& file){
    SymbolScope scopes;
    for(const auto& [name,line]:program.signature_lines)scopes.emplace(name,ScopeEntry{"",name,"local",file,line});
    return scopes;
}
string describe_symbols(const Program& program,const SymbolScope& scopes,const string& kind){
    map<string,vector<size_t>> heads;
    map<string,pair<size_t,size_t>> observations;
    map<string,size_t> goals;
    for(size_t i=0;i<program.rules.size();++i)heads[base_name(program.rules[i].head)].push_back(i);
    for(const auto& [_,atom]:program.observations){
        auto& count=observations[base_name(atom)];
        if(atom.pred.starts_with('!'))++count.second;else ++count.first;
    }
    for(const auto& goal:program.goals)++goals[base_name(goal)];
    ostringstream out;
    out<<"{\"schema\":\"cl-symbols-v1\",\"input_kind\":"<<quote_json(kind)<<",\"relations\":[";
    bool first=true;
    for(const auto& [name,arity]:program.arity){
        if(!first)out<<',';
        first=false;
        const auto type=program.signatures.find(name);
        const auto scope=scopes.find(name);
        out<<"{\"symbol\":"<<quote_json(name)<<",\"arity\":"<<arity
           <<",\"scope\":"<<quote_json(scope==scopes.end()?"unknown":scope->second.visibility)<<",\"qualified\":"
           <<(scope==scopes.end()||scope->second.module.empty()?string("null"):quote_json(scope->second.module+"::"+scope->second.name))
           <<",\"signature_explicit\":"<<(type!=program.signatures.end()?"true":"false")<<",\"types\":[";
        for(size_t i=0;i<arity;++i){
            if(i)out<<',';
            out<<quote_json(type==program.signatures.end()?"sym":type_text(type->second[i]));
        }
        out<<"],\"declaration\":";
        if(scope==scopes.end())out<<"null";
        else out<<"{\"file\":"<<quote_json(scope->second.file)<<",\"line\":"<<scope->second.line<<'}';
        const auto [pos,neg]=observations[name];
        out<<",\"observed_positive\":"<<pos<<",\"observed_negative\":"<<neg<<",\"goals\":"<<goals[name]<<",\"rules\":[";
        bool first_rule=true;
        for(const auto index:heads[name]){
            if(!first_rule)out<<',';
            first_rule=false;
            const auto& rule=program.rules[index];
            out<<"{\"ordinal\":"<<index+1<<",\"head_sign\":"<<quote_json(rule.head.pred.starts_with('!')?"negative":"positive")
               <<",\"source_label\":";
            if(!program.rule_labels.empty())out<<quote_json(program.rule_labels.at(index));
            else if(!program.rule_lines.empty())out<<quote_json("line:"+to_string(program.rule_lines.at(index)));
            else out<<"null";
            out<<",\"dependencies\":[";
            bool dependency_first=true;
            for(const auto& step:rule.body){
                if(!dependency_first)out<<',';
                dependency_first=false;
                out<<"{\"symbol\":"<<quote_json(base_name(step))<<",\"arity\":"<<step.args.size()
                   <<",\"sign\":"<<quote_json(step.pred.starts_with('!')?"negative":"positive")
                   <<",\"role\":"<<quote_json(calculation(step.pred)?"calculation":comparison(step.pred)?"condition":"relation")<<'}';
            }
            out<<"]}";
        }
        out<<"]}";
    }
    out<<"]}";
    auto text=out.str();
    require(text.size()<=2*1024*1024,"semantic index exceeds 2 MiB");
    return text;
}
