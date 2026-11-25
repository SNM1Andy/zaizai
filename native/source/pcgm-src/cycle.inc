#include "sha256.inc"

struct SensorPacket { string source; unsigned sequence; vector<Atom> facts; vector<string> origins; };
SensorPacket decode_packet(const string& raw){
    // An input packet asserts observations, never CL rules, goals, effects, or scripts.
    require(raw.size()<=32768,"sensor packet size limit");
    istringstream in(raw);
    string line, marker, src, seq, extra;
    require(bool(getline(in,line)),"packet header missing");
    istringstream header(line);
    require(bool(header>>marker>>src>>seq)&&marker=="source"&&!(header>>extra),"expected source NAME SEQUENCE");
    Parser name{src};const auto source=name.name();name.end();
    const auto sequence=sequence_number(seq);
    require(source.size()<=16 && sequence>0&&sequence<=1000000,"invalid sensor packet identity");
    SensorPacket p{source,sequence,{},{}};
    string origin;
    set<Atom> unique;
    while(getline(in,line)){
        Parser q{line};q.ws();
        if(q.take("# trace ")){
            q.ws();
            auto next=line.substr(q.i);
            if(next.ends_with('\r'))next.pop_back();
            require(origin.empty()&&permitted_origin(next),"invalid or duplicate transport trace");
            origin=std::move(next);
            continue;
        }
        if(q.i==line.size()||line[q.i]=='#')continue;
        auto atom=q.atom();q.end();
        require(std::ranges::none_of(atom.args,variable),"observation must be ground");
        require(unique.insert(atom).second,"duplicate fact within sensor packet");
        require(p.facts.size()<64,"sensor packet observation limit");
        p.facts.push_back(std::move(atom));
        p.origins.push_back(origin);
        origin.clear();
    }
    require(origin.empty(),"trace without observation");
    require(!p.facts.empty(),"empty sensor packet");
    return p;
}
string read_packet(const fs::path& root,const string& file){
    const auto dir=root/"incoming";
    return native_os::read_confined_component(dir,file+".packet",32768,{"incoming directory unavailable",
        "packet unavailable","invalid packet","packet read failed","packet too large"});
}

size_t stage_questions(Continuity& next,const set<Why>& gaps){
    set<Why> old;
    for(const auto& [_,q]:next.questions)old.emplace(q.goal,q.fact);
    size_t created=0;
    for(const auto& [goal,fact]:gaps){
        if(old.contains({goal,fact}))continue;
        require(next.questions.size()<256,"persistent question limit");
        const auto id="q"+to_string(next.events.size()+1);
        next.events.push_back("question "+show(goal)+" "+show(fact));
        next.questions.emplace(id,LocalQuestion{goal,fact});
        ++created;
    }
    return created;
}
