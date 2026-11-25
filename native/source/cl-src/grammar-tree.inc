pair<size_t,size_t> grammar_span(const Atom& a,size_t tokens){
    require(a.args.size()==2,"grammar parse span must have two fields");
    const auto start=integer(a.args[0]),end=integer(a.args[1]);
    require(start>=0&&end>start&&static_cast<uint64_t>(end)<=tokens,"invalid grammar parse span");
    return {static_cast<size_t>(start),static_cast<size_t>(end)};
}
vector<Atom> grammar_walk(const Table& table,const Atom& root){
    set<Atom> seen{root};
    vector<Atom> todo{root};
    for(size_t i=0;i<todo.size();++i){
        for(const auto& child:table.facts.at(todo[i]).parents){
            if(!seen.insert(child).second)continue;
            todo.push_back(child);
            require(todo.size()<=4096,"grammar tree proof traversal limit");
        }
    }
    return todo;
}
string render_grammar_tree(const string& source,const GrammarInference& parsed){
    const auto& tokens=parsed.tokens;
    const auto& table=parsed.table;
    const auto total=tokens.size();
    map<size_t,Atom> rows;
    for(const auto& item:grammar_walk(table,{"accept",{"unit"}}))
        if(item.pred=="source_line"){
            const auto [first,last]=grammar_span(item,total);
            require(rows.emplace(first,item).second,"ambiguous source line span");
        }
    vector<size_t> line_starts{0};
    for(size_t i=0;i<source.size();++i)if(source[i]=='\n')line_starts.push_back(i+1);
    auto render_span=[&](ostream& out,size_t a,size_t b){
        const auto start=tokens[a].begin,end=tokens[b-1].end;
        const auto line=upper_bound(line_starts.begin(),line_starts.end(),start)-line_starts.begin();
        out<<"{\"tokens\":["<<a<<','<<b<<"],\"bytes\":["<<start<<','<<end<<"],\"line\":"<<line
           <<",\"column\":"<<(start-line_starts.at(line-1)+1)<<'}';
    };
    ostringstream out;
    out<<"{\"schema\":\"cl-grammar-tree-v1\",\"context\":"<<parsed.context<<",\"statements\":[";
    bool first=true;
    size_t cursor=0;
    for(const auto& [start,row]:rows){
        const auto [a,b]=grammar_span(row,total);
        require(a==cursor,"grammar acceptance lacks contiguous source coverage");
        cursor=b;
        optional<Atom> statement;
        for(const auto& parent:table.facts.at(row).parents)
            if(parent.pred=="statement"){
                require(!statement,"ambiguous marked statement");
                statement=parent;
            }
        if(!statement){
            require(b==a+1&&tokens[a].kind=="eol","grammar did not capture a statement");
            continue;
        }
        const auto [from,stop]=grammar_span(*statement,total);
        require(from==a&&stop+2==b&&tokens[stop].kind=="dot"&&tokens[b-1].kind=="eol","grammar has invalid statement coverage");
        const auto& kinds=table.facts.at(*statement).parents;
        require(kinds.size()==1&&(kinds[0].pred=="declaration"||kinds[0].pred=="observation"||
                kinds[0].pred=="question"||kinds[0].pred=="production"),"grammar gives no unique statement type");
        string kind=kinds[0].pred;
        if(kind=="production"){
            const auto& parents=table.facts.at(kinds[0]).parents;
            kind=std::ranges::any_of(parents,[](const auto& p){return p.pred=="conditions";})?"rule":"fact";
        }
        if(!first)out<<',';
        first=false;
        out<<"{\"kind\":"<<quote_json(kind)<<",\"span\":";
        render_span(out,a,b-1);
        out<<",\"literals\":[";
        map<pair<size_t,size_t>,string> selected;
        for(const auto& node:grammar_walk(table,*statement)){
            if(node.pred!="literal"&&node.pred!="atom")continue;
            const auto [l,r]=grammar_span(node,total);
            require(l>=a&&r<=stop,"literal outside statement bounds");
            if(node.pred=="literal")selected[{l,r}]=tokens[l].kind=="bang"?"negative":"positive";
            else if(kind=="question")selected[{l,r}]="positive";
        }
        bool first_literal=true;
        for(const auto& [range,sign]:selected){
            if(!first_literal)out<<',';
            first_literal=false;
            out<<"{\"sign\":"<<quote_json(sign)<<",\"span\":";
            render_span(out,range.first,range.second);
            out<<'}';
        }
        out<<"]}";
    }
    require(cursor==total,"grammar acceptance has no complete structural proof");
    out<<"]}";
    return out.str();
}

string lower_grammar_source(const string& source,const GrammarInference& parsed){
    // The recognized spans must account for the entire lexical input first.
    (void)render_grammar_tree(source,parsed);
    const auto& tokens=parsed.tokens;
    const auto& table=parsed.table;
    const auto total=tokens.size();
    auto piece=[&](const Atom& span){
        const auto [a,b]=grammar_span(span,total);
        return source.substr(tokens[a].begin,tokens[b-1].end-tokens[a].begin);
    };
    map<size_t,Atom> statements;
    for(const auto& node:grammar_walk(table,{"accept",{"unit"}}))
        if(node.pred=="source_line")
            for(const auto& parent:table.facts.at(node).parents)if(parent.pred=="statement")
                require(statements.emplace(grammar_span(parent,total).first,parent).second,"multiple statements at one source span");
    string lowered;
    for(const auto& [_,statement]:statements){
        const auto parsed_as=table.facts.at(statement).parents.at(0);
        if(parsed_as.pred!="production"){
            lowered+=piece(statement)+".\n";continue;
        }
        optional<Atom> head,body;
        for(const auto& v:table.facts.at(parsed_as).parents){
            if(v.pred=="literal"){require(!head,"multiple grammar-selected heads");head=v;}
            if(v.pred=="conditions"){require(!body,"multiple grammar-selected condition groups");body=v;}
        }
        require(head.has_value(),"grammar selected no literal for rule head");
        lowered+=piece(*head);
        if(body){
            lowered+=" <- ";
            map<size_t,Atom> literals;
            const auto [b1,b2]=grammar_span(*body,total);
            for(const auto& literal:grammar_walk(table,*body))if(literal.pred=="literal"){
                const auto [a,b]=grammar_span(literal,total);
                require(a>=b1&&b<=b2&&literals.emplace(a,literal).second,
                        "overlapping or conflicting grammar body");
            }
            require(!literals.empty(),"grammar selected an empty rule body");
            bool first=true;
            size_t end=b1;
            for(const auto& [a,v]:literals){
                require(a>=end,"grammar selected overlapping body literals");
                end=grammar_span(v,total).second;
                if(!first)lowered+=" & ";
                lowered+=piece(v);first=false;
            }
        }
        lowered+=".\n";
    }
    return lowered;
}

string normalize_line_local(const string& grammar,const string& source){
    // This explicit mode is for line-local grammars only; it does not reinterpret
    // grammars whose acceptance conditions span the whole file.
    istringstream input(source);string page,line,lowered;
    size_t lines=0,segment_count=0;
    auto flush=[&](){
        require(++segment_count<=128,"segmented grammar source exceeds 128 windows");
        const auto parsed=assess_grammar(grammar,page);
        require(parsed.accepted,"grammar rejected source segment "+to_string(segment_count));
        lowered+=lower_grammar_source(page,parsed);
        require(lowered.size()<=256*1024,"segmented normalized source size limit");
        page.clear();lines=0;
    };
    while(getline(input,line)){
        page+=line+"\n";
        if(++lines==8)flush();
    }
    if(lines||segment_count==0)flush();
    return lowered;
}
