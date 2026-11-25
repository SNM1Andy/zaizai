bool grammar_letter(unsigned char c){return c>='a'&&c<='z';}
bool grammar_digit(unsigned char c){return c>='0'&&c<='9';}
struct GrammarToken {string kind;size_t begin,end;};
vector<GrammarToken> grammar_tokens(const string& input){
    vector<GrammarToken> result;
    auto add=[&](string item,size_t begin,size_t end){
        require(result.size()<1024,"grammar input token limit");
        result.push_back({std::move(item),begin,end});
    };
    const map<char,string> punctuation{{'(',"op"},{')',"cp"},{',',"comma"},{'.',"dot"},{'?',"ask"},
        {':',"colon"},{'&',"and"},{'!',"bang"},{'$',"var"},{'@',"tag"}};
    for(size_t i=0;i<input.size();){
        const auto c=static_cast<unsigned char>(input[i]);
        if(c==' '||c=='\r'||c=='\t'){++i;continue;}
        if(c=='\n'){add("eol",i,i+1);++i;continue;}
        if(c=='#'){while(i<input.size()&&input[i]!='\n')++i;continue;}
        if(c=='"'){
            const auto first=i;
            // Validate with the same decoder used by typed lowering. There is no
            // fallback to identifiers or punctuation after a malformed quote.
            (void)cl_text_symbol::term(input,i);
            add("quoted_symbol",first,i);
            continue;
        }
        if(grammar_letter(c)){
            const auto first=i++;
            while(i<input.size()&&(grammar_letter(input[i])||grammar_digit(input[i])||input[i]=='_'))++i;
            add(i-first<=48?"name":"invalid",first,i);
            continue;
        }
        if(grammar_digit(c)||(c=='-'&&i+1<input.size()&&grammar_digit(input[i+1]))){
            const auto first=i++;
            while(i<input.size()&&grammar_digit(input[i]))++i;
            auto num=input.substr(first,i-first);
            int64_t n=0;
            const auto end=num.data()+num.size();
            const auto parsed=from_chars(num.data(),end,n);
            add(parsed.ec==errc()&&parsed.ptr==end&&to_string(n)==num?"number":"invalid",first,i);
            continue;
        }
        if(c=='<'&&i+1<input.size()&&input[i+1]=='-'){add("arrow",i,i+2);i+=2;continue;}
        if(c=='='&&i+1<input.size()&&input[i+1]=='>'){add("forward",i,i+2);i+=2;continue;}
        if(const auto k=punctuation.find(static_cast<char>(c));k!=punctuation.end())add(k->second,i,i+1);
        else add("invalid",i,i+1);
        ++i;
    }
    if(result.empty()||result.back().kind!="eol")add("eol",input.size(),input.size());
    return result;
}
struct GrammarInference { vector<GrammarToken> tokens;Table table;string context;bool accepted; };
GrammarInference assess_grammar(const string& grammar,const string& source){
    auto token_kinds=grammar_tokens(source);
    string spec;
    for(size_t i=0;i<token_kinds.size();++i){
        const auto offset=to_string(i);
        spec+="& lex_"+offset+" lex("+offset+","+token_kinds[i].kind+").\n";
        spec+="& step_"+offset+" step("+offset+","+to_string(i+1)+").\n";
    }
    spec+="& source_span span(0,"+to_string(token_kinds.size())+").\n";
    auto program=instantiate_stage(grammar,spec);
    const map<string,vector<Kind>> contract{{"lex",{"i64","sym"}},{"step",{"i64","i64"}},
        {"span",{"i64","i64"}},{"accept",{"sym"}}};
    for(const auto& [name,signature]:contract)
        require(program.signatures.contains(name)&&program.signatures.at(name)==signature,"grammar signature missing for "+name);
    for(const auto& [id,a]:program.observations){
        const auto name=base_name(a);
        if(name=="lex"||name=="step"){
            const auto at=integer(a.args.at(0));
            require(at>=0&&static_cast<uint64_t>(at)<token_kinds.size()&&a.pred==name&&
                id==(name=="lex"?"lex_":"step_")+a.args[0]&&
                a.args[1]==(name=="lex"?token_kinds[static_cast<size_t>(at)].kind:to_string(at+1)),
                "grammar cannot supply extra lexical observations");
        }
        else if(name=="span")require(id=="source_span","grammar cannot supply another source span");
    }
    for(const auto& rule:program.rules){
        const auto name=base_name(rule.head);
        require(name!="lex"&&name!="step"&&name!="span","grammar cannot manufacture lexical input");
    }
    auto table=run(program);
    const Atom goal{"accept",{"unit"}};
    const auto verdict=atom_truth(table,goal);
    const bool accepted=verdict=="POSITIVE";
    const auto context="{\"token_count\":"+to_string(token_kinds.size())+
        ",\"source_sha256\":"+quote_json(sha256(source))+
        ",\"grammar_sha256\":"+quote_json(sha256(grammar))+"}";
    return {std::move(token_kinds),std::move(table),context,accepted};
}
