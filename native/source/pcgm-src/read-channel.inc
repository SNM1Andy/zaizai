string channel_context(const Continuity& s){
    return "{\"individual\":"+quote_json(s.id)+",\"event\":"+to_string(s.events.size())+
           ",\"epoch\":"+to_string(s.epoch)+",\"observation_version\":"+to_string(s.observation_version)+"}";
}
string channel_status(const Continuity& s){
    return "{\"state\":"+channel_context(s)+",\"owner\":"+
        (s.owner.empty()?string("null"):quote_json(s.owner))+
        ",\"handoff_pending\":"+(s.pending?"true":"false")+
        ",\"restore_staged\":"+(s.staged_copy.empty()?"false":"true")+"}";
}
unsigned request_sequence(Parser& p){
    p.ws();const auto start=p.i;
    while(p.i<p.s.size()&&p.s[p.i]>='0'&&p.s[p.i]<='9')++p.i;
    return sequence_number(p.s.substr(start,p.i-start));
}
string request_digest(Parser& p){
    p.ws();
    if(p.take("*")) { require(p.i<p.s.size()&&(p.s[p.i]==' '||p.s[p.i]=='\t'),"expected separator after *"); return {}; }
    require(p.i+64<=p.s.size(),"expected revision SHA-256 or *");
    auto digest=p.s.substr(p.i,64);
    require(all_of(digest.begin(),digest.end(),[](char c){
        return (c>='0'&&c<='9')||(c>='a'&&c<='f');
    }),"expected revision SHA-256 or *");
    p.i+=64;
    require(p.i<p.s.size()&&(p.s[p.i]==' '||p.s[p.i]=='\t'),"expected separator after revision SHA-256");
    return digest;
}
#include "read-chronicle.inc"
#include "reasoned-outcome.inc"
#include "read-review.inc"
#include "goal-obligation.inc"
#include "anchored-goal-obligation.inc"
#include "work-agenda.inc"
bool request_line(istream& in,string& out,bool& overflow){
    out.clear();overflow=false;bool any=false;char c;size_t bytes=0;
    while(in.get(c)){
        any=true;
        require(++bytes<=65536,"read frame exceeds absolute transport limit");
        if(c=='\n')return true;
        if(out.size()<512)out+=c;
        else overflow=true;
    }
    return any;
}
int read_channel(const fs::path& state_path,istream& input=cin,ostream& output=cout,const string& fixed_identity={}){
    const auto path=fs::absolute(state_path);
    StateStore reader(fs::canonical(path.parent_path())/path.filename(),false);
    const auto individual=reader.load().id;
    require(fixed_identity.empty()||fixed_identity==individual,"state identity differs from the bound read service");
    output<<std::unitbuf;
    string cached_digest;
    optional<Program> program;
    optional<Table> table;
    string line;
    bool overflow=false;
    while(output&&request_line(input,line,overflow)){
        string id;
        try{
            require(!overflow,"request line exceeds 512 bytes");
            Parser p{line};
            id=p.name();
            const auto op=p.name();
            require(op=="reasoned_outcome"||op=="agenda"||op=="anchored_obligation"||op=="obligation"||op=="status"||op=="proof"||op=="notices"||op=="inspect"||op=="decision"||op=="fingerprint"||op=="packages"||op=="slice"||op=="batch"||op=="generated"||op=="historical"||op=="timeline"||op=="archives"||op=="storage"||op=="storage_fresh"||op=="review"||op=="pinned_review"||op=="question"||op=="question_feed"||op=="choice_receipt"||op=="choice_intent"||op=="choice_basis"||op=="choice_option"||(op=="choice_reassess"||op=="choice_attribution")||op=="sensor_receipt"||op=="observation_batch"||op=="observation_batch_audit"||op=="workspace_proof"||op=="workspace_growth"||op=="learned_outcome"||op=="outcome_requests"||op=="measurement_history","unknown read operation");
            string digest;
            if(op=="storage_fresh")reader.archive_cache.clear();
            const auto s=reader.load((op=="reasoned_outcome"||op=="agenda"||op=="anchored_obligation"||op=="obligation"||op=="inspect"||op=="proof"||op=="fingerprint"||op=="slice"||op=="batch"||op=="storage"||op=="storage_fresh"||op=="review"||op=="question"||op=="question_feed"||op=="choice_basis"||(op=="choice_reassess"||op=="choice_attribution"))?&digest:nullptr);
            require(s.id==individual,"state identity changed; restart read channel explicitly");
            string payload;
            if(op=="status"){
                p.end();
                payload=channel_status(s);
            }else if(op=="agenda"){
                p.end();payload=discover_agenda(s,digest).json(s,digest);
            }else if(op=="anchored_obligation"){
                const auto revision=request_digest(p);
                require(!revision.empty()&&revision==digest,"anchored obligation revision no longer current");
                const auto from=p.name(),to=p.name();p.end();
                payload=anchored_goal_obligation(s,digest,from,to);
            }else if(op=="obligation"){
                const auto revision=request_digest(p);
                require(!revision.empty()&&revision==digest,"obligation revision no longer current");
                const auto goal=p.atom();p.end();
                payload=goal_obligation(s,digest,goal);
            }else if(op=="reasoned_outcome"){
                const auto case_id=p.name();const auto goal=p.atom();
                const auto basis=p.take("since")?p.name():string{};
                p.end();
                if(digest!=cached_digest){program=compile_active(s);table.reset();cached_digest=digest;}
                if(!table)table=run(*program,s.inactive);
                payload=reasoned_outcome(reader,s,digest,case_id,goal,basis,*program,*table);
            }else if(op=="observation_batch_audit"){
                const auto item=p.name();
                const auto exact=request_digest(p);
                vector<Atom> goals;
                while(p.take(";")){
                    require(goals.size()<4,"observation batch audit has at most four typed goals");
                    goals.push_back(p.atom());
                }
                p.end();
                require(!goals.empty(),"observation batch audit requires at least one goal");
                payload=audit_observation_batch(reader,s,item,exact,goals);
            }else if(op=="observation_batch"){
                const auto item=p.name();p.ws();const auto exact=p.s.substr(p.i);
                if(s.observation_batches.contains(item))(void)compile_active(s);
                payload=observation_batch_receipt(s,item,exact,false);
            }else if(op=="sensor_receipt"){
                const auto source=p.name();
                const auto sequence=request_sequence(p);
                p.ws();const auto exact=p.s.substr(p.i);
                payload=reconcile_sensor(s,source,sequence,exact);
            }else if(op=="outcome_requests"){
                const auto source=p.name();const auto cursor=request_sequence(p),count=request_sequence(p);p.end();
                require(cursor<=s.events.size()&&count>=1&&count<=32,"invalid outcome request feed cursor or count");
                const auto active=compile_active(s);
                const bool measured=active.measurement_sources.contains(source);
                require(measured||active.pinned_feedback_sources.contains(source),"source is not authorized for pinned outcome requests");
                const auto shape=measured?measure_shape(active,source):"outcome(sym,sym,success_or_failure)";
                const auto memory=read_experiences(s);
                ostringstream feed;
                feed<<"{\"schema\":\"pcgm-outcome-request-feed-v1\",\"individual\":"<<quote_json(s.id)
                    <<",\"source\":"<<quote_json(source)<<",\"results\":[";
                size_t shown=0,next=cursor;bool more=false;
                for(size_t i=cursor;i<s.events.size();++i){
                    if(!s.events.at(i).starts_with("decision "))continue;
                    const auto id="e"+to_string(i+1);
                    const auto& row=memory.at(id);
                    if(!row.observation.empty()||row.context.empty()||!active.experience_contexts.contains(row.context))continue;
                    if(shown==count){more=true;break;}
                    if(shown++)feed<<',';
                    next=i+1;
                    const auto pin=outcome_request_pin(s,source,id,row,shape);
                    feed<<"{\"decision\":"<<quote_json(id)<<",\"context\":"<<quote_json(row.context)
                        <<",\"kind\":"<<quote_json(row.kind)<<",\"decision_record\":"<<quote_json(s.events.at(i))
                        <<",\"request_sha256\":"<<quote_json(pin)<<",\"shape\":"<<quote_json(measured?shape:"outcome(DECISION,CONTEXT,success_or_failure)")<<'}';
                }
                if(!more)next=s.events.size();
                feed<<"],\"cursor\":"<<next<<",\"more\":"<<(more?"true":"false")<<'}';
                payload=feed.str();
            }else if(op=="measurement_history"){
                const auto id=p.name();p.end();
                const auto pinned=s.measurement_bases.find(id);
                require(pinned!=s.measurement_bases.end(),"exact historical measurement basis is unavailable");
                const auto frozen=verify_episode(reader,s,pinned->second);
                const auto row=read_experiences(s).at(id);
                const auto original=compile_active(frozen);
                require(original.observations.contains(row.observation)&&frozen.recorded_observations.contains(row.observation),
                        "pinned measurement basis lacks its admitted raw observation");
                const auto then=run(original,frozen.inactive);
                const auto raw=original.observations.at(row.observation);
                const auto historical=measured_outcome_proof(then,raw,row.observation,id,row.context);
                require(historical&&*historical==s.measured_strength.at(id),"pinned measurement proof did not recreate the original signed outcome");
                const auto current=compile_active(s);
                const auto now=run(current,s.inactive);
                const auto contribution=feedback_value(s,current,now,id,row).value_or(0);
                const Atom wanted{"measured_outcome",{id,row.context,*historical>0?"success":"failure"}};
                payload="{\"schema\":\"pcgm-measurement-history-v1\",\"decision\":"+quote_json(id)+
                    ",\"observation\":"+quote_json(row.observation)+
                    ",\"basis_sha256\":"+quote_json(pinned->second.digest)+",\"basis_event\":"+to_string(pinned->second.events)+
                    ",\"then_contribution\":"+to_string(*historical)+",\"now_contribution\":"+to_string(contribution)+
                    ",\"historical_proof_sha256\":"+quote_json(proof_digest(then,wanted))+
                    ",\"historical_proof\":"+json_report(then,{wanted},"pcgm",channel_context(frozen))+
                    ",\"current_proof\":"+json_report(now,{wanted},"pcgm",channel_context(s))+"}";
            }else if(op=="learned_outcome"){
                const auto id=p.name();p.end();
                const bool measured=s.measured_from_cycle.contains(id);
                require(measured||s.learned_from_cycle.contains(id),"no automatically learned outcome for this decision");
                const auto& [source,serial,index]=(measured?s.measured_from_cycle:s.learned_from_cycle).at(id);
                const auto history=read_experiences(s);
                const auto& row=history.at(id);
                const auto active=compile_active(s);
                const auto table=run(active,s.inactive);
                const auto strength=feedback_value(s,active,table,id,row);
                payload="{\"schema\":\"pcgm-learned-outcome-v1\",\"decision\":"+quote_json(id)+
                    ",\"context\":"+quote_json(row.context)+",\"observation\":"+quote_json(row.observation)+
                    ",\"source\":"+quote_json(source)+",\"sequence\":"+to_string(serial)+
                    ",\"index\":"+to_string(index)+",\"packet_sha256\":"+quote_json(s.cycles.at({source,serial}).digest)+
                    ",\"active_contribution\":"+to_string(strength.value_or(0));
                if(measured)payload+=",\"measured\":true,\"original_contribution\":"+to_string(s.measured_strength.at(id));
                payload+="}";
            }else if(op=="workspace_proof"){
                const auto alias=p.name();p.ws();const auto candidate=p.s.substr(p.i);
                require(candidate.size()==64&&hex_chars(candidate),"invalid workspace archive address");
                require(s.package_versions.contains(alias)&&s.package_versions.at(alias).contains(candidate),
                        "workspace candidate unavailable");
                require(s.workspace_proof_origins.contains(alias)&&s.workspace_proof_origins.at(alias).contains(candidate),
                        "exact workspace evidence was not retained for this candidate");
                const auto& proof=s.workspace_proof_origins.at(alias).at(candidate);
                const auto& origin=s.workspace_recipe_origins.at(alias).at(candidate);
                const auto verified=compile_active(s);
                for(const auto& [id,fact]:proof.source_facts)
                    require(verified.observations.contains(id)&&verified.observations.at(id)==fact,
                            "native CL recipe proof differs from admitted source fact");
                payload="{\"schema\":\"pcgm-workspace-proof-v1\",\"individual\":"+quote_json(s.id)+
                   ",\"alias\":"+quote_json(alias)+",\"base_sha256\":"+quote_json(proof.base)+
                   ",\"candidate_sha256\":"+quote_json(candidate)+
                   ",\"lock_sha256\":"+quote_json(s.workspace_origins.at(alias).at(proof.base).profile)+
                   ",\"recipe_sha256\":"+quote_json(origin.recipe)+",\"scope_sha256\":"+quote_json(origin.scope)+
                   ",\"evidence_sha256\":"+quote_json(origin.evidence)+",\"evidence\":"+quote_json(proof.bytes)+"}";
            }else if(op=="workspace_growth"){
                const auto alias=p.name();p.end();
                require(s.workspace_locks.contains(alias),"unknown CL workspace alias");
                payload="{\"schema\":\"pcgm-workspace-growth-v1\",\"alias\":"+quote_json(alias)+
                    ",\"active_ir_sha256\":"+quote_json(s.artifacts.at(alias))+",\"edges\":[";
                bool first=true;
                if(const auto found=s.workspace_additive_edges.find(alias);found!=s.workspace_additive_edges.end())
                    for(const auto& [edge,goals]:found->second){
                        if(!first)payload+=',';
                        first=false;
                        payload+="{\"before_ir_sha256\":"+quote_json(edge.first)+
                            ",\"after_ir_sha256\":"+quote_json(edge.second)+",\"goals_sha256\":"+quote_json(goals)+"}";
                    }
                payload+="]}";
            }else if((op=="choice_reassess"||op=="choice_attribution")){
                const auto ticket=p.name();
                require(ticket.size()==33&&ticket[0]=='d'&&hex_chars(ticket.substr(1)),"invalid PCGM choice outcome address");
                p.ws();const auto expected=p.s.substr(p.i);
                require(expected.size()==64&&hex_chars(expected)&&expected==digest,"PCGM reassessment head digest mismatch");
                payload=op=="choice_attribution"?explain_choice_attribution(reader,s,ticket,digest):
                    reassess_choice(reader,s,ticket,digest);
            }else if(op=="choice_option"){
                const auto id=p.name();
                require(id.size()==33&&id[0]=='d'&&hex_chars(id.substr(1)),"invalid PCGM choice outcome address");
                const auto index=request_sequence(p);
                vector<Atom> goals;
                while(p.take(";")){
                    require(goals.size()<4,"choice option has at most four proof comparisons");
                    goals.push_back(p.atom());
                }
                p.end();payload=counterfactual_option(reader,s,id,index,goals);
            }else if(op=="choice_basis"){
                const auto id=p.name();
                require(id.size()==33&&id[0]=='d'&&hex_chars(id.substr(1)),"invalid PCGM choice outcome address");
                vector<Atom> goals;
                while(p.take(";")){
                    require(goals.size()<4,"choice basis has at most four proof comparisons");
                    goals.push_back(p.atom());
                }
                p.end();payload=reconstructed_basis(reader,s,id,goals,digest);
            }else if(op=="choice_intent"){
                const auto id=p.name();p.end();
                require(id.size()==33&&id.front()=='d'&&hex_chars(id.substr(1)),"invalid durable choice intent address");
                const auto intent=s.choice_intents.find(id);
                string status="not_recorded";
                const auto binding=s.choice_rebound_intents.find(id);
                const auto* rebound=binding==s.choice_rebound_intents.end()?nullptr:&binding->second;
                if(intent!=s.choice_intents.end())
                    status=s.choice_outcomes.contains(id)?"completed":s.cancelled_intents.contains(id)?"cancelled":
                           coherent_choice_basis(s,id,intent->second,rebound)?"queued":"stale";
                payload="{\"schema\":\"pcgm-choice-intent-v1\",\"id\":"+quote_json(id)+",\"status\":"+quote_json(status);
                if(intent!=s.choice_intents.end())payload+=",\"initial_basis_sha256\":"+quote_json(intent->second.digest);
                if(rebound)payload+=",\"bound_basis_sha256\":"+quote_json(rebound->digest);
                payload+="}";
            }else if(op=="choice_receipt"){
                const auto id=p.name();p.end();
                require(id.size()==33&&id[0]=='d'&&hex_chars(id.substr(1)),"invalid PCGM choice outcome address");
                const auto found=s.choice_outcomes.find(id);
                payload="{\"schema\":\"pcgm-choice-outcome-v1\",\"id\":"+quote_json(id)+
                    ",\"individual\":"+quote_json(s.id)+",\"status\":"+
                    quote_json(found==s.choice_outcomes.end()?"not_recorded":found->second.kind);
                if(found!=s.choice_outcomes.end())payload+=",\"basis_sha256\":"+quote_json(found->second.basis)+
                    ",\"decision\":"+found->second.receipt;
                payload+="}";
            }else if(op=="question"||op=="question_feed"){
                const auto ticket=op=="question"?p.name():string{};
                const auto cursor=op=="question_feed"?request_sequence(p):0;
                const auto count=op=="question_feed"?request_sequence(p):1;
                p.end();
                require(cursor<=s.events.size()&&count>0&&count<=32,"invalid question feed cursor or count");
                if(digest!=cached_digest){program=compile_active(s);table.reset();cached_digest=digest;}
                require(program.has_value(),"question read compiler state unavailable");
                if(!table)table=run(*program,s.inactive);
                const auto gaps=open_gaps(*program,*table);
                std::ostringstream wire;
                wire<<"{\"schema\":\"pcgm-question-feed-v1\",\"state\":"<<channel_context(s)
                    <<",\"revision_sha256\":"<<quote_json(digest)<<",\"results\":[";
                size_t next=cursor,shown=0;bool more=false;
                if(op=="question"){
                    const auto one=s.questions.find(ticket);
                    require(one!=s.questions.end(),"unknown question");
                    wire<<question_json(s,ticket,one->second,*table,gaps,&*program);
                }else{
                    for(size_t i=cursor;i<s.events.size();++i){
                        if(!s.events[i].starts_with("question "))continue;
                        if(shown==count){more=true;break;}
                        const auto id="q"+to_string(i+1);
                        if(shown++)wire<<',';
                        wire<<question_json(s,id,s.questions.at(id),*table,gaps,&*program);
                        next=i+1;
                    }
                    if(!more)next=s.events.size();
                }
                wire<<"],\"cursor\":"<<next<<",\"more\":"<<(more?"true":"false")<<'}';
                payload=wire.str();
                require(payload.size()<=2*1024*1024,"question feed response too large");
            }else if(op=="pinned_review"){
                const auto pin=p.name(),pin_digest=request_digest(p);
                const auto decisions=request_sequence(p),notices=request_sequence(p),maximum=request_sequence(p);
                vector<Atom> goals;
                while(p.take(";")){
                    require(goals.size()<4,"pinned review has at most four proof goals");
                    goals.push_back(p.atom());
                }
                p.end();payload=pinned_review(reader,s,pin,pin_digest,decisions,notices,maximum,goals);
            }else if(op=="review"){
                const auto decisions=request_sequence(p),notices=request_sequence(p),maximum=request_sequence(p);
                require(notices<=s.events.size(),"review notice cursor beyond head");
                vector<Atom> goals;
                while(p.take(";")){
                    require(goals.size()<4,"review has at most four proof goals");
                    goals.push_back(p.atom());
                }
                p.end();
                string proof="null";
                if(!goals.empty()){
                    if(digest!=cached_digest){
                        program=compile_active(s);table.reset();cached_digest=digest;
                    }
                    require(program.has_value(),"review compiler state unavailable");
                    for(const auto& goal:goals)validate_time_query(*program,goal);
                    if(!table)table=run(*program,s.inactive);
                    proof=json_report(*table,goals,"pcgm",channel_context(s));
                }
                payload="{\"schema\":\"pcgm-review-v1\",\"revision_sha256\":"+quote_json(digest)+
                    ",\"status\":"+channel_status(s)+",\"proofs\":"+proof+",\"decisions\":"+
                    decision_window(s,decisions,maximum)+",\"notices\":"+notice_report(s,notices,"")+"}";
                require(payload.size()<=2*1024*1024,"review exceeds 2 MiB");
            }else if(op=="storage"||op=="storage_fresh"){
                p.end();
                payload="{\"schema\":\"pcgm-storage-v1\",\"state\":"+channel_context(s)+
                    ",\"representation\":"+quote_json(reader.compacted?"compact":"materialized")+
                    ",\"logical_sha256\":"+quote_json(digest)+",\"physical_sha256\":"+
                    quote_json(reader.physical_sha256)+",\"logical_bytes\":"+to_string(reader.logical_bytes)+
                    ",\"physical_bytes\":"+to_string(reader.physical_bytes)+
                    ",\"archive_verified_reads\":"+to_string(reader.archive_cache.reads)+",\"archive_verified_bytes\":"+
                    to_string(reader.archive_cache.verified_bytes)+",\"archive_cache_hits\":"+to_string(reader.archive_cache.hits)+"}";
            }else if(op=="archives"){
                p.end();payload=archive_report(reader,s);
            }else if(op=="historical"){
                const auto label=p.name();
                const auto atom=p.atom();p.end();
                payload="{\"schema\":\"pcgm-historical-proof-v1\",\"head\":"+channel_context(s)+
                    ",\"result\":"+historical_payload(reader,s,label,atom,true)+"}";
            }else if(op=="timeline"){
                const auto cursor=request_sequence(p),limit=request_sequence(p);
                const auto atom=p.atom();p.end();
                payload=historical_timeline(reader,s,cursor,limit,atom);
            }else if(op=="batch"){
                const auto limit=request_sequence(p);
                require(limit<=4,"worker ceiling must be 0 to 4");
                vector<Atom> goals;
                do{
                    require(goals.size()<8,"inspection query limit is 8");
                    goals.push_back(p.atom());
                }while(p.take(";"));
                p.end();
                if(digest!=cached_digest){
                    program=compile_active(s);
                    table.reset();cached_digest=digest;
                }
                require(program.has_value(),"no compiled reader state");
                for(const auto& query:goals)validate_time_query(*program,query);
                const auto result=evaluate_planes(*program,goals,s.inactive,limit,
                    [](const Program& p,const set<string>& inactive){return run(p,inactive);});
                payload=render_planes(result,"{\"engine\":\"pcgm\",\"revision_sha256\":"+quote_json(digest)+
                    ",\"state\":"+channel_context(s)+"}");
            }else if(op=="slice"){
                vector<Atom> goals;
                do{
                    require(goals.size()<8,"inspection query limit is 8");
                    goals.push_back(p.atom());
                }while(p.take(";"));
                p.end();
                if(digest!=cached_digest){
                    program=compile_active(s);
                    table.reset();cached_digest=digest;
                }
                require(program.has_value(),"no compiled reader state");
                for(const auto& query:goals)validate_time_query(*program,query);
                SliceStats counts;
                const auto kept=query_slice(*program,goals,counts);
                const auto result=run(kept,s.inactive);
                payload="{\"schema\":\"pcgm-query-slice-v1\",\"revision_sha256\":"+quote_json(digest)+
                    ",\"relations\":"+to_string(counts.relations)+",\"rules\":"+to_string(counts.rules)+
                    ",\"observations\":"+to_string(counts.observations)+",\"proofs\":"+
                    json_report(result,goals,"pcgm",channel_context(s))+"}";
                require(payload.size()<=2*1024*1024,"query projection exceeds 2 MiB");
            }else if(op=="generated"){
                p.end();
                ostringstream stream;bool first=true;
                stream<<"{\"schema\":\"pcgm-cl-origins-v1\",\"state\":"<<channel_context(s)<<",\"results\":[";
                for(const auto& [alias,history]:s.generated_artifacts)for(const auto& [_,item]:history){
                    if(!first)stream<<',';
                    first=false;
                    stream<<"{\"alias\":"<<quote_json(alias)<<",\"profile_sha256\":"<<quote_json(item.profile)
                        <<",\"source_sha256\":"<<quote_json(item.source)<<",\"ir_sha256\":"<<quote_json(item.image)
                        <<",\"active\":"<<(s.artifacts.at(alias)==item.image?"true":"false");
                    if(const auto generated=s.synthesized_artifacts.find(alias);generated!=s.synthesized_artifacts.end())
                        if(const auto syn=generated->second.find(item.image);syn!=generated->second.end()){
                            const auto& detail=syn->second;
                            stream<<",\"synthesis\":{\"generator_sha256\":"<<quote_json(detail.generator)
                                <<",\"scope_sha256\":"<<quote_json(detail.scope)
                                <<",\"evidence_sha256\":"<<quote_json(detail.evidence)<<'}';
                        }
                    stream<<'}';
                }
                stream<<"]}";payload=stream.str();
            }else if(op=="packages"){
                p.end();
                ostringstream records;bool first=true;
                records<<"{\"schema\":\"pcgm-packages-v1\",\"state\":"<<channel_context(s)<<",\"results\":[";
                for(const auto& [name,versions]:s.package_versions)for(const auto& record:versions){
                    if(!first)records<<',';
                    first=false;
                    records<<"{\"alias\":"<<quote_json(name)<<",\"package_sha256\":"<<quote_json(record.first)
                           <<",\"ir_sha256\":"<<quote_json(record.second)<<",\"active\":"
                           <<(s.artifacts.at(name)==record.second?"true":"false");
                    if(s.scope_origins.contains(name)&&s.scope_origins.at(name).contains(record.first)){
                        const auto& scope=s.scope_origins.at(name).at(record.first);
                        records<<",\"scope_policy_sha256\":"<<quote_json(scope.profile)
                               <<",\"scope_report_sha256\":"<<quote_json(scope.report);
                    }
                    if(s.workspace_origins.contains(name)&&s.workspace_origins.at(name).contains(record.first)){
                        const auto& scope=s.workspace_origins.at(name).at(record.first);
                        records<<",\"workspace_lock_sha256\":"<<quote_json(scope.profile)
                               <<",\"workspace_audit_sha256\":"<<quote_json(scope.report);
                    }
                    if(s.workspace_source_origins.contains(name)&&s.workspace_source_origins.at(name).contains(record.first))
                        records<<",\"workspace_source_sha256\":"<<quote_json(s.workspace_source_origins.at(name).at(record.first));
                    if(s.workspace_recipe_origins.contains(name)&&s.workspace_recipe_origins.at(name).contains(record.first)){
                        const auto& authored=s.workspace_recipe_origins.at(name).at(record.first);
                        records<<",\"workspace_recipe_sha256\":"<<quote_json(authored.recipe)
                               <<",\"workspace_recipe_scope_sha256\":"<<quote_json(authored.scope)
                               <<",\"workspace_recipe_evidence_sha256\":"<<quote_json(authored.evidence);
                    }
                    records<<'}';
                }
                records<<"]}";
                payload=records.str();
            }else if(op=="decision"){
                const auto decision=p.name();p.end();
                payload=stored_decision(s,decision);
            }else if(op=="notices"){
                const auto from=request_sequence(p);
                p.ws();string filter;
                if(p.i<p.s.size())filter=p.name();
                p.end();
                require(from<=s.events.size(),"notice cursor beyond head");
                payload=notice_report(s,from,filter);
            }else{
                vector<Atom> goals;
                unsigned from=0;
                string expected;
                if(op=="inspect"){
                    expected=request_digest(p);
                    from=request_sequence(p);
                    require(from<=s.events.size(),"notice cursor beyond head");
                    while(p.take(";")){
                        require(goals.size()<8,"inspection query limit is 8");
                        goals.push_back(p.atom());
                    }
                }else goals.push_back(p.atom());
                p.end();
                require(expected.empty()||expected==digest,"revision no longer current");
                string proofs="null";
                if(!goals.empty()){
                    if(digest!=cached_digest){
                        program=compile_active(s);
                        table.reset();
                        cached_digest=digest;
                    }
                    require(program.has_value(),"no compiled reader state");
                    if(!table)table=run(*program,s.inactive);
                    for(const auto& query:goals)validate_time_query(*program,query);
                    if(op!="fingerprint")proofs=json_report(*table,goals,"pcgm",channel_context(s));
                }
                if(op=="proof")payload=move(proofs);
                else if(op=="fingerprint"){
                    ostringstream o;
                    o<<"{\"schema\":\"pcgm-proof-id-v2\",\"goal\":";
                    json_atom(o,goals.at(0));
                    o<<",\"sha256\":"<<quote_json(proof_digest(*table,goals.at(0)))
                     <<",\"revision_sha256\":"<<quote_json(digest)<<'}';
                    payload=o.str();
                }
                else {
                    payload="{\"schema\":\"pcgm-inspection-v1\",\"revision_sha256\":"+quote_json(digest)+
                            ",\"status\":"+channel_status(s)+",\"proofs\":"+proofs+
                            ",\"notices\":"+notice_report(s,from,"")+"}";
                    require(payload.size()<=2*1024*1024,"inspection exceeds 2 MiB; request fewer proofs");
                }
            }
            output<<"{\"protocol\":\"pcgm-read-v1\",\"id\":"<<quote_json(id)
                <<",\"ok\":true,\"payload\":"<<payload<<"}\n";
        }catch(const exception& e){
            output<<"{\"protocol\":\"pcgm-read-v1\",\"id\":"<<(id.empty()?"null":quote_json(id))
                <<",\"ok\":false,\"error\":"<<quote_json(e.what())<<"}\n";
        }
    }
    return 0;
}
