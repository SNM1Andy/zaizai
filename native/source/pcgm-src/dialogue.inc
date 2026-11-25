struct TurnInput { string sid,tid,action,canonical; optional<Atom> target; string basis_pin; };
TurnInput interpret_turn(const string& input,const Program& program){
    Parser p{input};
    TurnInput q;
    q.sid=p.name();q.tid=p.name();q.action=p.name();
    q.canonical=q.action;
    if(q.action=="focus"){
        auto a=p.atom();
        require(program.goals.contains(a),"conversation target is not a declared goal");
        q.canonical+=" "+show(a);
        q.target=std::move(a);
    }else if(q.action=="outcome"){
        if(p.take("since")){
            q.basis_pin=p.name();
            q.canonical+=" since "+q.basis_pin;
        }
    }else if(q.action=="record"){
        p.ws();string digest=p.s.substr(p.i);p.i=p.s.size();
        require(digest.size()==65&&digest[0]=='h'&&hex_chars(digest.substr(1)),"invalid desktop result hash");
        q.canonical+=" "+digest;
    }else require(q.action=="why"||q.action=="status"||q.action=="need"||q.action=="clear",
                  "unknown dialogue command");
    p.end();
    return q;
}
string make_reply(const TurnInput& q,LocalSession& session,const Program& p,const Table& table,unsigned version){
    if(q.action=="record")return "recorded "+q.canonical.substr(7)+"\n";
    if(q.action=="clear"){
        session.focus.reset();
        return "focus_cleared\n";
    }
    if(q.target)session.focus=q.target;
    if(!session.focus)return "clarify no_focus\n";
    const auto a=*session.focus;
    ostringstream reply;
    reply<<"reply "<<show(a)<<" "<<truth_state(table,a)<<" observation_version="<<version<<'\n';
    if(q.action=="why"){
        explain(table,a,reply);
    }else if(q.action=="need"){
        const auto gaps=open_gaps(p,table);
        size_t found=0;
        for(const auto& [goal,fact]:gaps)if(goal==a){
            if(found>=8){reply<<"more_gaps_truncated\n";break;}
            ++found;reply<<"missing "<<show(fact)<<'\n';
        }
        if(!found)reply<<"no_addressable_gap\n";
    }
    auto bytes=reply.str();
    if(bytes.size()>8000){
        const auto cut=bytes.rfind('\n',7900);
        bytes.resize(cut==string::npos?7900:cut+1);
        bytes+="\nreply_truncated\n";
    }
    return bytes;
}
