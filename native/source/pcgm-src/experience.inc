struct Experience { size_t event; string kind,context,observation; };

map<string,Experience> read_experiences(const Continuity& state){
    map<string,Experience> all;
    for(size_t i=0;i<state.events.size();++i){
        const auto& e=state.events[i];
        if(e.starts_with("decision ")){
            istringstream text(e.substr(9));string kind,target;text>>kind>>target;
            if(kind=="artifact")kind+=":"+target;
            all.emplace("e"+to_string(i+1),Experience{i+1,kind,{},{}}); 
        }else if(e.starts_with("scene ")||e.starts_with("experience ")){
            const bool scene=e.starts_with("scene ");
            Parser q{e.substr(scene?6:11)};const auto id=q.name(), field=q.name();q.end();
            auto& target=all.at(id);
            auto& item=scene?target.context:target.observation;
            require(item.empty(),"duplicated experience field");
            item=field;
        }
    }
    return all;
}
optional<string> experience_context(const Program& p,const Table& table){
    optional<string> found;
    for(const auto& [id,guard]:p.experience_contexts){
        if(proof_without_conflict(table,guard)){
            if(found)return {};
            found=id;
        }
    }
    return found;
}
void record_experience_context(Continuity& state,const Program& p,const Table& facts){
    if(auto context=experience_context(p,facts))
        state.events.push_back("scene e"+to_string(state.events.size())+" "+*context);
}
optional<int> measured_outcome_proof(const Table&,const Atom&,const string&,const string&,const string&);
optional<int> feedback_value(const Continuity& state,const Program& p,const Table& t,
                             const string& id,const Experience& row){
    if(row.observation.empty()||row.context.empty()||state.inactive.contains(row.observation)||
       !p.experience_contexts.contains(row.context))return {};
    const auto actual=p.observations.find(row.observation);
    if(actual==p.observations.end())return {};
    const auto& fact=actual->second;
    if(fact.args.size()!=3||fact.args[0]!=id||fact.args[1]!=row.context)return {};
    if(fact.pred!="outcome"){
        const auto attached=state.measured_from_cycle.find(id);
        if(attached==state.measured_from_cycle.end())return {};
        const auto& [source,sequence,index]=attached->second;
        if(cycle_obs_id(source,sequence,index)!=row.observation||!p.measurement_sources.contains(source)||
           p.measurement_sources.at(source)!=fact.pred)return {};
        const auto currently=measured_outcome_proof(t,fact,row.observation,id,row.context);
        if(currently&&state.measured_strength.at(id)==*currently)return currently;
        return {};
    }
    const bool success=fact.args[2]=="success";
    if(!success&&fact.args[2]!="failure")return {};
    if(!proof_without_conflict(t,fact)||t.facts.contains({"outcome",{id,row.context,success?"failure":"success"}}))return {};
    bool newer=false;
    for(size_t i=row.event;i<state.events.size();++i){
        if(state.events[i]=="observe "+row.observation){newer=true;break;}
        if(state.events[i].starts_with("answer ")){
            const auto last=state.events[i].rfind(' ');
            if(state.events[i].substr(last+1)==row.observation){newer=true;break;}
        }
    }
    if(!newer)return {};
    return success?1:-1;
}
int memory_value(const Continuity& state,const Program& p,const Table& table,
                 const string& option,const optional<string>& context,const map<string,Experience>& all){
    if(!context)return 0;
    int score=0;
    for(const auto& [id,row]:all){
        if(row.kind==option&&row.context==*context)
            if(const auto evidence=feedback_value(state,p,table,id,row))score+=*evidence;
    }
    return clamp(score,-4,4);
}

size_t bind_observed_feedback(Continuity& state,const Program& p,const Table& table,
                             const string& source,unsigned sequence,const vector<Atom>& facts){
    if(!p.feedback_sources.contains(source))return 0;
    auto memory=read_experiences(state);
    auto linked=count_if(memory.begin(),memory.end(),[](const auto& row){return !row.second.observation.empty();});
    size_t count=0;
    for(size_t i=0;i<facts.size()&&linked<128;++i){
        const auto& fact=facts[i];
        if(fact.pred!="outcome"||fact.args.size()!=3)continue;
        const auto& event=fact.args[0];
        const auto known=memory.find(event);
        if(known==memory.end()||!known->second.observation.empty()||known->second.context!=fact.args[1])continue;
        if(count_if(facts.begin(),facts.end(),[&](const Atom& row){
            return row.pred=="outcome"&&!row.args.empty()&&row.args.front()==event;
        })!=1)continue;
        auto candidate=known->second;
        const auto id=cycle_obs_id(source,sequence,static_cast<unsigned>(i+1));
        candidate.observation=id;
        if(!feedback_value(state,p,table,event,candidate))continue;
        state.events.push_back("experience "+event+" "+id);
        state.events.push_back("experience_wire "+event+" "+source+" "+to_string(sequence)+" "+to_string(i+1));
        known->second.observation=id;
        ++linked;++count;
    }
    return count;
}

string outcome_request_pin(const Continuity& state,const string& source,const string& id,const Experience& experience,
                           const string& shape="outcome(sym,sym,success_or_failure)"){
    const auto& event=state.events.at(experience.event-1);
    return sha256("PCGM-OUTCOME-REQUEST-1\n"+state.id+"\n"+source+"\n"+id+"\n"+event+"\n"+experience.context+
                  "\n"+shape+"\n");
}
void require_pinned_outcome_packet(const Continuity& state,const Program& program,const SensorPacket& packet){
    require(program.pinned_feedback_sources.contains(packet.source),"source cannot reply to pinned outcome requests");
    const auto memory=read_experiences(state);
    set<string> seen;
    for(size_t i=0;i<packet.facts.size();++i){
        const auto& fact=packet.facts[i];
        require(fact.pred=="outcome"&&fact.args.size()==3&&(fact.args[2]=="success"||fact.args[2]=="failure"),
                "pinned outcome reply has the wrong result shape");
        const auto& decision=fact.args[0];
        const auto found=memory.find(decision);
        require(found!=memory.end()&&!found->second.context.empty()&&found->second.context==fact.args[1]&&
                program.experience_contexts.contains(found->second.context)&&found->second.observation.empty()&&
                seen.insert(decision).second,"pinned outcome request is absent, settled, duplicate, or differently scoped");
        const auto expected="review:1:outcome@"+outcome_request_pin(state,packet.source,decision,found->second);
        require(packet.origins.at(i)==expected,"pinned outcome request address did not match");
    }
}

// A measured assessment must depend on this original recorded raw observation,
// not on a numerically equal observation from a different source or time.
optional<int> measured_outcome_proof(const Table& table,const Atom& sample,const string& observation_id,
                                     const string& decision,const string& context){
    if(sample.args.size()<2||sample.args[0]!=decision||sample.args[1]!=context)return {};
    optional<int> result;
    for(const bool successful:{true,false}){
        const Atom outcome{"measured_outcome",{decision,context,successful?"success":"failure"}};
        const auto proof=table.facts.find(outcome);
        if(proof==table.facts.end())continue;
        if(!proof->second.origin.starts_with("r")||proof->second.parents.empty()||
           !proof_without_conflict(table,outcome)||result)return {};
        set<Atom> checked;vector<Atom> pending{outcome};bool anchored=false;
        const auto anchor="obs:"+observation_id;
        for(size_t i=0;i<pending.size();++i){
            const auto value=pending[i];
            if(!checked.insert(value).second)continue;
            if(checked.size()>512)return {};
            const auto point=table.facts.find(value);
            if(point==table.facts.end())return {};
            if(value==sample&&(point->second.origin==anchor||point->second.origin.starts_with(anchor+"@")))anchored=true;
            for(const auto& before:point->second.parents){
                if(!checked.contains(before))pending.push_back(before);
                if(pending.size()>4096)return {};
            }
        }
        if(!anchored)return {};
        result=successful?1:-1;
    }
    return result;
}


string measure_shape(const Program& program,const string& publisher){
    const auto& relation=program.measurement_sources.at(publisher);
    return relation+"(sym,sym,"+program.signatures.at(relation).at(2)+")";
}
void require_measurement_packet(const Continuity& state,const Program& program,const SensorPacket& packet){
    const auto memory=read_experiences(state);
    set<string> seen;
    const auto shape=measure_shape(program,packet.source);
    for(size_t i=0;i<packet.facts.size();++i){
        const auto& fact=packet.facts.at(i);
        require(fact.pred==program.measurement_sources.at(packet.source)&&fact.args.size()==3&&
                literal_type(fact.args.at(2))==program.signatures.at(fact.pred).at(2),
                "measurement does not match the authorized typed relation");
        const auto& decision=fact.args.at(0);
        const auto found=memory.find(decision);
        require(found!=memory.end()&&!found->second.context.empty()&&found->second.context==fact.args.at(1)&&
                program.experience_contexts.contains(found->second.context)&&found->second.observation.empty()&&
                seen.insert(decision).second,"measurement request absent, already settled, duplicate, or differently scoped");
        const auto pin=outcome_request_pin(state,packet.source,decision,found->second,shape);
        require(packet.origins.at(i)=="review:1:measurement@"+pin,"measurement does not match its original request address");
    }
}
void publish_episode(const StateStore&,const string&,const string&);
void bind_measured_feedback(Continuity& state,const Program& program,const Table& table,const SensorPacket& packet,
                            const StateStore& store){
    require(program.measurement_sources.contains(packet.source),"measurement binding without authorized policy");
    auto memory=read_experiences(state);
    auto linked=count_if(memory.begin(),memory.end(),[](const auto& item){return !item.second.observation.empty();});
    if(state.measurement_bases.size()>=32)return;
    const auto n=static_cast<unsigned>(state.events.size());
    string digest;
    for(size_t i=0;i<packet.facts.size()&&linked<128&&state.measurement_bases.size()<32;++i){
        const auto& fact=packet.facts[i];
        const auto& decision=fact.args.at(0);
        const auto context=fact.args.at(1);
        const auto index=static_cast<unsigned>(i+1);
        const auto id=cycle_obs_id(packet.source,packet.sequence,index);
        auto& record=memory.at(decision);
        if(!record.observation.empty())continue;
        const auto assessed=measured_outcome_proof(table,fact,id,decision,context);
        if(!assessed)continue;
        if(digest.empty()){
            const auto basis=encode(state);
            digest=sha256(basis);
            publish_episode(store,digest,basis);
        }
        record.observation=id;
        state.events.push_back("experience "+decision+" "+id);
        state.events.push_back("experience_measured "+decision+" "+packet.source+" "+to_string(packet.sequence)+" "+to_string(index)+
                               (*assessed>0?" success":" failure"));
        state.measured_strength.emplace(decision,*assessed);
        state.measured_from_cycle.emplace(decision,make_tuple(packet.source,packet.sequence,index));
        state.measurement_bases.emplace(decision,Pin{digest,n});
        state.events.push_back("measurement_basis "+decision+" "+digest+" "+to_string(n));
        ++linked;
    }
}
