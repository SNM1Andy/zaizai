Program instantiate_stage(const string& stage,const string& generated){
    if(!stage.starts_with("CLIR-"))
        return compile(stage+"\n"+generated);
    auto p=from_image(stage).first;
    istringstream facts(generated);
    string line;
    while(getline(facts,line)){
        Parser q{line};q.ws();if(q.i==line.size())continue;
        q.expect("&");const auto id=q.name();
        auto atom=q.atom();q.expect(".");q.end();
        require(std::ranges::none_of(atom.args,variable),"compiler stage input facts must be ground");
        require(p.signatures.contains(base_name(atom)),"compiler stage lacks typed input port");
        map<string,Kind> variables;check_type(p,atom,variables);
        require(p.observations.size()<4096&&p.observations.emplace(id,move(atom)).second,
                "compiler artifact already contains this input or exceeds its bound");
    }
    return p;
}
