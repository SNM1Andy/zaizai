/* Small compositional numeric input, not a natural-language model or reply template.
 * Evaluate the relation with an unbound result; the front end never computes the sum. */
optional<pair<unsigned,unsigned>> parse_quantity_question(string_view s){
    auto trim=[&]{while(!s.empty()&&(s.front()==' '||s.front()=='\t'))s.remove_prefix(1);};
    auto eat=[&](string_view token){trim();if(!s.starts_with(token))return false;s.remove_prefix(token.size());return true;};
    auto digit=[&]()->optional<unsigned>{
        const array<string_view,10> digits={"零","一","二","三","四","五","六","七","八","九"};
        for(unsigned i=0;i<digits.size();++i)
            if(eat(digits[i]))return i;
        if(eat("〇"))return 0;
        if(eat("两"))return 2;
        return {};
    };
    auto number=[&]()->optional<unsigned>{
        trim();
        if(!s.empty()&&s.front()>='0'&&s.front()<='9'){
            const auto n=s.find_first_not_of("0123456789");
            const auto word=s.substr(0,n);
            if(word.size()>6)return {};
            unsigned v=0;const auto result=from_chars(word.data(),word.data()+word.size(),v);
            if(result.ec!=errc())return {};
            s.remove_prefix(word.size());return v;
        }
        const auto first=digit();
        if(eat("十")){
            if(first&&*first==0)return {};
            const auto last=digit();
            if(last&&*last==0)return {};
            return first.value_or(1)*10+last.value_or(0);
        }
        return first;
    };
    if(eat("小洛")&&!(eat("，")||eat(",")))return {};
    const auto first=number();
    if(!first||!(eat("加上")||eat("加")||eat("+")||eat("＋")))return {};
    const auto second=number();
    if(!second)return {};
    const bool equality=eat("等于")||eat("=")||eat("＝");
    const bool unknown=eat("多少")||eat("几");
    trim();
    if(!unknown&&(!equality||!(s.starts_with("?")||s.starts_with("？"))))return {};
    while(eat("?")||eat("？")||eat("。")||eat("/")){}
    trim();
    if(!s.empty())return {};
    return pair{*first,*second};
}
int quantity_question_channel(){
    cout<<unitbuf;
    string line;bool overflow=false;
    while(request_line(cin,line,overflow)){
        const auto parsed=overflow?nullopt:parse_quantity_question(line);
        if(!parsed){
            cout<<"{\"schema\":\"pcgm-quantity-question-v1\",\"status\":\"unparsed\",\"value\":null,\"writes_state\":false}\n";
            continue;
        }
        const auto [a,b]=*parsed;
        const auto program=compile(
            ": left(qty(item)).\n: right(qty(item)).\n: total(qty(item)).\n"
            "& expression_left left("+to_string(a)+"@item).\n& expression_right right("+to_string(b)+"@item).\n"
            "total($out) <- left($a) & right($b) & qty_add($a,$b,$out).\n");
        const auto result=run(program);
        optional<Atom> only;
        for(const auto& [fact,_]:result.facts)
            if(fact.pred=="total"){require(!only,"arithmetic produced multiple results");only=fact;}
        require(only&&only->args.size()==1&&proof_without_conflict(result,*only),"arithmetic has no unambiguous proof");
        const auto exact=only->args[0];const auto sep=exact.find('@');
        require(sep!=string::npos,"arithmetic result lacked its unit");
        cout<<"{\"schema\":\"pcgm-quantity-question-v1\",\"status\":\"solved\",\"value\":"
            <<integer(exact.substr(0,sep))<<",\"proof\":";
        json_fact(cout,result,*only);
        cout<<",\"writes_state\":false}\n";
    }
    return 0;
}
