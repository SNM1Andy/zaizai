struct PublicEntry {
    string direction;
    vector<Kind> types;
    auto operator<=>(const PublicEntry&) const = default;
};
using PublicApi=map<pair<string,string>,PublicEntry>;
string api_type_list(const vector<Kind>& types){
    string s;
    for(size_t i=0;i<types.size();++i){if(i)s+=",";s+=type_text(types[i]);}
    return s;
}
PublicApi public_api(const LinkedProject& project,const Program& program){
    PublicApi result;
    for(const auto& [path,unit]:project.units){
        for(const auto& name:unit.public_names){
            const auto merged=(path==project.root?name:unit.name+"__"+name);
            result.emplace(make_pair(unit.name,name),
                  PublicEntry{unit.input_names.contains(name)?"input":"output",program.signatures.at(merged)});
        }
    }
    return result;
}
string api_text(const PublicApi& api){
    string out="CL-API-1\n";
    for(const auto& [name,entry]:api)
        out+=name.first+"::"+name.second+" "+entry.direction+" ("+api_type_list(entry.types)+")\n";
    return out;
}
PublicApi parse_api(const string& bytes){
    istringstream in(bytes);
    string line;
    require(getline(in,line)&&line=="CL-API-1","expected CL-API-1");
    PublicApi parsed;
    while(getline(in,line)){
        require(parsed.size()<1024,"public API entry limit");
        Parser p{line};
        const auto module=p.name();p.expect("::");const auto name=p.name();
        require(valid_module(module)&&name.find("__")==string::npos,"invalid public API name");
        auto direction=p.name();
        require(direction=="input"||direction=="output","invalid public API direction");
        vector<Kind> types;
        p.expect("(");
        do {
            auto kind=p.name();
            if(kind=="qty"){p.expect("(");auto unit=p.name();p.expect(")");kind+=":"+unit;}
            else require(kind=="sym"||kind=="i64","invalid public API type");
            require(types.size()<4,"public API arity limit");
            types.push_back(move(kind));
        }while(p.take(","));
        p.expect(")");p.end();
        require(parsed.emplace(make_pair(module,name),PublicEntry{move(direction),move(types)}).second,"duplicate public API symbol");
    }
    require(api_text(parsed)==bytes,"noncanonical public API");
    return parsed;
}
bool compatible_api(const PublicApi& prior,const PublicApi& next,ostream& out){
    size_t broken=0,added=0;
    for(const auto& [id,entry]:prior){
        const auto it=next.find(id);
        if(it==next.end()){
            out<<"removed "<<id.first<<"::"<<id.second<<'\n';++broken;
        }else if(it->second!=entry){
            out<<"changed "<<id.first<<"::"<<id.second<<' '<<entry.direction<<" ("<<api_type_list(entry.types)
               <<") -> "<<it->second.direction<<" ("<<api_type_list(it->second.types)<<")\n";++broken;
        }
    }
    for(const auto& [id,_]:next)if(!prior.contains(id)){
        out<<"added "<<id.first<<"::"<<id.second<<'\n';++added;
    }
    out<<(broken?"api_incompatible":"api_compatible")<<" breaking="<<broken<<" additions="<<added<<'\n';
    return !broken;
}
