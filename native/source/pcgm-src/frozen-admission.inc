string exact_frozen_observation_id(const string& actor,const string& ticket,const string& request,
                                   const string& artifact,const string& package,const string& snapshot,const string& proof){
    return "bundle_"+sha256("PCGM-FROZEN-ADMIT-1\n"+actor+"\n"+ticket+"\n"+request+
                                   "\n"+artifact+"\n"+package+"\n"+snapshot+"\n"+proof+"\n").substr(0,24);
}
struct FrozenAdmission {string id;bool committed;};
FrozenAdmission admit_frozen_exact(StateStore& store,Continuity& state,Program& epoch,Table& table,
                                   const string& ticket,const string& request,const string& member,
                                   const string& artifact,const string& package,const string& snapshot,const string& proof){
    for(const auto& digest:{request,artifact,package,snapshot,proof})
        require(digest.size()==64&&hex_chars(digest),"frozen CL import needs exact SHA-256 pins");
    Parser name{member};require(name.name()==member&&member.size()<=48,"invalid frozen evidence inbox name");name.end();
    const auto q=state.questions.find(ticket);
    require(q!=state.questions.end(),"unknown question");
    const auto id=exact_frozen_observation_id(state.id,ticket,request,artifact,package,snapshot,proof);
    if(state.frozen_receipts.contains(id)){
        const auto& old=state.frozen_receipts.at(id);
        const auto& match=state.bundle_receipts.at(id);
        require(old.first==artifact&&old.second==snapshot&&match.ticket==ticket&&match.request==request&&
                match.package==package&&match.proof==proof,"frozen CL receipt identity differs");
        return {id,false};
    }
    require(!epoch.observations.contains(id),"frozen CL evidence observation ID already exists");
    const auto status=question_status(q->second,table,open_gaps(epoch,table),state,&epoch);
    require(status=="open"&&question_pin(state,ticket,q->second,status,&epoch,&table)==request,
            "frozen proof question has a stale request address");
    const auto raw=native_os::read_confined_component(store.dst.parent_path()/"incoming",member+".clef",5*1024*1024,{
        "cannot open frozen CL evidence inbox","cannot open local frozen CL evidence","frozen CL evidence is not regular",
        "cannot read local frozen CL evidence","frozen CL evidence exceeds size limit"});
    const auto result=cl_native::offline_frozen_single_goal(raw,artifact,package,snapshot,show(q->second.fact)+"\n");
    require(sha256(result.receipt)==proof,"frozen CL answer does not match reviewed proof");
    require(result.sign==cl_native::EvidenceSign::Positive||result.sign==cl_native::EvidenceSign::Negative,
            "PCGM cannot admit unknown or conflicted frozen CL evidence");
    const auto fact=result.sign==cl_native::EvidenceSign::Positive?q->second.fact:opposite_of(q->second.fact);
    auto staged=state;
    staged.source+="\n& "+id+" "+show(fact)+".\n";
    auto next_epoch=compile_active(staged);auto next_table=run(next_epoch,staged.inactive);
    staged.events.push_back("answer "+ticket+" "+id);
    staged.events.push_back("answer_bundle "+ticket+" "+id+" "+request+" "+package+" "+proof);
    staged.events.push_back("answer_frozen "+id+" "+artifact+" "+snapshot);
    staged.recorded_observations.insert(id);
    staged.receipt_question.emplace(id,ticket);
    staged.bundle_receipts.emplace(id,BundleReceipt{ticket,request,package,proof});
    staged.frozen_receipts.emplace(id,make_pair(artifact,snapshot));
    ++staged.observation_version;
    add_notices(staged,table,next_table);
    store.save(staged);state=std::move(staged);epoch=std::move(next_epoch);table=std::move(next_table);
    return {id,true};
}
