#include <tuple>
#include <cerrno>
#include <cstring>
#include <fcntl.h>

using Descriptor=native_os::Descriptor;
constexpr size_t state_limit=8*1024*1024; // reconstructed logical state and full materializations
constexpr size_t compact_file_limit=2*1024*1024;
constexpr size_t archive_segment_limit=4*1024*1024;
constexpr unsigned history_event_limit=50000;
constexpr size_t archive_count_limit=512;
struct CycleReceipt { string digest; unsigned observations=0,questions=0; };
struct SensorResponse {string workspace;unsigned event=0;};
using CycleKey=pair<string,unsigned>;
struct AutoReceipt { string status,reason; };
unsigned sequence_number(const string& s){
    unsigned out=0;
    auto r=from_chars(s.data(),s.data()+s.size(),out);
    require(r.ec==errc{}&&r.ptr==s.data()+s.size()&&to_string(out)==s,"invalid canonical sequence number");
    return out;
}
string cycle_obs_id(const string& source,unsigned sequence,unsigned index){
    return "sensor_"+source+"_"+to_string(sequence)+"_"+to_string(index);
}
struct RevisionPlan {
    string snapshot,patch;
    size_t offset=0;
    bool applied=false,reverted=false;
};
bool hex_chars(const string& s){return s.find_first_not_of("0123456789abcdef")==string::npos;}
bool valid_identity(const string& id){
    auto core=id.starts_with("TEST-R28-")?id.substr(9):id;
    return core.size()==32&&hex_chars(core);
}
string to_hex(const string& s){
    constexpr char digits[]="0123456789abcdef";
    string out;out.reserve(2*s.size());
    for(unsigned char c:s){out+=digits[c>>4];out+=digits[c&15];}
    return out;
}
string from_hex(const string& s){
    require(!s.empty()&&s.size()%2==0&&s.size()<=32768&&hex_chars(s),"invalid serialized rule patch");
    auto decode=[](char c){return c<='9'?c-'0':c-'a'+10;};
    string out;out.reserve(s.size()/2);
    for(size_t i=0;i<s.size();i+=2) out+=static_cast<char>((decode(s[i])<<4)|decode(s[i+1]));
    return out;
}
struct ScopeOrigin {string profile,report;};
struct RecipeOrigin {string recipe,scope,evidence;};
struct WorkspaceProofOrigin {string base,bytes;map<string,Atom> source_facts;};
struct LocalQuestion { Atom goal, fact; bool agenda=false; };
struct WireReceipt {string ticket,source,pin,packet;};
struct BundleReceipt {string ticket,request,package,proof;};
struct ChoiceOutcome {string basis,kind,receipt;};
struct NativeHandoff {
    string from,from_hash,to,to_hash,base_state,nonce;
};
struct LocalTurn { string request,reply; };
struct LocalSession {
    optional<Atom> focus;
    map<string,LocalTurn> turns;
    vector<string> order;
};
struct Pin { string digest; unsigned events; };
struct SynthesisOrigin {string generator,scope,evidence;};
struct CompilerOrigin {string profile,source,image;};
struct Notice {unsigned event;string watch;Atom fact;string before,after,source_before,source_after;unsigned identity_version;};
struct ArchiveSegment {unsigned first,last;string previous,digest,snapshot;};
bool ordinary_observation_id(const string& id){
    return !id.starts_with("geom_sensor_")&&!id.starts_with("sensor_")&&
           !id.starts_with("wire_")&&!id.starts_with("bundle_")&&!id.starts_with("artifact_");
}
struct ObservationBatchEdit {string operation,id;optional<Atom> fact;};
struct ObservationBatch {string id,basis;vector<ObservationBatchEdit> edits;bool audited=false;};
struct ObservationBatchReceipt {string basis,digest;unsigned event,version,count;};
ObservationBatch parse_observation_batch(const string& line){
    const bool audited=line.starts_with(":observation_batch_audited ");
    const string_view prefix=audited?":observation_batch_audited ":":observation_batch ";
    require(line.starts_with(prefix)&&line.size()<=4096&&line.find_first_of("\r\n")==string::npos,
            "invalid observation batch frame or size");
    Parser q{line.substr(prefix.size())};
    ObservationBatch parsed;parsed.audited=audited;
    parsed.id=q.name();q.ws();
    require(q.i+64<=q.s.size(),"observation batch requires exact head SHA-256");
    parsed.basis=q.s.substr(q.i,64);
    require(hex_chars(parsed.basis),"observation batch requires exact head SHA-256");
    q.i+=64;
    set<string> unique;
    while(q.take(";")){
        const auto op=q.name(),id=q.name();
        require(parsed.edits.size()<8&&(op=="observe"||op=="withdraw"||op=="restore"),
                "invalid observation batch operation or count");
        require(ordinary_observation_id(id)&&unique.insert(id).second,
                "observation batch requires distinct ordinary observation IDs");
        auto& item=parsed.edits.emplace_back(ObservationBatchEdit{op,id,{}});
        if(op=="observe"){
            item.fact=q.atom();
            require(std::ranges::none_of(item.fact->args,variable),"observation batch facts must be ground");
        }
    }
    q.end();
    require(!parsed.edits.empty(),"observation batch requires at least one edit");
    return parsed;
}
// Windows single-individual dialogue ledger. Enforce identical caps on admission and replay.
constexpr size_t native_dialogue_session_limit=512;
constexpr size_t native_dialogue_turn_limit=4096;
struct Continuity {
    string id;
    string source;
    set<string> inactive, modules, recorded_observations;
    vector<string> events;
    map<string,LocalQuestion> questions;
    map<string,tuple<string,string,string>> obligation_enrollments;
    map<string,ObservationBatchReceipt> observation_batches;
    map<string,Pin> observation_batch_audit_bases;
    map<string,Atom> observation_batch_facts;
    map<string,string> receipt_question;
    map<string,WireReceipt> wire_receipts;
    map<string,BundleReceipt> bundle_receipts;
    map<string,pair<string,string>> frozen_receipts;
    map<string,string> workspace_answer_locks;
    map<string,string> bundle_assessments;
    map<string,ChoiceOutcome> choice_outcomes;
    set<string> choice_bases;
    map<string,Pin> choice_intents,choice_rebound_intents;
    set<string> cancelled_intents;
    map<CycleKey,CycleReceipt> cycles;
    map<CycleKey,SensorResponse> sensor_responses;
    map<CycleKey,AutoReceipt> automatic;
    set<string> autopause;
    map<string,unsigned> last_cycle;
    map<string,RevisionPlan> plans;
    map<string,LocalSession> dialogues;
    map<string,string> decision_traces;
    map<string,Pin> pins;
    map<string,string> artifacts;
    map<string,map<string,CompilerOrigin>> generated_artifacts;
    map<string,map<string,SynthesisOrigin>> synthesized_artifacts;
    map<string,pair<string,string>> installed_packages;
    map<string,map<string,string>> package_versions;
    map<string,string> package_contracts;
    map<string,string> scope_policies;
    map<string,map<string,ScopeOrigin>> scope_origins;
    map<string,string> workspace_locks;
    map<string,set<string>> workspace_authorized;
    map<string,map<string,ScopeOrigin>> workspace_origins;
    map<string,map<string,string>> workspace_source_origins;
    map<string,map<pair<string,string>,string>> workspace_additive_edges;
    map<string,map<string,string>> workspace_version_contracts;
    map<string,map<string,RecipeOrigin>> workspace_recipe_origins;
    map<string,map<string,WorkspaceProofOrigin>> workspace_proof_origins;
    map<string,tuple<string,unsigned,unsigned>> learned_from_cycle,measured_from_cycle;
    map<string,int> measured_strength;
    map<string,Pin> measurement_bases;
    map<string,set<string>> artifact_versions;
    map<string,Atom> watches;
    vector<Notice> notices;
    vector<ArchiveSegment> archives;
    vector<string> active_revisions;
    string owner,owner_hash,staged_copy;
    optional<NativeHandoff> pending;
    bool has_field=false;
    unsigned epoch=0;
    unsigned observation_version=0;
};

bool choice_owner_only_tail(const vector<string>& events,size_t from){
    if(from>events.size())return false;
    const auto n=events.size()-from;
    if(n<2||n>8||n%2)return false;
    for(size_t i=from;i<events.size();i+=2)
        if(!events[i].starts_with("handoff ")||!events[i+1].starts_with("claimed "))return false;
    return true;
}
bool coherent_choice_basis(const Continuity& state,const string& id,const Pin& initial,const Pin* rebound=nullptr){
    if(rebound)return state.events.size()==rebound->events+1&&
        state.events.back()=="choice_intent_rebound "+id+" "+initial.digest+" "+rebound->digest+" "+to_string(rebound->events);
    return state.events.size()==initial.events+1&&
        state.events.back()=="choice_intent "+id+" "+initial.digest+" "+to_string(initial.events);
}

string new_id(){
    unsigned char bytes[16];
    native_os::random_bytes(bytes,sizeof(bytes));
    constexpr char hex[]="0123456789abcdef";
    string out;
    for(auto b:bytes){ out+=hex[b>>4]; out+=hex[b&15]; }
    return out;
}

// Accidental corruption detector, not an authenticity guarantee.
string checksum(const string& data){
    uint64_t hash=14695981039346656037ULL;
    for(unsigned char c:data){ hash^=c; hash*=1099511628211ULL; }
    return to_string(hash);
}
string encode(const Continuity& c){
    string payload=c.id+"\n";
    for(const auto& event:c.events) payload+=event+"\n";
    payload+="source\n"+c.source;
    auto bytes="PCGM-STATE-1\n"+checksum(payload)+"\n"+payload;
    require(bytes.size()<=state_limit,"persistent state size limit");
    return bytes;
}

Continuity decode(const string& s){
    const string magic="PCGM-STATE-1\n";
    require(s.starts_with(magic),"invalid persistent state format");
    size_t p=magic.size();
    auto next_line=[&]{
        const auto end=s.find('\n',p);
        require(end!=string::npos,"truncated persistent state");
        auto line=s.substr(p,end-p);
        p=end+1;
        return line;
    };
    const auto digest=next_line();
    require(digest==checksum(s.substr(p)),"persistent state checksum mismatch");
    Continuity c;
    c.id=next_line();
    require(valid_identity(c.id),
            "invalid persistent individual ID");
    optional<CycleKey> current_cycle;
    vector<ObservationBatchEdit> pending_batch;
    size_t batch_edit=0;
    unsigned batch_i=0, questions_i=0;
    while(true){
        const auto e=next_line();
        const CycleReceipt* reading=current_cycle?&c.cycles.at(*current_cycle):nullptr;
        if(reading&&batch_i==reading->observations && questions_i==reading->questions){
            current_cycle.reset(); reading=nullptr;
        }
        if(e=="source"){
            require(!reading,"incomplete cycle receipt");
            require(batch_edit==pending_batch.size(),"incomplete observation batch receipt");
            break;
        }
        if(batch_edit<pending_batch.size()){
            const auto& expected=pending_batch.at(batch_edit++);
            require(e==expected.operation+" "+expected.id,"observation batch edit order mismatch");
        }
        if(reading){
            if(batch_i<reading->observations){
                const auto& [name,seq]=*current_cycle;
                require(e=="observe "+cycle_obs_id(name,seq,++batch_i),"cycle observation order mismatch");
            }else{
                require(e.starts_with("question "),"cycle question order mismatch");
                ++questions_i;
            }
        }
        require(c.events.size()<history_event_limit,"persistent history limit");
        if(!c.staged_copy.empty())require(e.starts_with("activated_copy "),"unactivated copy cannot append new events");
        if(c.pending)require(e.starts_with("claimed ")||e.starts_with("handoff_cancelled "),
                             "unresolved handoff must terminate the state");
        if(e.starts_with("owner ")){
            istringstream in(e.substr(6));string extra;
            require(c.events.empty()&&bool(in>>c.owner>>c.owner_hash)&&!(in>>extra)&&
                    c.owner_hash.size()==64&&hex_chars(c.owner_hash),"invalid initial owner");
            Parser q{c.owner};q.name();q.end();
        }
        else if(e.starts_with("restored_copy ")){
            const auto digest=e.substr(14);
            require(c.staged_copy.empty()&&digest.size()==64&&hex_chars(digest),"invalid restored-copy state");
            c.staged_copy=digest;
        }
        else if(e.starts_with("activated_copy ")){
            require(!c.staged_copy.empty()&&e.substr(15)==c.staged_copy,"invalid copy activation");
            c.staged_copy.clear();
        }
        else if(e.starts_with("handoff ")){
            istringstream in(e.substr(8));NativeHandoff h;string extra;
            require(bool(in>>h.from>>h.from_hash>>h.to>>h.to_hash>>h.base_state>>h.nonce)&&!(in>>extra),
                    "invalid durable handoff");
            Parser q{h.to};q.name();q.end();
            require(h.from==c.owner&&!h.from.empty()&&h.from_hash==c.owner_hash&&
                    h.to_hash.size()==64&&hex_chars(h.to_hash)&&h.from_hash!=h.to_hash&&
                    h.base_state.size()==64&&hex_chars(h.base_state)&&h.nonce.size()==32&&hex_chars(h.nonce),
                    "inconsistent durable handoff");
            c.pending=std::move(h);
        }
        else if(e.starts_with("claimed ")||e.starts_with("handoff_cancelled ")){
            const bool claim=e.starts_with("claimed ");
            require(c.pending&&e.substr(claim?8:18)==c.pending->nonce,"handoff token mismatch in state");
            if(claim){c.owner=c.pending->to;c.owner_hash=c.pending->to_hash;}
            c.pending.reset();
        }
        else if(e=="revision") ++c.epoch;
        else if(e=="field_v11_glyph64_s8"){
            require(!c.has_field && c.modules.contains("geometry"),"invalid geometry initialization");
            c.has_field=true;
        }
        else if(e.starts_with("field_tick ")){
            require(c.has_field,"geometry tick without initialization");
        }
        else if(e.starts_with("proposal ")){
            istringstream in(e.substr(9));string snapshot,patch,extra;
            require(bool(in>>snapshot>>patch)&&!(in>>extra)&&snapshot.size()==64&&hex_chars(snapshot),
                    "invalid persistent revision proposal");
            require(c.plans.size()<128,"persistent revision plan limit");
            c.plans.emplace("p"+to_string(c.events.size()+1),RevisionPlan{snapshot,from_hex(patch)});
        }
        else if(e.starts_with("apply ")){
            istringstream in(e.substr(6));string id,position,extra;
            require(bool(in>>id>>position)&&!(in>>extra)&&c.plans.contains(id),"invalid persisted apply");
            auto& plan=c.plans.at(id);
            require(!plan.applied,"proposal applied twice");
            plan.applied=true;
            plan.offset=sequence_number(position);
            c.active_revisions.push_back(id);
            ++c.epoch;
        }
        else if(e.starts_with("revert ")){
            Parser q{e.substr(7)};const auto id=q.name();q.end();
            require(!c.active_revisions.empty()&&c.active_revisions.back()==id,"rollback is not latest");
            c.plans.at(id).reverted=true;
            c.active_revisions.pop_back();
            ++c.epoch;
        }
        else if(e.starts_with("cycle ")){
            require(!reading,"nested cycle receipt");
            istringstream in(e.substr(6));string server,seq,digest,records,questions,extra;
            require(bool(in>>server>>seq>>digest>>records>>questions)&&!(in>>extra),"invalid cycle receipt");
            Parser name{server};const auto src=name.name();name.end();
            require(src.size()<=16 && digest.size()==64 &&
                    digest.find_first_not_of("0123456789abcdef")==string::npos,"invalid cycle receipt identity");
            const auto n=sequence_number(seq), r=sequence_number(records), q=sequence_number(questions);
            require(n>0&&n<=1000000&&r>0&&r<=64&&q<=256&&n==c.last_cycle[src]+1,
                    "cycle receipt sequence or size mismatch");
            current_cycle=CycleKey{src,n};
            require(c.cycles.emplace(*current_cycle,CycleReceipt{digest,r,q}).second,"duplicate cycle receipt");
            c.last_cycle[src]=n;
            batch_i=questions_i=0;
        }
        else if(e.starts_with("question ")){
            Parser q{e.substr(9)};
            const auto goal=q.atom(), fact=q.atom(); q.end();
            const auto ground=[](const Atom& a){return !a.pred.starts_with("!") &&
                std::ranges::none_of(a.args,variable);};
            require(ground(goal)&&ground(fact)&&goal!=fact,"invalid durable question");
            const auto id="q"+to_string(c.events.size()+1);
            for(const auto& [_,old]:c.questions)
                require(old.goal!=goal||old.fact!=fact,"duplicate durable question");
            require(c.questions.size()<256,"persistent question limit");
            c.questions.emplace(id,LocalQuestion{goal,fact});
        }
        else if(e.starts_with("obligation_enrolled ")){
            istringstream in(e.substr(20));string pin,review,head,ticket,extra;
            require(bool(in>>pin>>review>>head>>ticket)&&!(in>>extra)&&
                pin.size()==64&&hex_chars(pin)&&review.size()==64&&hex_chars(review)&&head.size()==64&&hex_chars(head)&&
                c.questions.contains(ticket)&&ticket=="q"+to_string(c.events.size()),
                "invalid durable obligation enrollment");
            require(c.obligation_enrollments.emplace(pin,tuple{review,head,ticket}).second,
                "duplicate durable obligation enrollment");
            c.questions.at(ticket).agenda=sha256("PCGM-LOCAL-AGENDA-APPROVAL-1\n"+c.id+"\n"+head+"\n"+review+"\n")==pin;
        }
        else if(e.starts_with("cycle_response ")){
            istringstream in(e.substr(15));string channel,sequence,packet,hex,extra;
            require(bool(in>>channel>>sequence>>packet>>hex)&&!(in>>extra),"invalid correlated sensor response");
            const CycleKey key{channel,sequence_number(sequence)};
            require(c.cycles.contains(key)&&c.cycles.at(key).digest==packet,"sensor response does not match the original packet");
            auto detail=hex=="-"?string{}:from_hex(hex);
            require(detail.size()<=480,"durable workspace decision output exceeds sensor limit");
            require(c.sensor_responses.emplace(key,SensorResponse{std::move(detail),static_cast<unsigned>(c.events.size()+1)}).second,
                    "duplicate correlated sensor response");
        }
        else if(e.starts_with("answer ")){
            Parser q{e.substr(7)};
            const auto ticket=q.name(), id=q.name(); q.end();
            require(c.questions.contains(ticket),"answer precedes its question");
            require(c.recorded_observations.insert(id).second &&
                    c.receipt_question.emplace(id,ticket).second,"duplicate recorded answer");
            ++c.observation_version;
        }
        else if(e.starts_with("answer_wire ")){
            istringstream r(e.substr(12));string ticket,id,source,pin,packet,extra;
            require(bool(r>>ticket>>id>>source>>pin>>packet)&&!(r>>extra)&&
                    id.starts_with("wire_")&&id.size()==29&&hex_chars(id.substr(5))&&
                    c.receipt_question.contains(id)&&c.receipt_question.at(id)==ticket&&
                    pin.size()==64&&hex_chars(pin)&&packet.size()==64&&hex_chars(packet),
                    "invalid durable question answer receipt");
            Parser s{source};require(s.name()==source&&source.size()<=24,"invalid durable answer source");s.end();
            require(c.wire_receipts.emplace(id,WireReceipt{ticket,source,pin,packet}).second,
                    "duplicate durable question answer receipt");
        }
        else if(e.starts_with("answer_bundle ")){
            istringstream in(e.substr(14));string ticket,id,request,package,proof,extra;
            const auto hash=[](const string& h){return h.size()==64&&hex_chars(h);};
            require(bool(in>>ticket>>id>>request>>package>>proof)&&!(in>>extra)&&
                    id.starts_with("bundle_")&&id.size()==31&&hex_chars(id.substr(7))&&
                    c.receipt_question.contains(id)&&c.receipt_question.at(id)==ticket&&
                    !c.events.empty()&&c.events.back()=="answer "+ticket+" "+id&&
                    hash(request)&&hash(package)&&hash(proof),"invalid durable CL bundle receipt");
            require(c.bundle_receipts.emplace(id,BundleReceipt{ticket,request,package,proof}).second,
                    "duplicate durable CL bundle receipt");
        }
        else if(e.starts_with("answer_frozen ")){
            istringstream in(e.substr(14));string id,artifact,snapshot,extra;
            require(bool(in>>id>>artifact>>snapshot)&&!(in>>extra)&&artifact.size()==64&&snapshot.size()==64&&
                    hex_chars(artifact)&&hex_chars(snapshot)&&c.bundle_receipts.contains(id)&&!c.events.empty()&&
                    c.events.back().starts_with("answer_bundle "+c.bundle_receipts.at(id).ticket+" "+id+" "),
                    "invalid durable frozen CL receipt provenance");
            require(c.frozen_receipts.emplace(id,make_pair(artifact,snapshot)).second,"duplicate frozen CL evidence origin");
        }
        else if(e.starts_with("answer_workspace ")){
            istringstream in(e.substr(17));string id,lock,extra;
            require(bool(in>>id>>lock)&&!(in>>extra)&&lock.size()==64&&hex_chars(lock)&&
                    c.bundle_receipts.contains(id)&&!c.events.empty()&&
                    c.events.back().starts_with("answer_bundle "+c.bundle_receipts.at(id).ticket+" "+id+" "),
                    "invalid durable workspace evidence provenance");
            require(c.workspace_answer_locks.emplace(id,lock).second,"duplicate workspace evidence origin");
        }
        else if(e.starts_with("answer_assessment ")){
            istringstream in(e.substr(18));string id,hex,extra;
            require(bool(in>>id>>hex)&&!(in>>extra)&&c.bundle_receipts.contains(id),"invalid evidence assessment reference");
            const auto value=from_hex(hex);
            require(value.size()<=12000&&value.starts_with("{\"schema\":\"pcgm-decision-v1\",")&&value.ends_with('}')&&
                    c.bundle_assessments.emplace(id,value).second,"invalid evidence assessment payload");
        }
        else if(e.starts_with("choice_intent ")){
            istringstream row(e.substr(14));string id,digest,event,extra;
            require(bool(row>>id>>digest>>event)&&!(row>>extra)&&id.size()==33&&id[0]=='d'&&hex_chars(id.substr(1))&&
                    digest.size()==64&&hex_chars(digest)&&c.choice_intents.size()<12&&c.pins.size()<32&&
                    !c.choice_outcomes.contains(id)&&sequence_number(event)==c.events.size()&&
                    std::ranges::none_of(c.choice_intents,[&](const auto& x){
                        return !c.cancelled_intents.contains(x.first)&&!c.choice_outcomes.contains(x.first);
                    }),"invalid durable choice intent");
            const Pin basis{digest,sequence_number(event)};
            require(c.choice_intents.emplace(id,basis).second&&c.pins.emplace("intent_"+id,basis).second,
                    "duplicate durable choice intent");
        }
        else if(e.starts_with("choice_intent_rebound ")){
            istringstream row(e.substr(22));string id,old,fresh,event,extra;
            require(bool(row>>id>>old>>fresh>>event)&&!(row>>extra)&&fresh.size()==64&&hex_chars(fresh)&&
                    c.choice_intents.contains(id)&&!c.choice_outcomes.contains(id)&&!c.cancelled_intents.contains(id)&&
                    !c.choice_rebound_intents.contains(id)&&c.pins.size()<32&&
                    c.choice_intents.at(id).digest==old&&sequence_number(event)==c.events.size()&&
                    choice_owner_only_tail(c.events,c.choice_intents.at(id).events+1),"invalid durable choice ownership rebind");
            const Pin basis{fresh,sequence_number(event)};
            require(c.choice_rebound_intents.emplace(id,basis).second&&c.pins.emplace("rebound_"+id,basis).second,
                    "duplicate durable choice ownership rebind");
        }
        else if(e.starts_with("cancel_choice_intent ")){
            const auto id=e.substr(21);
            require(c.choice_intents.contains(id)&&!c.choice_outcomes.contains(id)&&c.cancelled_intents.insert(id).second,
                    "invalid durable choice intent cancellation");
        }
        else if(e.starts_with("choice_outcome ")){
            istringstream line(e.substr(15));string id,basis,kind,hex,extra;
            require(bool(line>>id>>basis>>kind>>hex)&&!(line>>extra)&&id.size()==33&&id[0]=='d'&&hex_chars(id.substr(1))&&
                    basis.size()==64&&hex_chars(basis)&&c.choice_outcomes.size()<128,"invalid durable choice job address");
            require(kind=="committed"||kind=="unchanged","invalid durable choice job outcome");
            const auto receipt=from_hex(hex);
            require(receipt.size()<=12000&&receipt.starts_with("{\"schema\":\"pcgm-decision-v1\",")&&receipt.ends_with('}')&&
                    receipt.find("\"trigger\":\"live_job:"+id+"\"")!=string::npos,
                    "durable choice job receipt does not match its address");
            if(kind=="committed"){
                require(std::ranges::any_of(c.decision_traces,[&](const auto& one){return one.second==receipt;}),
                        "durable choice job has no matching committed decision");
            }else require(receipt.find("\"status\":\"committed\"")==string::npos,
                          "durable no-change receipt cannot claim commit");
            require(c.choice_outcomes.emplace(id,ChoiceOutcome{basis,kind,receipt}).second,"duplicate durable choice job receipt");
        }
        else if(e.starts_with("choice_basis ")){
            istringstream line(e.substr(13));string id,hash,count,extra;
            require(bool(line>>id>>hash>>count)&&!(line>>extra)&&c.choice_outcomes.contains(id)&&
                    c.choice_outcomes.at(id).basis==hash&&c.pins.size()<32,"invalid archived choice basis");
            const auto events=sequence_number(count);
            require(events<c.events.size(),"archived choice basis does not precede its outcome");
            require(c.choice_bases.insert(id).second&&c.pins.emplace("basis_"+id,Pin{hash,events}).second,
                    "duplicate archived choice basis");
        }
        else if(e.starts_with("watch ")){
            Parser q{e.substr(6)};const auto name=q.name();auto fact=q.atom();q.end();
            require(!fact.pred.starts_with("!")&&std::ranges::none_of(fact.args,variable)&&
                    c.watches.size()<32&&c.watches.emplace(name,fact).second,
                    "invalid evidence watch");
        }
        else if(e.starts_with("unwatch ")){
            Parser q{e.substr(8)};const auto name=q.name();q.end();
            require(c.watches.erase(name)==1,"invalid watch removal");
        }
        else if(e.starts_with("notice ")||e.starts_with("notice2 ")){
            const bool stable=e.starts_with("notice2 ");
            istringstream in(e.substr(stable?8:7));string name,goal,first,second,a,b,extra;
            require(bool(in>>name>>goal>>first>>second>>a>>b)&&!(in>>extra)&&c.watches.contains(name)&&
                    a.size()==64&&b.size()==64&&a!=b&&hex_chars(a)&&hex_chars(b),"invalid stored notice");
            Parser q{goal};const auto fact=q.atom();q.end();
            require(fact==c.watches.at(name),"notice does not match active watch");
            const set<string> truths{"UNKNOWN","POSITIVE","NEGATIVE","CONFLICT"};
            require(truths.contains(first)&&truths.contains(second),"invalid watched truth state");
            c.notices.push_back({static_cast<unsigned>(c.events.size()+1),name,fact,first,second,a,b,stable?2U:1U});
        }
        else if(e.starts_with("artifact ")){
            istringstream args(e.substr(9));string name,digest,extra;
            require(bool(args>>name>>digest)&&!(args>>extra)&&digest.size()==64&&hex_chars(digest),
                    "invalid artifact receipt");
            Parser q{name};q.name();q.end();
            require(c.artifacts.emplace(name,digest).second,"duplicate artifact receipt");
            ++c.epoch;
        }
        else if(e.starts_with("artifact_generated ")||e.starts_with("artifact_generated_revision ")){
            const bool generated_revision=e.starts_with("artifact_generated_revision ");
            istringstream in(e.substr(generated_revision?28:19));string alias,profile,source,image,extra;
            require(bool(in>>alias>>profile>>source>>image)&&!(in>>extra)&&
                profile.size()==64&&source.size()==64&&image.size()==64&&
                hex_chars(profile)&&hex_chars(source)&&hex_chars(image)&&!c.events.empty()&&
                c.artifacts.contains(alias)&&c.artifacts.at(alias)==image,"invalid native compiler artifact origin");
            const auto& last=c.events.back();
            if(generated_revision){
                require(c.generated_artifacts.contains(alias)&&last.starts_with("artifact_switch "+alias+" ")&&last.ends_with(" "+image),
                        "generated IR revision lacks a paired artifact switch");
            }else require(!c.generated_artifacts.contains(alias)&&last=="artifact "+alias+" "+image,"generated IR origin lacks installation");
            auto& versions=c.generated_artifacts[alias];
            require(versions.size()<4&&versions.emplace(image,CompilerOrigin{profile,source,image}).second,
                    "duplicate or excessive generated IR provenance");
        }
        else if(e.starts_with("artifact_synthesized ")){
            istringstream in(e.substr(21));string alias,image,generator,scope,evidence,extra;
            require(bool(in>>alias>>image>>generator>>scope>>evidence)&&!(in>>extra)&&
                image.size()==64&&generator.size()==64&&scope.size()==64&&evidence.size()==64&&
                hex_chars(image)&&hex_chars(generator)&&hex_chars(scope)&&hex_chars(evidence)&&
                c.generated_artifacts.contains(alias)&&c.generated_artifacts.at(alias).contains(image)&&
                c.artifacts.at(alias)==image&&!c.events.empty()&&c.events.back().ends_with(" "+image)&&
                (c.events.back().starts_with("artifact_generated "+alias+" ")||
                 c.events.back().starts_with("artifact_generated_revision "+alias+" ")),
                "invalid synthesized artifact provenance receipt");
            require(c.synthesized_artifacts[alias].emplace(image,SynthesisOrigin{generator,scope,evidence}).second,
                "duplicate synthesized artifact provenance");
        }
        else if(e.starts_with("artifact_package ")){
            istringstream args(e.substr(17));string name,outer,inner,extra;
            require(bool(args>>name>>outer>>inner)&&!(args>>extra)&&outer.size()==64&&inner.size()==64&&
                    hex_chars(outer)&&hex_chars(inner)&&!c.events.empty()&&c.events.back()=="artifact "+name+" "+inner,
                    "invalid CL package origin receipt");
            require(c.installed_packages.emplace(name,make_pair(outer,inner)).second,"duplicate CL package origin");
            c.package_versions[name].emplace(outer,inner);
        }
        else if(e.starts_with("artifact_switch ")){
            istringstream args(e.substr(16));string name,prior,next,extra;
            require(bool(args>>name>>prior>>next)&&!(args>>extra)&&
                prior.size()==64&&next.size()==64&&prior!=next&&hex_chars(prior)&&hex_chars(next),
                "invalid artifact switch receipt");
            const auto it=c.artifacts.find(name);
            require(it!=c.artifacts.end()&&it->second==prior,"artifact switch prior version mismatch");
            auto& retained=c.artifact_versions[name];
            retained.insert(prior);retained.insert(next);
            require(retained.size()<=4,"retained artifact version limit");
            it->second=next;++c.epoch;
        }
        else if(e.starts_with("artifact_package_contract ")){
            istringstream in(e.substr(26));string name,digest,extra;
            require(bool(in>>name>>digest)&&!(in>>extra)&&digest.size()==64&&hex_chars(digest)&&
                    !c.events.empty()&&c.events.back().starts_with("artifact_package "+name+" ")&&
                    c.package_contracts.emplace(name,digest).second,"invalid CL package contract receipt");
        }
        else if(e.starts_with("artifact_package_retained ")){
            istringstream in(e.substr(26));string name,outer,inner,extra;
            require(bool(in>>name>>outer>>inner)&&!(in>>extra)&&outer.size()==64&&inner.size()==64&&
                    hex_chars(outer)&&hex_chars(inner)&&c.package_versions.contains(name)&&c.package_contracts.contains(name)&&
                    c.artifacts.at(name)==inner&&!c.events.empty()&&
                    c.events.back().starts_with("artifact_switch "+name+" ")&&c.events.back().ends_with(" "+inner),
                    "invalid retained CL package receipt");
            auto& history=c.package_versions.at(name);
            require(history.size()<4&&history.emplace(outer,inner).second,"duplicate or excessive CL package history");
        }
        else if(e.starts_with("artifact_scope ")){
            istringstream in(e.substr(15));string alias,outer,profile,report,extra;
            const auto hash=[](const string& h){return h.size()==64&&hex_chars(h);};
            require(bool(in>>alias>>outer>>profile>>report)&&!(in>>extra)&&hash(outer)&&hash(profile)&&hash(report)&&
                    !c.workspace_locks.contains(alias)&&
                    c.package_versions.contains(alias)&&c.package_versions.at(alias).contains(outer)&&
                    c.artifacts.at(alias)==c.package_versions.at(alias).at(outer),"invalid CL module scope receipt");
            const auto [policy,created]=c.scope_policies.try_emplace(alias,profile);
            require(policy->second==profile&&(!created||c.package_versions.at(alias).size()==1),
                    "CL module scope pin changed or was attached retrospectively");
            require(!c.events.empty()&&(created?
                     c.events.back().starts_with("artifact_package_contract "+alias+" "):
                     c.events.back()=="artifact_package_retained "+alias+" "+outer+" "+c.artifacts.at(alias)),
                    "CL module scope receipt is not attached to its new package");
            require(c.scope_origins[alias].emplace(outer,ScopeOrigin{profile,report}).second,"duplicate CL scope attestation");
        }
        else if(e.starts_with("artifact_workspace_candidate ")||e.starts_with("artifact_workspace_source ")){
            const bool from_source=e.starts_with("artifact_workspace_source ");
            istringstream in(e.substr(from_source?26:29));string alias,prior,old_lock,new_lock,outer,image,report,source,extra;
            const auto hash=[](const string& h){return h.size()==64&&hex_chars(h);};
            require(bool(in>>alias>>prior>>old_lock>>new_lock>>outer>>image>>report)&&
                    (!from_source||(bool(in>>source)&&hash(source)))&&!(in>>extra)&&hash(prior)&&
                    hash(old_lock)&&hash(new_lock)&&(from_source?old_lock==new_lock:old_lock!=new_lock)&&
                    hash(outer)&&hash(image)&&hash(report)&&
                    c.workspace_locks.contains(alias)&&c.artifacts.at(alias)==prior,
                    "invalid admitted CL workspace dependency candidate");
            auto& versions=c.package_versions.at(alias);
            auto& details=c.workspace_origins.at(alias);
            require(std::ranges::any_of(versions,[&](const auto& row){
                return row.second==prior&&details.at(row.first).profile==old_lock;
            }),"workspace dependency candidate did not pin its prior active lock");
            require(versions.size()<4&&std::ranges::none_of(versions,[&](const auto& row){return row.second==image;})&&
                    versions.emplace(outer,image).second&&details.emplace(outer,ScopeOrigin{new_lock,report}).second,
                    "invalid or duplicate workspace dependency candidate");
            auto& retained=c.artifact_versions[alias];
            retained.insert(prior);retained.insert(image);
            require(retained.size()<=4,"retained workspace dependency capacity");
            c.workspace_authorized[alias].insert(new_lock);
            if(from_source)require(c.workspace_source_origins[alias].emplace(outer,source).second,"duplicate CL workspace source origin");
        }
        else if(e.starts_with("workspace_version_contract ")){
            istringstream in(e.substr(27));string alias,outer,digest,extra;
            require(bool(in>>alias>>outer>>digest)&&!(in>>extra)&&outer.size()==64&&digest.size()==64&&
                    hex_chars(outer)&&hex_chars(digest)&&c.workspace_origins.contains(alias)&&
                    c.workspace_origins.at(alias).contains(outer)&&digest!=c.package_contracts.at(alias)&&
                    !c.events.empty()&&
                    (c.events.back().starts_with("artifact_workspace_source "+alias+" ")||
                    c.events.back().starts_with("artifact_workspace_candidate "+alias+" ")||
                    c.events.back().starts_with("artifact_workspace "+alias+" "))&&
                    c.events.back().find(" "+outer+" ")!=string::npos,
                    "invalid CL workspace version-specific contract");
            require(c.workspace_version_contracts[alias].emplace(outer,digest).second,
                    "duplicate CL workspace version-specific contract");
        }
        else if(e.starts_with("workspace_additive_edge ")){
            istringstream in(e.substr(24));string alias,before,after,outer,goals,extra;
            const auto hash=[](const string& h){return h.size()==64&&hex_chars(h);};
            require(bool(in>>alias>>before>>after>>outer>>goals)&&!(in>>extra)&&
                    hash(before)&&hash(after)&&hash(outer)&&hash(goals)&&before!=after&&
                    c.artifacts.contains(alias)&&c.artifacts.at(alias)==before&&c.workspace_source_origins.contains(alias)&&
                    c.workspace_source_origins.at(alias).contains(outer)&&c.package_versions.at(alias).at(outer)==after&&
                    !c.events.empty(),"invalid CL additive candidate provenance");
            const auto prior_marker="workspace_version_contract "+alias+" "+outer+" ";
            const size_t distance=c.events.back().starts_with(prior_marker)?2:1;
            require(c.events.size()>=distance&&
                    c.events.at(c.events.size()-distance).starts_with("artifact_workspace_source "+alias+" "+before+" ")&&
                    c.events.at(c.events.size()-distance).find(" "+outer+" "+after+" ")!=string::npos,
                    "CL additive edge not adjacent to its exact verified retention");
            require(c.workspace_additive_edges[alias].emplace(make_pair(before,after),goals).second,
                    "duplicate CL additive candidate edge");
        }
        else if(e.starts_with("workspace_recipe_origin ")){
            istringstream in(e.substr(24));string alias,outer,recipe,scope,evidence,extra;
            const auto hash=[](const string& h){return h.size()==64&&hex_chars(h);};
            require(bool(in>>alias>>outer>>recipe>>scope>>evidence)&&!(in>>extra)&&hash(outer)&&hash(recipe)&&hash(scope)&&hash(evidence)&&
                    c.workspace_source_origins.contains(alias)&&c.workspace_source_origins.at(alias).contains(outer)&&
                    !c.events.empty()&&c.events.back().starts_with("artifact_workspace_source "+alias+" "),
                    "invalid native CL workspace recipe provenance");
            require(c.workspace_recipe_origins[alias].emplace(outer,RecipeOrigin{recipe,scope,evidence}).second,
                    "duplicate native CL workspace recipe provenance");
        }
        else if(e.starts_with("workspace_recipe_proof ")){
            istringstream in(e.substr(23));string alias,outer,base,encoded,extra;
            const auto hash=[](const string& h){return h.size()==64&&hex_chars(h);};
            require(bool(in>>alias>>outer>>base>>encoded)&&!(in>>extra)&&hash(outer)&&hash(base)&&
                    c.workspace_recipe_origins.contains(alias)&&c.workspace_recipe_origins.at(alias).contains(outer)&&
                    !c.events.empty()&&c.events.back().starts_with("workspace_recipe_origin "+alias+" "+outer+" ")&&
                    c.package_versions.at(alias).contains(base)&&c.package_versions.at(alias).at(base)==c.artifacts.at(alias)&&
                    base!=outer,"invalid original native CL recipe proof address or prior version");
            const auto bytes=from_hex(encoded);
            require(sha256(bytes)==c.workspace_recipe_origins.at(alias).at(outer).evidence,"native CL recipe proof digest changed");
            istringstream lines(bytes);string line,prior,canonical="CLWPROOFS-1\n";
            require(bool(getline(lines,line))&&line=="CLWPROOFS-1","invalid native CL receipt bundle");
            map<string,Atom> facts;set<string> sources;
            while(getline(lines,line)){
                istringstream row(line);string port,source,serial,pin,id,fact,leftover;
                require(bool(row>>port>>source>>serial>>pin>>id>>fact)&&!(row>>leftover)&&port>prior&&facts.size()<8,
                        "invalid ordered native CL receipt proof row");
                Parser qp{port};qp.name();qp.end();
                Parser qs{source};qs.name();qs.end();
                prior=port;
                const auto sequence=sequence_number(serial);
                const auto cycle=c.cycles.find({source,sequence});
                require(cycle!=c.cycles.end()&&cycle->second.digest==pin&&c.last_cycle.at(source)==sequence&&
                        !c.autopause.contains(source)&&!c.inactive.contains(id)&&c.recorded_observations.contains(id),
                        "native CL recipe proof has no exact eligible original source receipt");
                const auto prefix="sensor_"+source+"_"+serial+"_";
                require(id.starts_with(prefix),"native CL proof observation not from claimed source");
                const auto index=sequence_number(id.substr(prefix.size()));
                require(index>0&&index<=cycle->second.observations,"native CL proof observation not from claimed receipt");
                Parser a{fact};auto datum=a.atom();a.end();
                require(!datum.pred.starts_with("!")&&show(datum)==fact&&facts.emplace(id,std::move(datum)).second,
                        "invalid or repeated native CL proof observation");
                sources.insert(source);
                canonical+=port+" "+source+" "+serial+" "+pin+" "+id+" "+fact+"\n";
            }
            require(sources.size()>=2&&bytes==canonical&&
                    c.workspace_proof_origins[alias].emplace(outer,WorkspaceProofOrigin{base,bytes,std::move(facts)}).second,
                    "invalid or duplicate native CL receipt proof");
        }
        else if(e.starts_with("artifact_workspace ")){
            istringstream in(e.substr(19));string alias,outer,lock,report,extra;
            const auto hash=[](const string& h){return h.size()==64&&hex_chars(h);};
            require(bool(in>>alias>>outer>>lock>>report)&&!(in>>extra)&&hash(outer)&&hash(lock)&&hash(report)&&
                    !c.scope_policies.contains(alias)&&c.package_versions.contains(alias)&&c.package_versions.at(alias).contains(outer)&&
                    c.artifacts.at(alias)==c.package_versions.at(alias).at(outer),"invalid native CL workspace receipt");
            const auto [policy,created]=c.workspace_locks.try_emplace(alias,lock);
            if(created){
                require(policy->second==lock&&c.package_versions.at(alias).size()==1,"initial CL workspace lock invalid");
                c.workspace_authorized[alias].insert(lock);
            }else require(c.workspace_authorized.at(alias).contains(lock),"CL workspace lock had no authorized admission");
            require(!c.events.empty()&&(created?
                    c.events.back().starts_with("artifact_package_contract "+alias+" "):
                    c.events.back()=="artifact_package_retained "+alias+" "+outer+" "+c.artifacts.at(alias)),
                    "CL workspace receipt is not paired with its verified package");
            require(c.workspace_origins[alias].emplace(outer,ScopeOrigin{lock,report}).second,"duplicate CL workspace receipt");
        }
        else if(e.starts_with("archive_seal ")){
            istringstream in(e.substr(13));string first,last,prior,digest,snapshot,extra;
            require(bool(in>>first>>last>>prior>>digest>>snapshot)&&!(in>>extra)&&
                    prior.size()==64&&digest.size()==64&&snapshot.size()==64&&
                    hex_chars(prior)&&hex_chars(digest)&&hex_chars(snapshot),"invalid archive segment receipt");
            const auto lo=sequence_number(first),hi=sequence_number(last);
            const auto required= c.archives.empty()?1:c.archives.back().last+1;
            const auto prev=c.archives.empty()?string(64,'0'):c.archives.back().digest;
            require(c.archives.size()<archive_count_limit&&lo==required&&lo<=hi&&hi<=c.events.size()&&hi-lo<128&&prior==prev,
                    "archive segment is not a contiguous anchored range");
            c.archives.push_back({lo,hi,prior,digest,snapshot});
        }
        else if(e.starts_with("pin ")){
            istringstream in(e.substr(4));string label,digest,count,extra;
            require(bool(in>>label>>digest>>count)&&!(in>>extra)&&digest.size()==64&&hex_chars(digest),
                    "invalid evidence pin");
            Parser key{label};key.name();key.end();
            const auto n=sequence_number(count);
            require(n==c.events.size()&&c.pins.size()<32&&c.pins.emplace(label,Pin{digest,n}).second,
                    "invalid or duplicate evidence pin");
        }
        else if(e.starts_with("dialogue ")){
            istringstream in(e.substr(9));string sid,tid,request,focus,reply,extra;
            require(bool(in>>sid>>tid>>request>>focus>>reply)&&!(in>>extra),"invalid dialogue receipt");
            Parser s{sid},t{tid};s.name();s.end();t.name();t.end();
            require(c.dialogues.size()<native_dialogue_session_limit||c.dialogues.contains(sid),"persisted dialogue session limit");
            auto& session=c.dialogues[sid];
            require(session.turns.size()<native_dialogue_turn_limit&&session.turns.emplace(tid,LocalTurn{from_hex(request),from_hex(reply)}).second,
                    "invalid repeated dialogue receipt");
            if(focus=="-")session.focus.reset();
            else{
                Parser topic{from_hex(focus)};auto a=topic.atom();topic.end();
                require(!a.pred.starts_with("!")&&std::ranges::none_of(a.args,variable),"invalid persisted topic");
                session.focus=std::move(a);
            }
            session.order.push_back(tid);
        }
        else if(e.starts_with("scene ")||e.starts_with("experience ")){
            const bool scene=e.starts_with("scene ");
            Parser q{e.substr(scene?6:11)};const auto event=q.name(), label=q.name();q.end();
            require(event.starts_with("e"),"invalid historical decision ID");
            const auto id=sequence_number(event.substr(1));
            require(id>0&&id<=c.events.size()&&c.events.at(id-1).starts_with("decision "),
                    "memory event references a missing decision");
            if(scene)require(id==c.events.size(),"decision scene must immediately follow its decision");
            else require(c.recorded_observations.contains(label)&&
                count_if(c.events.begin(),c.events.end(),[](const string& text){return text.starts_with("experience ");})<128,
                "experience refers to an unrecorded observation or exceeds the limit");
        }
        else if(e.starts_with("experience_wire ")||e.starts_with("experience_measured ")){
            const bool measured=e.starts_with("experience_measured ");
            Parser row{e.substr(measured?20:16)};
            const auto decision=row.name(),source=row.name();
            const auto serial=sequence_number(row.term()),index=sequence_number(row.term());
            if(measured){
                const auto result=row.name();
                require((result=="success"||result=="failure")&&c.measured_strength.emplace(decision,result=="success"?1:-1).second,
                        "measured outcome history must pin its original sign");
            }
            row.end();
            const auto receipt=c.cycles.find({source,serial});
            require(receipt!=c.cycles.end()&&index>0&&index<=receipt->second.observations&&
                    !c.events.empty()&&c.events.back()=="experience "+decision+" "+cycle_obs_id(source,serial,index)&&
                    (measured?c.measured_from_cycle:c.learned_from_cycle).emplace(decision,make_tuple(source,serial,index)).second,
                    "automatic experience is not bound to an original outcome receipt");
        }
        else if(e.starts_with("measurement_basis ")){
            istringstream item(e.substr(18));string id,digest,count,extra;
            require(bool(item>>id>>digest>>count)&&!(item>>extra)&&digest.size()==64&&hex_chars(digest)&&
                    c.measured_from_cycle.contains(id)&&c.measurement_bases.size()<32&&
                    !c.events.empty()&&c.events.back().starts_with("experience_measured "+id+" "),
                    "measurement basis does not identify its original assessment");
            const auto n=sequence_number(count);
            require(n>0&&n+2<=c.events.size()&&c.measurement_bases.emplace(id,Pin{digest,n}).second,
                    "invalid original measurement basis cursor");
        }
        else if(e.starts_with("decision ")){
            istringstream in(e.substr(9));string kind,id,digest,wishes,risk,cost,extra;
            require(bool(in>>kind>>id>>digest>>wishes>>risk>>cost)&&!(in>>extra)&&
                    (kind=="rewrite"||kind=="rollback"||kind=="artifact")&&digest.size()==64&&hex_chars(digest),
                    "invalid decision receipt");
            require(sequence_number(wishes)<=64&&sequence_number(risk)<=64&&sequence_number(cost)<=256,
                    "invalid decision scores");
            if(kind=="artifact"){
                const auto sep=id.find(':');
                require(sep!=string::npos,"invalid decided artifact identity");
                const auto alias=id.substr(0,sep),target=id.substr(sep+1);
                require(c.artifacts.contains(alias)&&c.artifacts.at(alias)==target&&!c.events.empty(),
                    "decision receipt lacks active artifact");
                auto last=c.events.size();
                if(last&&c.events[last-1].starts_with("artifact_synthesized "+alias+" "+target+" "))--last;
                if(last&&c.events[last-1].starts_with("artifact_generated_revision "+alias+" ")&&
                   c.events[last-1].ends_with(" "+target))--last;
                require(last&&c.events[last-1].starts_with("artifact_switch "+alias+" ")&&
                        c.events[last-1].ends_with(" "+target),"decision receipt lacks the paired artifact switch");
            }else{
                require(c.plans.contains(id),"decision receipt lacks a known rule plan");
                const auto& plan=c.plans.at(id);
                require(plan.applied&&(plan.reverted==(kind=="rollback")),"decision receipt lacks revision");
            }
        }
        else if(e.starts_with("decision_trace ")){
            istringstream payload(e.substr(15));string ref,raw,extra;
            require(bool(payload>>ref>>raw)&&!(payload>>extra)&&ref.starts_with('e'),"invalid decision trace receipt");
            const auto id=sequence_number(ref.substr(1));
            require(id>0&&id<=c.events.size()&&c.events.at(id-1).starts_with("decision ")&&
                (id==c.events.size()||(id+1==c.events.size()&&c.events.back().starts_with("scene "))),
                "decision trace not adjacent to a decision");
            const auto receipt=from_hex(raw);
            require(receipt.size()<=12000&&receipt.starts_with("{\"schema\":\"pcgm-decision-v1\",")&&
                    receipt.ends_with('}')&&c.decision_traces.emplace(ref,receipt).second,
                    "invalid structured decision trace");
        }
        else if(e.starts_with("autopause ")||e.starts_with("autoresume ")){
            const bool pausing=e.starts_with("autopause ");
            Parser q{e.substr(pausing?10:11)};const auto channel=q.name();q.end();
            const bool changed=pausing?c.autopause.insert(channel).second:c.autopause.erase(channel)!=0;
            require(changed,"invalid automatic mode transition");
        }
        else if(e.starts_with("automatic ")){
            istringstream in(e.substr(10));string src,seq,status,reason,extra;
            require(bool(in>>src>>seq>>status>>reason)&&!(in>>extra),"invalid automatic receipt");
            const CycleKey key{src,sequence_number(seq)};
            require(c.cycles.contains(key)&&(status=="blocked"||status=="no_change"||status=="paused"||status=="rolled_back"||status=="version_switched"||status=="stay"||status=="undecided"||
                    (c.plans.contains(status)&&c.plans.at(status).applied)),"automatic receipt missing prerequisite");
            auto detail=from_hex(reason);if(detail=="-")detail.clear();
            require(c.automatic.emplace(key,AutoReceipt{status,detail}).second,"duplicate automatic receipt");
        }
        else if(e.starts_with("observation_batch ")){
            require(!reading,"unexpected observation batch in a sensor cycle");
            const auto raw=from_hex(e.substr(18));
            const auto parsed=parse_observation_batch(raw);
            require(c.observation_batches.size()<128&&c.observation_version<=10000-parsed.edits.size(),
                    "durable observation batch retention or version limit");
            const auto changes=static_cast<unsigned>(parsed.edits.size());
            const auto position=static_cast<unsigned>(c.events.size()+1+changes);
            require(c.observation_batches.emplace(parsed.id,ObservationBatchReceipt{
                parsed.basis,sha256(raw),position,c.observation_version+changes,changes}).second,
                "duplicate durable observation batch");
            for(const auto& item:parsed.edits)if(item.fact)
                require(c.observation_batch_facts.emplace(item.id,*item.fact).second,
                        "duplicate observation in durable batch history");
            if(parsed.audited)
                require(c.observation_batch_audit_bases.size()<16&&
                        c.observation_batch_audit_bases.emplace(parsed.id,Pin{parsed.basis,static_cast<unsigned>(c.events.size())}).second,
                        "durable observation audit retention limit or duplicate basis");
            pending_batch=parsed.edits;batch_edit=0;
        }
        else if(e.starts_with("observe ")){
            Parser q{e.substr(8)};
            const auto id=q.name(); q.end();
            require(c.recorded_observations.insert(id).second,"duplicate recorded observation");
            ++c.observation_version;
        }
        else if(e.starts_with("install ")){
            Parser q{e.substr(8)};
            const auto name=q.name(); q.end();
            require(c.modules.insert(name).second,"duplicate persistent module");
            ++c.epoch;
        }
        else {
            const bool withdraw=e.starts_with("withdraw ");
            require(withdraw || e.starts_with("restore "),"invalid persistent event");
            Parser q{e.substr(withdraw?9:8)};
            const auto id=q.name(); q.end();
            const bool change=withdraw?c.inactive.insert(id).second:c.inactive.erase(id)!=0;
            require(change,"inconsistent persistent evidence history");
            ++c.observation_version;
        }
        c.events.push_back(e);
    }
    for(const auto& [alias,profile]:c.scope_policies){
        const auto& origins=c.scope_origins.at(alias);
        const auto& versions=c.package_versions.at(alias);
        require(origins.size()==versions.size()&&std::ranges::any_of(versions,[&](const auto& pair){
            return pair.second==c.artifacts.at(alias)&&origins.contains(pair.first);
        }),"scoped CL artifact contains an unattested version");
        for(const auto& [outer,scope]:origins)
            require(scope.profile==profile&&versions.contains(outer),"scoped CL artifact policy differs");
    }
    for(const auto& [alias,lock]:c.workspace_locks){
        const auto& origins=c.workspace_origins.at(alias);
        const auto& versions=c.package_versions.at(alias);
        require(origins.size()==versions.size()&&std::ranges::any_of(versions,[&](const auto& pair){
            return pair.second==c.artifacts.at(alias)&&origins.contains(pair.first);
        }),"CL workspace contains an unattested version");
        for(const auto& [outer,scope]:origins)
            require(c.workspace_authorized.at(alias).contains(scope.profile)&&versions.contains(outer),
                    "CL workspace dependency lock differs");
        require(c.workspace_authorized.at(alias).contains(lock),"initial CL workspace dependency lock lost");
    }
    c.source=s.substr(p);
    return c;
}

string sha256(const string& input);
struct CommitIndeterminate : runtime_error { using runtime_error::runtime_error; };
string workspace_active_lock(const Continuity& state,const string& alias){
    require(state.workspace_locks.contains(alias),"unknown scoped CL workspace");
    for(const auto& [outer,image]:state.package_versions.at(alias))
        if(image==state.artifacts.at(alias))return state.workspace_origins.at(alias).at(outer).profile;
    throw runtime_error("current CL workspace has no verified lock");
}
string workspace_contract_by_archive(const Continuity& state,const string& alias,const string& outer){
    if(const auto values=state.workspace_version_contracts.find(alias);values!=state.workspace_version_contracts.end()){
        if(const auto match=values->second.find(outer);match!=values->second.end())return match->second;
    }
    if(const auto known=state.workspace_additive_edges.find(alias);known!=state.workspace_additive_edges.end()){
        const auto& image=state.package_versions.at(alias).at(outer);
        if(std::ranges::any_of(known->second,[&](const auto& entry){return entry.first.second==image;}))return {};
    }
    return state.package_contracts.at(alias);
}
string workspace_contract_by_image(const Continuity& state,const string& alias,const string& image){
    const auto& history=state.package_versions.at(alias);
    for(const auto& [outer,inner]:history)if(inner==image){
        auto contract=workspace_contract_by_archive(state,alias,outer);
        return contract.empty()?"unbound_"+image:contract;
    }
    throw runtime_error("CL workspace image has no verified public contract");
}
void retain_workspace_contract(Continuity& state,const string& alias,const string& outer,const string& api){
    if(api==state.package_contracts.at(alias))return;
    require(state.workspace_version_contracts[alias].emplace(outer,api).second,"duplicate retained workspace API contract");
    state.events.push_back("workspace_version_contract "+alias+" "+outer+" "+api);
}
struct SegmentStamp {
    uint64_t device;
    uint64_t inode;
    int64_t size;
    int64_t modified,modified_ns,changed,changed_ns;
    auto operator<=>(const SegmentStamp&) const = default;
};
struct SegmentCacheEntry {SegmentStamp stamp;shared_ptr<const string> bytes;size_t recent;};
struct SegmentReadCache {
    map<string,SegmentCacheEntry> entries;
    size_t held=0,tick=0,hits=0,reads=0,verified_bytes=0;
    void clear(){entries.clear();held=0;}
};
string compact_transfer_state(const Continuity& state);
string expand_compact_transfer(const fs::path& history,const string& compact);
string expand_compact_transfer(int history,const string& compact,SegmentReadCache* cache=nullptr);
vector<Pin> transferable_pins(const Continuity& state){
    vector<Pin> result;
    for(const auto& [_,pin]:state.pins)result.push_back(pin);
    for(const auto& [_,pin]:state.measurement_bases)result.push_back(pin);
    for(const auto& [_,pin]:state.observation_batch_audit_bases)result.push_back(pin);
    return result;
}

struct StateStore {
    fs::path dst;
    Descriptor dir;
    Descriptor lease;
    bool compacted=false;
    SegmentReadCache archive_cache;
    string physical_sha256;
    size_t physical_bytes=0,logical_bytes=0;
    explicit StateStore(fs::path target,bool writer=true)
        :dst(fs::absolute(std::move(target))),
         dir(native_os::open_directory(dst.parent_path())),
         lease(writer?native_os::open_lock(dir.fd,dst.filename().string()+".lock"):-1){
        require(dir.fd>=0,"cannot open state directory");
        if(writer)native_os::acquire_lock(lease.fd,"cannot open state lock","state lock must be a regular file",
                                         "state already has a writer or lock unavailable");
    }
    void check_directory()const{
        native_os::confirm_directory(dir.fd,dst.parent_path(),"persistent state directory moved; reopen using its intended path");
    }
    native_os::AnchoredAssets asset_folder(const string& suffix,bool create=false,bool optional=false)const{
        check_directory();
        require(!create||lease.fd>=0,"state opened without a writer lease");
        return native_os::AnchoredAssets(dir.fd,dst.filename().string()+suffix,create,optional);
    }
    native_os::AnchoredAssets input_folder(const string& leaf)const{
        check_directory();
        return native_os::AnchoredAssets(dir.fd,leaf);
    }
    string expand_live(const string& compact,SegmentReadCache* cache=nullptr)const{
        const auto folder=asset_folder(".history");
        auto expanded=expand_compact_transfer(folder.confirmed_descriptor(),compact,cache);
        folder.confirm();check_directory();return expanded;
    }
    void keep_asset(const string& suffix,const string& name,const string& bytes,size_t cap,
                    const native_os::ReadMessages& words)const{
        try{asset_folder(suffix,true).put_exact(name,bytes,cap,words);}
        catch(const native_os::UncertainCommit& e){throw CommitIndeterminate(e.what());}
        check_directory();
    }
    Continuity load(string* raw_digest=nullptr){
        check_directory();
        const auto s=native_os::read_confined_component(dir.fd,dst.filename().string(),state_limit,{
            "cannot open state directory","cannot open persistent state","state must be a regular file",
            "cannot read persistent state","persistent state size limit"});
        physical_sha256=sha256(s);physical_bytes=s.size();
        compacted=s.starts_with("PCGM-COMPACT-1\n");
        const auto logical=compacted?expand_live(s,lease.fd<0?&archive_cache:nullptr):s;
        logical_bytes=logical.size();
        auto state=decode(logical);
        if(compacted)require(compact_transfer_state(state)==s,"noncanonical compact live state");
        if(raw_digest)*raw_digest=sha256(logical);
        return state;
    }
    void save(const Continuity& c,bool init=false,optional<bool> representation=nullopt){
        require(lease.fd>=0,"state opened without a writer lease");
        check_directory();
        require(c.events.size()<=history_event_limit,"persistent history limit");
        const auto logical=encode(c);
        const auto new_mode=representation.value_or(compacted);
        const auto bytes=new_mode?compact_transfer_state(c):logical;
        if(new_mode)require(expand_live(bytes)==logical,
                            "compact history does not reconstruct the live state");
        try{
            native_os::atomic_local_commit(dst.filename().string(),dir.fd,bytes,".pcgm-pending-",init,{
                "cannot create pending persistent state","cannot write pending persistent state","cannot sync pending persistent state",
                "state initialization needs a new path","cannot replace persistent state",
                "state directory sync failed after commit; reopen and reconcile before continuing"});
        }catch(const native_os::UncertainCommit& e){throw CommitIndeterminate(e.what());}
        compacted=new_mode;physical_sha256=sha256(bytes);physical_bytes=bytes.size();logical_bytes=logical.size();
    }
};
