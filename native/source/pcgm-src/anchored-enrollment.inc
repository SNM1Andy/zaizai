string enroll_anchored_review(StateStore& store,const string& approval,const string& signal,bool agenda=false){
    const auto digest=[](const string& s){return s.size()==64&&hex_chars(s);};
    require(approval.size()<=1024&&digest(signal)&&sha256(approval)==signal,"local question approval pin mismatch");
    istringstream in(approval);
    string schema,actor,head,from,to,review,extra;
    if(agenda){
        require(bool(in>>schema>>actor>>head>>review)&&!(in>>extra)&&approval==agenda_approval(actor,head,review),
                "invalid canonical local agenda approval");
    }else{
        require(bool(in>>schema>>actor>>head>>from>>to>>review)&&!(in>>extra)&&
            schema=="PCGM-LOCAL-OBLIGATION-APPROVAL-1"&&valid_identity(actor)&&digest(head)&&digest(review)&&
            approval==schema+"\n"+actor+"\n"+head+"\n"+from+" "+to+"\n"+review+"\n",
            "invalid canonical local obligation approval");
        for(const auto& name:{from,to}){Parser p{name};require(p.name()==name,"invalid approval route");p.end();}
    }
    string current_head;
    auto current=store.load(&current_head);
    require(current.id==actor&&current.owner==build_name&&current.owner_hash==local_binary_hash()&&
            !current.pending&&current.staged_copy.empty(),"obligation enrollment requires active managed owner");
    const auto result=[&](const string& ticket,const string& result_head,bool retry){
        return "{\"schema\":\"pcgm-local-obligation-enrollment-v1\",\"status\":"+quote_json(retry?"already_enrolled":"enrolled")+
            ",\"actor\":"+quote_json(actor)+",\"head_sha256\":"+quote_json(result_head)+
            ",\"ticket\":"+quote_json(ticket)+",\"review_sha256\":"+quote_json(review)+
            ",\"writes_state\":"+(retry?"false":"true")+",\"asserts_fact\":false,\"outbound\":false}\n";
    };
    if(const auto old=current.obligation_enrollments.find(signal);old!=current.obligation_enrollments.end()){
        const auto& [proof,basis,ticket]=old->second;
        require(proof==review&&basis==head&&current.questions.contains(ticket),"durable obligation approval trace differs");
        return result(ticket,current_head,true);
    }
    require(current_head==head,"local obligation approval is stale");
    optional<pair<Atom,Atom>> selected;
    string recomputed;
    if(agenda){
        const auto scan=discover_agenda(current,head);
        require(scan.limit.empty()&&scan.eligible.size()==1,"agenda no longer has one complete selection");
        selected=scan.choice;
        recomputed=scan.review;
    }else recomputed=anchored_goal_obligation(current,head,from,to,&selected);
    require(selected&&sha256(recomputed)==review,"local approval does not match current grounded review");
    const auto& [goal,need]=*selected;
    const auto old_program=compile_active(current);
    const auto old_facts=run(old_program,current.inactive);
    require(agenda||!old_program.goals.contains(goal),"grounded obligation goal already registered");
    for(const auto& [_,q]:current.questions)require(!matches_question(q,need),"grounded premise already has a question");
    if(!old_program.goals.contains(goal))current.source+="\n? "+show(goal)+".\n";
    const auto next_program=compile_active(current);
    auto goals=old_program.goals;goals.insert(goal);
    const auto next_facts=run(next_program,current.inactive);
    require(goals==next_program.goals&&ranges::equal(old_facts.facts,next_facts.facts,[](const auto& a,const auto& b){
        return a.first==b.first;
    })&&open_gaps(next_program,next_facts).contains({goal,need}),"obligation enrollment would change facts or is no longer open");
    const auto ticket="q"+to_string(current.events.size()+1);
    require(stage_questions(current,{{goal,need}})==1,"obligation enrollment did not stage exactly one question");
    current.questions.at(ticket).agenda=agenda;
    current.events.push_back("obligation_enrolled "+signal+" "+review+" "+head+" "+ticket);
    require(current.obligation_enrollments.emplace(signal,tuple{review,head,ticket}).second,"duplicate obligation enrollment");
    const auto after=sha256(encode(current));
    store.save(current);
    return result(ticket,after,false);
}
