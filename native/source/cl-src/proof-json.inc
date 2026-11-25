string quote_json(const string& s){
    constexpr char hex[]="0123456789abcdef";
    string out="\"";
    for(size_t i=0;i<s.size();){
        const auto b=static_cast<unsigned char>(s[i]);
        if(b<128){
            ++i;
            if(b=='"'||b=='\\'){out+='\\';out+=static_cast<char>(b);}
            else if(b<32){out+="\\u00";out+=hex[b>>4];out+=hex[b&15];}
            else out+=static_cast<char>(b);
            continue;
        }
        size_t n=b>=0xc2&&b<=0xdf?2:b>=0xe0&&b<=0xef?3:b>=0xf0&&b<=0xf4?4:0;
        bool ok=n&&s.size()-i>=n;
        if(ok){
            const auto next=static_cast<unsigned char>(s[i+1]);
            ok=!(b==0xe0&&next<0xa0)&&!(b==0xed&&next>=0xa0)&&
                !(b==0xf0&&next<0x90)&&!(b==0xf4&&next>=0x90);
            for(size_t k=1;k<n&&ok;++k)ok=(static_cast<unsigned char>(s[i+k])&0xc0U)==0x80U;
        }
        if(ok){out.append(s,i,n);i+=n;}else{out+="\\ufffd";++i;}
    }
    return out+"\"";
}
void json_atom(ostream& out,const Atom& a){
    const bool neg=a.pred.starts_with("!");
    out<<"{\"predicate\":"<<quote_json(neg?a.pred.substr(1):a.pred)
       <<",\"polarity\":\""<<(neg?"negative":"positive")<<"\",\"arguments\":[";
    for(size_t i=0;i<a.args.size();++i){
        const auto& arg=a.args[i];
        if(i)out<<',';
        const bool text=cl_text_symbol::is_wire(arg);
        out<<"{\"type\":"<<quote_json(type_text(literal_type(arg)))<<",\"value\":"
           <<quote_json(text?cl_text_symbol::from_wire(arg):arg);
        if(text)out<<",\"encoding\":\"quoted_utf8\"";
        out<<'}';
    }
    out<<"]}";
}
void json_branch(ostream& out,const Table& table,const Atom& a){
    if(!table.facts.contains(a)){out<<"{\"supported\":false,\"truncated\":false,\"nodes\":[]}";return;}
    vector<Atom> walk{a};set<Atom> enqueued{a};
    ostringstream nodes;
    size_t cursor=0;
    for(;cursor<walk.size()&&cursor<128;++cursor){
        const auto fact=walk[cursor];
        const auto& proof=table.facts.at(fact);
        if(cursor)nodes<<',';
        nodes<<"{\"fact\":";json_atom(nodes,fact);
        nodes<<",\"origin\":"<<quote_json(proof.origin)<<",\"premises\":[";
        bool first=true;
        for(const auto& premise:proof.parents){
            if(!first)nodes<<',';
            first=false;
            json_atom(nodes,premise);
            if(enqueued.insert(premise).second)walk.push_back(premise);
        }
        nodes<<"],\"checks\":[";
        first=true;
        for(const auto& check:proof.checks){
            if(!first)nodes<<',';
            first=false;
            json_atom(nodes,check);
        }
        nodes<<"]}";
    }
    out<<"{\"supported\":true,\"truncated\":"<<(cursor<walk.size()?"true":"false")
       <<",\"nodes\":["<<nodes.str()<<"]}";
}
void json_fact(ostream& out,const Table& t,Atom a){
    auto opposite=a;opposite.pred="!"+a.pred;
    const auto pos=t.facts.contains(a), neg=t.facts.contains(opposite);
    const char* status=pos?(neg?"CONFLICT":"POSITIVE"):(neg?"NEGATIVE":"UNKNOWN");
    out<<"{\"goal\":";json_atom(out,a);out<<",\"status\":"<<quote_json(status)
       <<",\"positive\":";
    json_branch(out,t,a);out<<",\"negative\":";json_branch(out,t,opposite);out<<'}';
}
string json_report(const Table& t,const vector<Atom>& goals,const string& engine,const string& context){
    ostringstream out;
    out<<"{\"schema\":\"cl-proof-v1\",\"engine\":"<<quote_json(engine)
       <<",\"context\":"<<context<<",\"results\":[";
    for(size_t i=0;i<goals.size();++i){if(i)out<<',';json_fact(out,t,goals[i]);}
    out<<"]}";
    return out.str();
}
