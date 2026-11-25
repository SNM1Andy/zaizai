#include "../cl-text-symbol.hpp"
#include <mutex>
#include <algorithm>
#include <cerrno>
#ifndef CL_PORTABLE_MEMORY_CORE
#include <fcntl.h>

#include <sys/stat.h>
#include <io.h>
#endif
#include <chrono>
#include <future>
#include <memory>
#include <atomic>
#include <thread>
#include <array>
#include <bit>
#include <cctype>
#include "../cl-native.hpp"
#ifndef CL_PORTABLE_MEMORY_CORE
#include "../native-os.hpp"
#endif
#include "../native-projection.hpp"
#include <charconv>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <limits>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>


namespace cl_native {
using namespace std;
namespace fs = std::filesystem;
struct Atom {
    string pred;
    vector<string> args;
    auto operator<=>(const Atom&) const = default;
};
struct Rule { Atom head; vector<Atom> body; auto operator<=>(const Rule&) const = default; };
using Kind=string;
struct Program {
    vector<Rule> rules;
    vector<unsigned> rule_lines;
    vector<size_t> rule_numbers;
    map<string,size_t> signature_lines;
    vector<string> rule_labels;
    set<Atom> goals;
    map<string,Atom> observations;
    map<string,string> observation_labels;
    map<string,size_t> arity;
    map<string,vector<Kind>> signatures;
};
struct Proof { string origin; vector<Atom> parents; vector<Atom> checks; };
struct Table { map<Atom,Proof> facts; };
bool variable(const string& x) { return x.starts_with('$'); }
string show(const Atom& a) {
    string out = a.pred + "(";
    for (size_t i=0; i<a.args.size(); ++i) out += (i ? "," : "") + a.args[i];
    return out + ")";
}
void require(bool ok, const string& error) { if (!ok) throw runtime_error(error); }
struct Parser {
    string s; size_t i = 0;
    void ws() { while(i<s.size() && (s[i]==' ' || s[i]=='\r' || s[i]=='\t')) ++i; }
    bool take(const string& x) { ws(); if (s.compare(i,x.size(),x)!=0) return false; i+=x.size(); return true; }
    void expect(const string& x) { require(take(x),"expected " + x); }
    string name() {
        ws(); size_t j=i;
        auto lower=[](char c){return c>='a' && c<='z';};
        require(i<s.size() && lower(s[i]),"expected identifier"); ++i;
        while (i<s.size() && (lower(s[i]) || (s[i]>='0'&&s[i]<='9') || s[i]=='_')) ++i;
        require(i-j <= 48,"identifier too long"); return s.substr(j,i-j);
    }
    string term() {
        if(take("$")) return "$"+name();
        ws(); const size_t start=i;
        if(i<s.size()&&(s[i]=='"'||std::string_view(s).substr(i).starts_with(cl_text_symbol::prefix)))
            return cl_text_symbol::term(s,i);
        if(i<s.size() && (s[i]=='-' || (s[i]>='0'&&s[i]<='9'))) {
            if(s[i]=='-') ++i;
            const size_t digits=i;
            while(i<s.size() && s[i]>='0'&&s[i]<='9') ++i;
            require(i>digits,"expected integer");
            int64_t value=0;
            auto r=std::from_chars(s.data()+start,s.data()+i,value);
            require(r.ec==std::errc() && r.ptr==s.data()+i,"signed 64-bit integer out of range");
            auto canonical=std::to_string(value);
            require(s.compare(start,i-start,canonical)==0,"noncanonical integer");
            if(take("@")) canonical+="@"+name();
            return canonical;
        }
        return name();
    }
    Atom atom() {
        auto neg = take("!");
        string pred=name(); if(neg) pred="!"+pred;
        Atom a{pred,{}}; expect("(");
        do {
            a.args.push_back(term());
            require(a.args.size()<=4,"arity limit");
        } while (take(","));
        expect(")"); return a;
    }
    void end() { ws(); require(i==s.size(),"unexpected trailing input"); }
};
bool quantity_comparison(const string& name){return name=="qty_le"||name=="qty_lt";}
bool binary_filter(const string& name){return name=="int_le"||name=="int_lt"||quantity_comparison(name)||cl_text_symbol::comparison_name(name);}
Kind literal_type(const string& term){
    if(cl_text_symbol::is_wire(term))return "sym";
    const auto tag=term.find('@');
    if(tag!=string::npos)return "qty:"+term.substr(tag+1);
    return term[0]=='-'||(term[0]>='0'&&term[0]<='9')?"i64":"sym";
}
string type_text(const Kind& type){
    return type.starts_with("qty:")?"qty("+type.substr(4)+")":type;
}
int64_t integer(const string& x){
    int64_t value=0;
    const auto end=x.data()+x.size();
    const auto r=from_chars(x.data(),end,value);
    require(r.ec==std::errc{}&&r.ptr==end,"expected bound signed 64-bit integer");
    return value;
}
#include "typed-arithmetic.inc"
void declare(Program& p,const Atom& a) {
    auto key = a.pred.starts_with('!')? a.pred.substr(1):a.pred;
    require(!comparison(key),"CL builtin can only occur as a positive rule condition");
    auto [it, ins] = p.arity.emplace(key,a.args.size());
    require(ins || it->second==a.args.size(),"arity mismatch for "+key);
}
string base_name(const Atom& a) { return a.pred.starts_with('!') ? a.pred.substr(1):a.pred; }
#include "join-index.inc"
#include "closed-folds.inc"
#include "unit-conversion.inc"
void check_type(const Program& p,const Atom& a,map<string,Kind>& vars){
    if(fold_calculation(a.pred)){check_fold_types(p,a,vars);return;}
    if(unit_conversion(a.pred)){check_conversion_types(p,a,vars);return;}
    if(calculation(a.pred)){check_calculation_type(a,vars);return;}
    if(quantity_comparison(a.pred)){
        const auto left=variable(a.args[0])?vars.at(a.args[0]):literal_type(a.args[0]);
        const auto right=variable(a.args[1])?vars.at(a.args[1]):literal_type(a.args[1]);
        require(left.starts_with("qty:")&&right.starts_with("qty:")&&left==right,
                "quantity comparison requires one identical unit, got "+type_text(left)+" and "+type_text(right));
        return;
    }
    const bool arithmetic=comparison(a.pred);
    const auto sig=p.signatures.find(base_name(a));
    if(sig!=p.signatures.end())
        require(sig->second.size()==a.args.size(),"arity mismatch for "+base_name(a));
    for(size_t i=0;i<a.args.size();++i){
        const auto expected=arithmetic?(cl_text_symbol::comparison_name(a.pred)?"sym":"i64"):sig==p.signatures.end()?"sym":sig->second[i];
        const auto& t=a.args[i];
        if(variable(t)){
            auto [it, inserted]=vars.try_emplace(t,expected);
            require(inserted || it->second==expected,"inconsistent type for "+t+": "+type_text(it->second)+" vs "+type_text(expected));
        } else {
            const auto got=literal_type(t);
            require(got==expected,"argument type mismatch in "+show(a)+": expected "+type_text(expected)+", got "+type_text(got));
        }
    }
}
Program compile(const string& src) {
    require(src.size()<=256*1024,"source size limit");
    Program p;
    istringstream in(src); string line; unsigned ln=0;
    map<string,unsigned> observation_lines;
    map<Atom,unsigned> goal_lines;
    while (getline(in,line)) {
        ++ln;
        try {
            Parser q{line}; q.ws();
            if(q.i==line.size() || line[q.i]=='#') continue;
            if (q.take("?")) {
                auto a=q.atom(); q.expect("."); q.end();
                require(!a.pred.starts_with("!"),"goal must use an unsigned predicate");
                for(const auto& x:a.args) require(!variable(x),"goal must be ground");
                declare(p,a);
                require(p.goals.size()<64,"goal count limit");
                require(p.goals.insert(a).second,"duplicate goal");
                goal_lines.emplace(std::move(a),ln);
                continue;
            }
            if (q.take(":")) {
                auto name=q.name(); q.expect("(");
                vector<Kind> kinds;
                do {
                    const auto k=q.name();
                    if(k=="qty"){
                        q.expect("(");const auto unit=q.name();q.expect(")");
                        kinds.push_back("qty:"+unit);
                    }else{
                        require(k=="sym"||k=="i64","unknown type");
                        kinds.push_back(k);
                    }
                    require(kinds.size()<=4,"arity limit");
                } while(q.take(","));
                q.expect(")"); q.expect("."); q.end();
                require(p.signatures.size()<1024,"signature limit");
                declare(p,{name,vector<string>(kinds.size(),"x")});
                require(p.signatures.emplace(name,std::move(kinds)).second,"duplicate signature");
                p.signature_lines[name]=ln;
                continue;
            }
            if (q.take("&")) {
                auto id=q.name(); auto a=q.atom(); q.expect("."); q.end();
                for(const auto& t:a.args) require(!variable(t),"observation must be ground");
                declare(p,a);
                require(p.observations.size()<4096,"observation limit");
                require(p.observations.emplace(id,std::move(a)).second,"duplicate observation ID");
                observation_lines.emplace(id,ln);
                continue;
            }
            Rule r{q.atom(),{}};
            if(q.take("<-")) do {
                r.body.push_back(q.atom()); require(r.body.size()<=8,"body size limit");
            } while(q.take("&"));
            q.expect("."); q.end();
            set<string> bound;
            for(const auto& b:r.body) {
                if(comparison(b.pred)){
                    check_builtin_binding(b,bound);
                    continue;
                }
                declare(p,b);
                for (const auto& t:b.args) if(variable(t)) bound.insert(t);
            }
            for(const auto& t:r.head.args) require(!variable(t)||bound.contains(t),"unbound head variable");
            declare(p,r.head); require(p.rules.size()<512,"rule limit");
            p.rules.push_back(std::move(r)); p.rule_lines.push_back(ln);
        } catch (const exception& e) { throw runtime_error("line "+to_string(ln)+": "+e.what()); }
    }
    auto at=[&](unsigned line,const auto& body){
        try { body(); } catch(const exception& e) { throw runtime_error("line "+to_string(line)+": "+e.what()); }
    };
    for(size_t i=0;i<p.rules.size();++i) at(p.rule_lines.at(i),[&]{
        map<string,Kind> vars; check_type(p,p.rules[i].head,vars);
        for(const auto& b:p.rules[i].body) check_type(p,b,vars);
    });
    for(const auto& [id,observation]:p.observations) at(observation_lines.at(id),[&]{
        map<string,Kind> vars; check_type(p,observation,vars);
    });
    for(const auto& a:p.goals)at(goal_lines.at(a),[&]{map<string,Kind> vars;check_type(p,a,vars);});
    validate_calculation_cycles(p.rules);
    validate_closed_folds(p);
    return p;
}
struct RoundCheckpoint {
    JoinWork counts;
    Table facts;
    vector<Atom> frontier;
    vector<pair<string,unsigned>> masks;
};
class RoundEvaluator {
    const Program& program;
    const JoinLimit limits;
    JoinWork local;
    JoinWork* work;
    CostLedger* profile=nullptr;
    const set<Atom>* excluded=nullptr;
    Table out;
    size_t probes=0,indexed=0,step=0;
    JoinIndex select;
    vector<const Atom*> recent;
    bool done=false,failed=false,resource_failure=false;
public:
    RoundEvaluator(const Program& p,const set<string>& inactive,const JoinLimit& l,JoinWork* w,CostLedger* costs=nullptr,const set<Atom>* filter=nullptr)
        :program(p),limits(l),work(w?w:&local),profile(costs),excluded(filter),select(indexed,work,limits.indexed){
    if(profile)profile->rules.resize(program.rules.size());
    for(const auto& [id,a]:program.observations)
        if(!inactive.contains(id)&&(!excluded||!excluded->contains(a))){
            const auto location=program.observation_labels.find(id);
            if(out.facts.size()>=limits.facts&&!out.facts.contains(a))throw EvaluationLimit("fact limit");
            out.facts.try_emplace(a,Proof{"obs:"+id+(location==program.observation_labels.end()?"":"@"+location->second),{},{}});
            if(profile)profile->initial_facts=out.facts.size();
        }
    for(const auto& [f,_]:out.facts){select.add(&f);recent.push_back(&f);}
    }
    RoundEvaluator(const Program& p,const JoinLimit& l,RoundCheckpoint saved)
        :program(p),limits(l),local(saved.counts),work(&local),out(std::move(saved.facts)),
         probes(local.probes),indexed(local.indexed),step(local.rounds),select(indexed,work,limits.indexed){
        require(step<=limits.rounds&&probes<=limits.probes&&indexed<=limits.indexed&&
                out.facts.size()<=limits.facts,"checkpoint has excessive logical work");
        for(const auto& [fact,_]:out.facts)select.add(&fact);
        select.recover_masks(saved.masks,indexed);
        for(const auto& f:saved.frontier){
            const auto it=out.facts.find(f);
            require(it!=out.facts.end(),"checkpoint frontier refers to missing fact");
            recent.push_back(&it->first);
        }
        require(step==0||!recent.empty(),"checkpoint has empty noninitial frontier");
    }
    RoundCheckpoint checkpoint()const{
        require(!done&&!failed,"only an unfinished CL session can be checkpointed");
        RoundCheckpoint out_state{*work,out,{},select.written_masks()};
        for(const auto* fact:recent)out_state.frontier.push_back(*fact);
        return out_state;
    }
    RoundEvaluator(const RoundEvaluator&)=delete;
    RoundEvaluator& operator=(const RoundEvaluator&)=delete;
    size_t rounds()const{return step;}
    size_t facts()const{return out.facts.size();}
    const JoinWork& counters()const{return *work;}
    bool complete()const{return done;}
    bool rejected()const{return failed;}
    bool exhausted()const{return resource_failure;}
    bool advance(){
        if(failed)throw runtime_error("CL evaluation already failed");
        if(done)return true;
        try{
            if(step>=limits.rounds)throw EvaluationLimit("fixpoint budget");
        if(work)++work->rounds;
        JoinIndex fresh(indexed,work,limits.indexed);
        set<const Atom*> newest;
        for(const auto* f:recent){fresh.add(f);newest.insert(f);}
        map<Atom,Proof> delta;
        map<Atom,size_t> rule_priority;
        for(size_t ri=0;ri<program.rules.size();++ri) {
            RuleCost* tally=profile?&profile->rules.at(ri):nullptr;
            struct Attribution {
                RuleCost* dst;const JoinWork& counters;size_t probes,indexed;
                ~Attribution(){if(dst){dst->probes+=counters.probes-probes;dst->indexed+=counters.indexed-indexed;}}
            } take{tally,*work,work->probes,work->indexed};
            if(tally)++tally->rounds;
            const auto& r=program.rules[ri];
            using Env=map<string,string>;
            vector<const Atom*> witness;
            vector<Atom> checks;
            size_t pivot=r.body.size();
            function<void(size_t,const Env&)> visit=[&](size_t level,const Env& bound) {
                if(level==r.body.size()){
                    Atom f=r.head;
                    for(auto& a:f.args) if(variable(a)) a=bound.at(a);
                    if((excluded&&excluded->contains(f))||out.facts.contains(f))return;
                    const auto previous=delta.find(f);
                    if(previous!=delta.end()&&rule_priority.at(f)!=ri)return;
                    Proof proof{"r"+to_string(program.rule_numbers.empty()?ri+1:program.rule_numbers.at(ri))+(program.rule_labels.empty()?"":"@"+program.rule_labels.at(ri)),{},checks};
                    for (const auto* w:witness) proof.parents.push_back(*w);
                    if(previous!=delta.end()){
                        if(proof.parents<previous->second.parents)previous->second=std::move(proof);
                        return;
                    }
                    if(out.facts.size()+delta.size()>=limits.facts)throw EvaluationLimit("fact limit");
                    rule_priority.emplace(f,ri);
                    delta.emplace(std::move(f),std::move(proof));if(tally)++tally->queued;return;
                }
                const auto& pattern=r.body[level];
                if(comparison(pattern.pred)){
                    if(++probes>limits.probes)throw EvaluationLimit("join budget");
                    if(work)++work->probes;
                    auto check=pattern;
                    auto next=bound;
                    const auto witnesses=witness.size();
                    const auto consume=[&]{
                        if(++probes>limits.probes)throw EvaluationLimit("join budget");
                        if(work)++work->probes;
                    };
                    const bool applies=unit_conversion(check.pred)?
                        lookup_unit_conversion(select,check,next,witness,consume):fold_calculation(check.pred)?
                        lookup_closed_fold(program,select,check,next,witness,consume):eval_builtin(check,next);
                    if(applies){checks.push_back(std::move(check));visit(level+1,next);checks.pop_back();}
                    witness.resize(witnesses);
                    return;
                }
                const auto& rows=(level==pivot?fresh:select).lookup(pattern,bound);
                for(const auto* f:rows){
                    if(pivot<r.body.size()&&level<pivot&&newest.contains(f))continue;
                    if(++probes>limits.probes)throw EvaluationLimit("join budget");
                    if(work)++work->probes;
                    auto e=bound; bool ok=true;
                    for(size_t j=0;j<pattern.args.size()&&ok;++j) {
                        const auto& v=pattern.args[j]; const auto& x=f->args[j];
                        if(!variable(v)) ok=(v==x);
                        else { auto [p1,inserted]=e.emplace(v,x); ok=inserted || p1->second==x; }
                    }
                    if(ok){witness.push_back(f); visit(level+1,e); witness.pop_back();}
                }
            };
            // Checked arithmetic has observable overflow and retains normal eager
            // traversal. Pure relational derivations need a latest-round fact.
            const bool arithmetic=std::ranges::any_of(r.body,[](const Atom& a){return calculation(a.pred);});
            const bool relational=std::ranges::any_of(r.body,[](const Atom& a){return !comparison(a.pred);});
            if(arithmetic||(!relational&&step==0))visit(0,{});
            if(!arithmetic&&relational)
                for(pivot=0;pivot<r.body.size();++pivot)
                    if(!comparison(r.body[pivot].pred)&&fresh.has(r.body[pivot].pred))visit(0,{});
        }
            ++step;
            if(delta.empty()){done=true;return true;}
            recent.clear();recent.reserve(delta.size());
            for(const auto& [fact,_]:delta){select.add(&fact);recent.push_back(&fact);}
            out.facts.merge(delta);
            return false;
        }catch(const EvaluationLimit&){failed=true;resource_failure=true;throw;}
         catch(...){failed=true;throw;}
    }
    const Table& result()const{
        require(done&&!failed,"CL evaluation has no complete proof");
        return out;
    }
    Table take(){
        require(done&&!failed,"CL evaluation has no complete proof");
        return std::move(out);
    }
};
Table run(const Program& p,const set<string>& inactive={},JoinWork* work=nullptr,const JoinLimit& limits={},const set<Atom>* excluded=nullptr){
    RoundEvaluator session(p,inactive,limits,work,nullptr,excluded);
    while(!session.advance()){}
    return session.take();
}
// Positive and negative support are independent. Conflicting witnesses do not
// silently justify a revision and lack of support is not a denial.
string describe(const Proof& p) {
    string out=p.origin;
    for(const auto& parent:p.parents) out+=" "+show(parent);
    for(const auto& check:p.checks) out+=" [verified "+show(check)+"]";
    return out;
}
void explain(const Table& t,Atom a){
    require(!a.pred.starts_with('!'),"explain the unsigned predicate");
    for(const auto& x:a.args) require(!variable(x),"explanation must be ground");
    cout<<"proof_graph "<<show(a)<<'\n';
    for(int sign=0;sign<2;++sign){
        if(sign) a.pred="!"+a.pred;
        cout<<(sign?"negative":"positive")<<": ";
        if(!t.facts.contains(a)){cout<<"no_support\n"; continue;}
        cout<<"supported\n";
        vector<Atom> work{a}; set<Atom> seen;
        while(!work.empty()){
            auto f=std::move(work.back()); work.pop_back();
            if(seen.contains(f)) continue;
            if(seen.size()==512){cout<<"  truncated_node_limit\n"; break;}
            seen.insert(f);
            const auto& proof=t.facts.at(f);
            cout<<"  "<<show(f)<<" <= "<<describe(proof)<<'\n';
            for(auto it=proof.parents.rbegin();it!=proof.parents.rend();++it) work.push_back(*it);
        }
    }
}
void query(const Table& t,Atom a) {
    require(!a.pred.starts_with('!'),"query the unsigned predicate");
    for(const auto& x:a.args) require(!variable(x),"query must be ground");
    auto pos=t.facts.find(a); a.pred="!"+a.pred; auto neg=t.facts.find(a);
    cout<<(pos==t.facts.end()?(neg==t.facts.end()?"UNKNOWN":"NEGATIVE"):(neg==t.facts.end()?"POSITIVE":"CONFLICT"));
    if(pos!=t.facts.end()) cout<<" plus="<<describe(pos->second);
    if(neg!=t.facts.end()) cout<<" minus="<<describe(neg->second);
    cout<<'\n';
}

string input_file(const fs::path& file){
    ifstream f(file,ios::binary);
    require(bool(f),"cannot open "+file.string());
    string s(256*1024+1,'\0');
    f.read(s.data(),s.size());
    require(!f.bad()&&f.gcount()<static_cast<streamsize>(s.size()),"input exceeds limit: "+file.string());
    s.resize(static_cast<size_t>(f.gcount()));
    return s;
}

// Domain-neutral read-only report over the two public predicates of the decision convention.
set<string> frontier_set(const Table& t,map<string,set<string>>* relations=nullptr){
    set<string> candidates;
    for(const auto& [a,_]:t.facts)
        if(a.pred=="feasible" && a.args.size()==1 &&
           !t.facts.contains({"!feasible",a.args})) candidates.insert(a.args[0]);
    map<string,set<string>> edges;
    for(const auto& [a,_]:t.facts) if(a.pred=="dominates" && a.args.size()==2 &&
        candidates.contains(a.args[0]) && candidates.contains(a.args[1])){
        require(!t.facts.contains({"!dominates",a.args}),"conflicting comparison: "+show(a));
        edges[a.args[0]].insert(a.args[1]);
    }
    auto remaining=candidates;
    for(const auto& [_,children]:edges)
        for(const auto& c:children) remaining.erase(c);
    map<string,int> marks;
    for(const auto& n:candidates) marks[n]=0;
    for(const auto& [_,children]:edges) for(const auto& c:children) ++marks.at(c);
    vector<string> queue;
    for(const auto& [n,deg]:marks) if(deg==0)queue.push_back(n);
    for(size_t i=0;i<queue.size();++i)
        for(const auto& c:edges[queue[i]]) if(--marks.at(c)==0) queue.push_back(c);
    require(queue.size()==candidates.size(),"cyclic comparison; no frontier issued");
    if(relations)*relations=std::move(edges);
    return remaining;
}
void frontier(const Table& t){
    map<string,set<string>> edges;
    const auto remaining=frontier_set(t,&edges);
    if(remaining.empty())cout<<"frontier none\n";
    else {
        cout<<"frontier";
        for(const auto& n:remaining)cout<<" "<<n;
        cout<<'\n';
    }
    for(const auto& [from,children]:edges)
        for(const auto& to:children) cout<<"dominance "<<from<<" "<<to<<" "
            <<describe(t.facts.at({"dominates",{from,to}}))<<'\n';
}

#include "sha256.inc"
#include "modules.inc"
#include "release.inc"
#include "csv.inc"
#include "authoring.inc"
#include "bridge-export.inc"
#include "compiled-ir.inc"
#include "proof-json.inc"
#include "public-api.inc"
#include "source-generator.inc"
#include "stage-instantiate.inc"
#include "scope-policy.inc"
#include "workspace-recipe.inc"
#include "workspace-compound-recipe.inc"
#include "package.inc"
#include "workspace-closure.inc"
#include "workspace-archive.inc"
#include "workspace-mixed-recipe.inc"
#include "workspace-source-recipe.inc"
#include "offline-receipt.inc"
std::vector<std::string> checked_repair_statuses(const std::string& source){
    require(source.size()<=65536,"repair proof source exceeds 64 KiB");
    const auto program=compile(source);
    require(!program.goals.empty()&&program.goals.size()<=32&&program.rules.size()<=128&&
            program.observations.size()<=512,"repair proof slice exceeds native CL budget");
    const auto table=run(program,{},nullptr,{64,4096,250000,250000});
    vector<string> result;
    for(const auto& goal:program.goals){
        auto neg=goal;neg.pred="!"+goal.pred;
        const bool pos=table.facts.contains(goal),minus=table.facts.contains(neg);
        result.emplace_back(pos?(minus?"CONFLICT":"POSITIVE"):(minus?"NEGATIVE":"UNKNOWN"));
    }
    return result;
}
#include "proof-integrity.inc"
#include "round-checkpoint.inc"
#ifndef CL_PORTABLE_MEMORY_CORE
#include "round-session.inc"
#endif
std::string pinned_package_ir_bytes(const std::string& bytes,const std::string& expected){
    require(expected.size()==64 && expected.find_first_not_of("0123456789abcdef")==string::npos &&
            sha256(bytes)==expected,"package does not match supplied SHA-256");
    return verify_package_bytes(bytes).ir;
}
JoinLimit bounded_limits(const EvaluationCeilings& c){
    const JoinLimit cap;
    if(!c.rounds||c.rounds>cap.rounds||!c.facts||c.facts>cap.facts||
       !c.probes||c.probes>cap.probes||!c.indexed||c.indexed>cap.indexed)
        throw std::invalid_argument("invalid CL resource ceiling");
    return {c.rounds,c.facts,c.probes,c.indexed};
}
std::string audit_package_checkpoint(const string& bytes,const string& package,const string& query,
                                      const string& saved,const string& pin,const EvaluationCeilings& cap){
    require(workspace_digest(package)&&sha256(bytes)==package,"package does not match supplied SHA-256");
    const auto bundle=decode_package(bytes);
    const auto program=verify_package(bundle);
    (void)offline_goals(program,query);
    const auto goals=sha256(query);
    const auto limits=bounded_limits(cap);
    const auto native=recompute_checkpoint(saved,pin,package,goals,limits,program);
    const auto& work=native->counters();
    return "{\"schema\":\"cl-checkpoint-audit-v1\",\"valid\":true,\"checkpoint_sha256\":"+quote_json(pin)+
        ",\"package_sha256\":"+quote_json(package)+",\"goals_sha256\":"+quote_json(goals)+
        ",\"rounds\":"+to_string(work.rounds)+",\"facts\":"+to_string(native->facts())+
        ",\"probes\":"+to_string(work.probes)+",\"indexed\":"+to_string(work.indexed)+"}\n";
}
std::string offline_proof_bounded_bytes(const std::string& package,const std::string& expected,const std::string& goals,
                                        const EvaluationCeilings& c){
    return offline_receipt(package,expected,goals,bounded_limits(c));
}
SingleGoalProof offline_single_goal_bounded(const std::string& package,const std::string& expected,const std::string& goal,
                                            const EvaluationCeilings& c){
    auto sign=EvidenceSign::Unknown;
    auto receipt=offline_receipt(package,expected,goal,bounded_limits(c),&sign);
    return {sign,std::move(receipt)};
}
std::string offline_proof_bytes(const std::string& package,const std::string& expected,const std::string& goals){return offline_receipt(package,expected,goals);}
#include "query-slice.inc"
#include "compute-planes.inc"
#include "budgeted-planes.inc"
#include "grammar-bridge.inc"
#include "grammar-tree.inc"
#include "type-audit.inc"
#include "direct-lowering.inc"
#include "repl.inc"
#include "compiler-profile.inc"
#ifndef CL_PORTABLE_MEMORY_CORE
#include "compiler-journal.inc"
#endif
#include "evidence-session.inc"
#include "evidence-frozen.inc"
#include "release-compare.inc"
#include "logical-cost-profile.inc"
#ifndef CL_PORTABLE_MEMORY_CORE
#include "offline-resolver.inc"
#endif
#include "capabilities.inc"
#include "symbol-index.inc"

VerifiedPackage verify_package_bytes(const string& bytes){
    auto bundle=decode_package(bytes);
    (void)verify_package(bundle);
    auto ir_digest=sha256(bundle.ir);
    return {move(bundle.ir),sha256(bytes),std::move(ir_digest),sha256(bundle.api),
            bundle.scope_policy.empty()?string{}:sha256(bundle.scope_policy),std::move(bundle.scope_report),{}, {}};
}

VerifiedPackage verify_workspace_bytes(const string& bytes,const string& required_lock){
    auto archived=decode_workspace(bytes);
    const auto source=assemble_workspace_bytes(archived.input,required_lock);
    require(archived.report==sha256(source.receipt),"workspace archive audit receipt differs from reconstruction");
    require(archived.ir==to_image(source.program,{}),"workspace archive IR differs from reconstruction");
    const auto digest=sha256(archived.ir);
    return {std::move(archived.ir),sha256(bytes),digest,source.api_digest,{}, {},required_lock,std::move(archived.report)};
}
std::string pack_workspace_buffers(const string& source,const string& lock,const string& lock_pin,
       const string& data,bool has_data,vector<WorkspacePackageBuffer> packages){
    require(source.size()<=256*1024&&lock.size()<=64*1024&&data.size()<=256*1024&&packages.size()<=16,
            "workspace source, lock, data or dependency limit");
    WorkspaceInput input;
    input.app=source;input.lock=lock;
    if(has_data)input.data=data;
    else require(data.empty(),"workspace data buffer requires explicit presence");
    size_t total=0;
    for(auto& member:packages){
        require(package_filename(member.name)&&member.name.ends_with(".clpkg")&&member.bytes.size()<=package_limit,
                "invalid workspace dependency buffer");
        total+=member.bytes.size();
        require(total<=workspace_archive_cap,"workspace dependency bytes exceed 16 MiB");
        require(input.packages.emplace(std::move(member.name),std::move(member.bytes)).second,
                "duplicate workspace dependency buffer");
    }
    const auto product=assemble_workspace_bytes(input,lock_pin);
    return package_workspace(input,to_image(product.program,{}),sha256(product.receipt));
}
std::string pinned_workspace_ir_bytes(const string& archive,const string& pin,const string& lock){
    require(workspace_digest(pin)&&sha256(archive)==pin,"workspace archive does not match supplied SHA-256");
    return verify_workspace_bytes(archive,lock).ir;
}
static void workspace_proof_limits(const EvaluationCeilings& ceilings){
    if(!ceilings.rounds||!ceilings.facts||!ceilings.probes||!ceilings.indexed)
        throw std::invalid_argument("workspace proof ceilings must be positive");
    require(ceilings.rounds<=128&&ceilings.facts<=12000&&ceilings.probes<=2000000&&ceilings.indexed<=2000000,
            "workspace proof ceilings exceed engine limits");
}
static string workspace_render_receipt(const Table& proof,const vector<Atom>& queried,
       const string& pin,const string& lock,const string& ir_pin,const string& goals){
    auto report=json_report(proof,queried,"cl",
        "{\"protocol\":\"cl-workspace-proof-v1\",\"archive_sha256\":"+quote_json(pin)+
        ",\"lock_sha256\":"+quote_json(lock)+",\"ir_sha256\":"+quote_json(ir_pin)+
        ",\"goals_sha256\":"+quote_json(sha256(goals))+"}")+'\n';
    require(report.size()<=4*1024*1024,"workspace proof exceeds output limit");
    return report;
}
class ImmutableWorkspace final : public PreparedWorkspace {
    const Program program;
    const Table table;
    const string pin,lock,ir_pin;
public:
    ImmutableWorkspace(Program p,Table t,string a,string l,string ir):
        program(std::move(p)),table(std::move(t)),pin(std::move(a)),lock(std::move(l)),ir_pin(std::move(ir)){}
    string proof(const string& expected_archive,const string& goals) const override{
        require(workspace_digest(expected_archive)&&expected_archive==pin,"prepared workspace archive pin differs");
        return workspace_render_receipt(table,offline_goals(program,goals),pin,lock,ir_pin,goals);
    }
};
std::unique_ptr<const PreparedWorkspace> prepare_workspace(const string& bytes,const string& pin,
            const string& lock,const EvaluationCeilings& ceilings){
    workspace_proof_limits(ceilings);
    require(workspace_digest(pin)&&sha256(bytes)==pin,"workspace archive does not match supplied SHA-256");
    const auto archive=decode_workspace(bytes);
    auto linked=assemble_workspace_bytes(archive.input,lock);
    require(archive.report==sha256(linked.receipt)&&archive.ir==to_image(linked.program,{}),
            "workspace archive failed independent reconstruction");
    auto facts=run(linked.program,{},nullptr,{ceilings.rounds,ceilings.facts,ceilings.probes,ceilings.indexed});
    return std::make_unique<ImmutableWorkspace>(std::move(linked.program),std::move(facts),pin,lock,sha256(archive.ir));
}
static std::string workspace_proof_engine(const string& bytes,const string& pin,const string& lock,
       const string& goals,const EvaluationCeilings& ceilings,EvidenceSign* sign){
    require(workspace_digest(pin)&&sha256(bytes)==pin,"workspace archive does not match supplied SHA-256");
    const auto archive=decode_workspace(bytes);
    auto linked=assemble_workspace_bytes(archive.input,lock);
    require(archive.report==sha256(linked.receipt)&&archive.ir==to_image(linked.program,{}),
            "workspace archive failed independent reconstruction");
    const auto queried=offline_goals(linked.program,goals);
    workspace_proof_limits(ceilings);
    const auto proof=run(linked.program,{},nullptr,{ceilings.rounds,ceilings.facts,ceilings.probes,ceilings.indexed});
    if(sign){
        require(queried.size()==1,"workspace evidence requires one exact ground question");
        auto negative=queried.front();negative.pred="!"+negative.pred;
        const bool pos=proof.facts.contains(queried.front()),neg=proof.facts.contains(negative);
        *sign=pos?(neg?EvidenceSign::Conflict:EvidenceSign::Positive):(neg?EvidenceSign::Negative:EvidenceSign::Unknown);
    }
    return workspace_render_receipt(proof,queried,pin,lock,sha256(archive.ir),goals);
}
std::string workspace_proof_bounded_bytes(const string& bytes,const string& pin,const string& lock,
       const string& goals,const EvaluationCeilings& ceilings){
    return workspace_proof_engine(bytes,pin,lock,goals,ceilings,nullptr);
}
SingleGoalProof workspace_single_goal_bounded(const string& bytes,const string& pin,const string& lock,
       const string& goal,const EvaluationCeilings& ceilings){
    EvidenceSign sign=EvidenceSign::Unknown;
    auto receipt=workspace_proof_engine(bytes,pin,lock,goal,ceilings,&sign);
    return {sign,std::move(receipt)};
}
static WorkspaceRebuild rebuild_workspace_candidate(const string& archive,const string& archive_expected,
       const string& dependency_lock,const string& candidate,const string& source_expected,
       const string* regression_goals=nullptr){
    require(workspace_digest(archive_expected)&&sha256(archive)==archive_expected,"workspace baseline archive SHA-256 mismatch");
    require(workspace_digest(source_expected)&&sha256(candidate)==source_expected,"workspace candidate source SHA-256 mismatch");
    require(candidate.size()<=256*1024,"workspace candidate source size limit");
    auto baseline=decode_workspace(archive);
    const auto original=assemble_workspace_bytes(baseline.input,dependency_lock);
    require(sha256(original.receipt)==baseline.report&&to_image(original.program,{})==baseline.ir,
            "workspace baseline failed independent reconstruction");
    const auto path=fs::path("/clpkg/application.cl");
    const auto old_name=LinkedProject::load_text(path,baseline.input.app).name;
    require(LinkedProject::load_text(path,candidate).name==old_name,
            "workspace source update cannot change application module identity");
    baseline.input.app=candidate;
    const auto proposed=assemble_workspace_bytes(baseline.input,dependency_lock);
    if(!regression_goals)require(proposed.api_digest==original.api_digest,"workspace source update public API changed");
    else {
        ostringstream differences;
        require(proposed.api!=original.api&&compatible_api(parse_api(original.api),parse_api(proposed.api),differences),
                "additive workspace branch needs a new export and must preserve every existing public interface");
    }
    require(proposed.program.observations==original.program.observations,
            "workspace source update cannot change ground observations");
    if(regression_goals){
        const auto old_queries=offline_goals(original.program,*regression_goals);
        const auto new_queries=offline_goals(proposed.program,*regression_goals);
        require(old_queries==new_queries,"additive workspace regression goal identities differ");
        const auto old_truth=run(original.program),new_truth=run(proposed.program);
        for(const auto& goal:old_queries){
            auto negative=goal;negative.pred="!"+negative.pred;
            require(old_truth.facts.contains(goal)==new_truth.facts.contains(goal)&&
                    old_truth.facts.contains(negative)==new_truth.facts.contains(negative),
                    "additive workspace branch changed a pinned regression outcome: "+show(goal));
        }
    }
    const auto ir=to_image(proposed.program,{});
    const auto report=sha256(proposed.receipt);
    const auto bytes=package_workspace(baseline.input,ir,report);
    auto verified=verify_workspace_bytes(bytes,dependency_lock);
    return {bytes,source_expected,std::move(verified)};
}
WorkspaceRebuild rebuild_workspace_source(const string& archive,const string& archive_expected,
       const string& dependency_lock,const string& candidate,const string& source_expected){
    return rebuild_workspace_candidate(archive,archive_expected,dependency_lock,candidate,source_expected);
}
std::string fork_workspace_additive(const string& archive,const string& archive_expected,const string& lock,
       const string& candidate,const string& source_expected,const string& goals,const string& goals_pin){
    require(goals.size()<=32*1024&&workspace_digest(goals_pin)&&sha256(goals)==goals_pin,
            "additive workspace regression goals digest mismatch");
    return rebuild_workspace_candidate(archive,archive_expected,lock,candidate,source_expected,&goals).archive;
}
std::vector<WorkspaceEvidencePort> workspace_evidence_ports(const std::string& boundary){
    if(!boundary.starts_with("CLWRECIPE-3\n")&&!boundary.starts_with("CLWRECIPE-4\n"))return {};
    return parse_source_recipe(boundary).ports;
}
WorkspaceRebuild synthesize_workspace_quantity(const string& original,const string& expected,
        const string& lock,const string& recipe,const string& recipe_pin,const string& boundary,
        const string& boundary_pin,const string& evidence){
    require(workspace_digest(expected)&&sha256(original)==expected,"workspace recipe base archive digest mismatch");
    require(workspace_digest(recipe_pin)&&sha256(recipe)==recipe_pin,"workspace recipe stage digest mismatch");
    require(workspace_digest(boundary_pin)&&sha256(boundary)==boundary_pin,"workspace recipe scope digest mismatch");
    const auto package=decode_workspace(original);
    const auto generated=[&](){
        if(boundary.starts_with("CLWRECIPE-3\n")||boundary.starts_with("CLWRECIPE-4\n"))return rewrite_source_quantity(package.input.app,recipe,boundary,evidence);
        if(boundary.starts_with("CLWRECIPE-2\n"))return rewrite_compound_quantity(package.input.app,recipe,boundary,evidence);
        const auto scope=read_quantity_scope(boundary);
        const auto candidate_amount=guided_amount(recipe,scope,evidence);
        return rewrite_one_quantity(package.input.app,scope,candidate_amount);
    }();
    return rebuild_workspace_source(original,expected,lock,generated,sha256(generated));
}
ProfileProduct build_profile_bytes(const string& profile,const string& expected_profile,
                                   const string& source,const string& expected_source){
    require(sha256(profile)==expected_profile,"CL compiler profile transfer digest mismatch");
    require(sha256(source)==expected_source,"CL source transfer digest mismatch");
    const auto verified=decode_profile(profile);
    auto image=profile_build(verified,source);
    const auto digest=sha256(image);
    return {move(image),expected_profile,expected_source,digest};
}

ProfileRebuildProduct rebuild_compiler_profile_bytes(const ProfileRebuildInputs& in){
    const std::array<std::pair<const char*,const PinnedProfileInput*>,5> pins{{
        {"baseline profile",&in.baseline},{"grammar source",&in.grammar},{"type source",&in.types},
        {"lowering source",&in.lower},{"smoke source",&in.smoke}
    }};
    for(const auto& [name,part]:pins)
        require(workspace_digest(part->pin)&&sha256(part->contents)==part->pin,
                string("CL profile rebuild ")+name+" digest mismatch");
    require(workspace_digest(in.smoke_ir_pin),"CL profile rebuild needs a lowercase smoke IR digest");
    const auto baseline=decode_profile(in.baseline.contents);
    require(sha256(profile_build(baseline,in.smoke.contents))==in.smoke_ir_pin,
            "CL profile rebuild baseline failed the pinned smoke build");
    const auto candidate=verify_self_compilation(baseline,in.grammar.contents,in.types.contents,in.lower.contents,
                                                 in.smoke.contents,in.smoke_ir_pin);
    auto receipt="{\"schema\":\"cl-profile-rebuild-v1\",\"baseline_sha256\":"+quote_json(in.baseline.pin)+
        ",\"grammar_sha256\":"+quote_json(in.grammar.pin)+",\"types_sha256\":"+quote_json(in.types.pin)+
        ",\"lower_sha256\":"+quote_json(in.lower.pin)+",\"smoke_source_sha256\":"+quote_json(in.smoke.pin)+
        ",\"smoke_ir_sha256\":"+quote_json(in.smoke_ir_pin)+",\"candidate_sha256\":"+quote_json(candidate.digest)+
        ",\"fixed_point\":true,\"applied\":false}\n";
    return {encode_profile(candidate),std::move(receipt)};
}
std::string audit_rebuilt_compiler_profile_bytes(const ProfileRebuildInputs& input,
        const PinnedProfileInput& candidate,const PinnedProfileInput& receipt){
    require(workspace_digest(candidate.pin)&&sha256(candidate.contents)==candidate.pin,
            "CL profile rebuild candidate transfer digest mismatch");
    require(workspace_digest(receipt.pin)&&sha256(receipt.contents)==receipt.pin,
            "CL profile rebuild receipt transfer digest mismatch");
    auto rebuilt=rebuild_compiler_profile_bytes(input);
    require(rebuilt.candidate==candidate.contents,"CL profile rebuild candidate differs from reconstruction");
    require(rebuilt.receipt==receipt.contents,"CL profile rebuild receipt differs from reconstruction");
    return std::move(rebuilt.receipt);
}

EvidenceProduct synthesize_profile_bytes(const string& profile,const string& profile_digest,
        const string& base,const string& base_digest,const string& generator,const string& generator_digest,
        const string& scope,const string& scope_digest,const string& evidence){
    require(sha256(generator)==generator_digest&&sha256(scope)==scope_digest,"native synthesis rule or scope digest mismatch");
    istringstream controls(scope);
    string line,normal_scope;
    set<string> allowed;
    require(getline(controls,line)&&line=="CL-AST-SCOPE-1","invalid native synthesis scope");
    normal_scope=line+"\n";
    while(getline(controls,line)){
        Parser q{line};const auto mode=q.name();
        if(mode=="evidence"){
            const auto name=q.name();q.end();allowed.insert(name);
        }else normal_scope+=line+"\n";
    }
    istringstream input(evidence);
    size_t count=0;
    while(getline(input,line)){
        Parser q{line};q.expect("&");(void)q.name();
        const auto point=q.atom();q.expect(".");q.end();
        require(allowed.contains(point.pred)&&std::ranges::none_of(point.args,variable),"CL synthesis evidence outside approved scope");
        require(++count<=16,"CL synthesis evidence count limit");
    }
    require(count>0,"no approved CL synthesis evidence");
    const auto [source,code]=generate_source(generator+"\n"+evidence,base,base_digest,normal_scope);
    auto product=build_profile_bytes(profile,profile_digest,source,sha256(source));
    return {move(product),generator_digest,scope_digest,sha256(evidence)};
}

#ifndef CL_PORTABLE_MEMORY_CORE
int driver(int argc,char** argv){
    try{
        if(argc==2&&(string(argv[1])=="capabilities"||string(argv[1])=="--help")){
            if(string(argv[1])=="--help")cout<<"CL native compiler and prover; machine-readable quickstart: cl capabilities\n";
            else cout<<cl_feature_manifest()<<'\n';
            return 0;
        }
        require(argc>=3&&argc<=12,
                "usage: cl check|run|explain|frontier RULES.cl [DATA.cl] | cl lock ROOT.cl | cl project-CMD ROOT.cl LOCK [DATA.cl] | cl hash FILE | cl verify-release MANIFEST | cl csv-lock ROOT MAP | cl csv-CMD ROOT LOCK MAP CSV");
        string command=argv[1];
        if(command=="init"){
            require(argc==3,"usage: cl init NEW_DIRECTORY");
            init_project(argv[2]);return 0;
        }
        if(command=="hash"||command=="verify-release"){
            require(argc==3,"command requires one file path");
            if(command=="hash")cout<<hash_file(argv[2])<<'\n';
            else verify_release(argv[2]);
            return 0;
        }
        if(command=="lock"){
            require(argc==3,"usage: cl lock ROOT.cl");
            LinkedProject project(argv[2]);
            project.compile_project({});
            cout<<project.lock_text();
            return 0;
        }
        if(command=="project-scoped-compile"||command=="project-scoped-report"){
            require(argc==6||argc==7,"usage: cl project-scoped-compile|project-scoped-report ROOT LOCK PROFILE EXPECTED_SHA256 [DATA]");
            const auto policy=read_receipt_input(argv[4],2*1024*1024);
            require(sha256(policy)==argv[5],"CL module scope profile digest mismatch");
            LinkedProject project(argv[2]);
            require(input_file(argv[3])==project.lock_text(),"project lock mismatch");
            const bool report_only=command=="project-scoped-report";
            string report;
            project.scope_verifier=[&](const LinkedProject& subject){
                auto [accepted,body]=audit_module_scope(subject,policy,sha256(policy));
                report=std::move(body);
                if(!accepted)throw ScopeDeclined();
            };
            try{
                auto program=project.compile_project(argc==7?fs::path(argv[6]):fs::path{});
                if(report_only)cout<<report<<'\n';
                else cout<<to_image(program,{});
                return 0;
            }catch(const ScopeDeclined&){
                if(report_only)cout<<report<<'\n';else cerr<<report<<'\n';
                return 2;
            }
        }
        if(command=="project-api"||command=="project-api-check"){
            const bool check=command=="project-api-check";
            require(argc==(check?5:4),"usage: cl project-api ROOT LOCK | cl project-api-check ROOT LOCK API");
            LinkedProject project(argv[2]);
            require(input_file(argv[3])==project.lock_text(),"project lock mismatch; review dependency changes");
            const auto program=project.compile_project({});
            const auto api=public_api(project,program);
            if(!check){cout<<api_text(api);return 0;}
            const auto prior=parse_api(input_file(argv[4]));
            return compatible_api(prior,api,cout)?0:3;
        }
        if(command=="generate-source"||command=="generate-ir"){
            require(argc==6,"usage: cl generate-source|generate-ir GENERATOR BASE BASE_SHA256 SCOPE");
            auto [source,program]=generate_source(input_file(argv[2]),input_file(argv[3]),argv[4],input_file(argv[5]));
            if(command=="generate-source")cout<<source;
            else cout<<to_image(program,{});
            return 0;
        }
        if(command=="project-pack"){
            require(argc==5||argc==6,"usage: cl project-pack ROOT LOCK API [DATA]");
            cout<<encode_package(pack_project(argv[2],argv[3],argv[4],argc==6?fs::path(argv[5]):fs::path{}));
            return 0;
        }
        if(command=="workspace-synthesize-quantity"){
            require(argc==10,"usage: cl workspace-synthesize-quantity ARCHIVE ARCHIVE_SHA256 LOCK_SHA256 RECIPE RECIPE_SHA256 SCOPE SCOPE_SHA256 EVIDENCE_ATOM");
            const auto result=synthesize_workspace_quantity(read_receipt_input(argv[2],workspace_archive_cap),argv[3],argv[4],
                read_receipt_input(argv[5],256*1024),argv[6],read_receipt_input(argv[7],16*1024),argv[8],argv[9]);
            cout<<result.archive;return 0;
        }
        if(command=="workspace-replay-synthesis"){
            require(argc==12,"usage: cl workspace-replay-synthesis BASE BASE_SHA256 LOCK_SHA256 RECIPE RECIPE_SHA256 SCOPE SCOPE_SHA256 EVIDENCE EVIDENCE_SHA256 EXPECTED_CANDIDATE_SHA256");
            const auto evidence=read_receipt_input(argv[9],16*1024);
            require(workspace_digest(argv[10])&&sha256(evidence)==argv[10],"replay evidence SHA-256 mismatch");
            const auto rebuilt=synthesize_workspace_quantity(read_receipt_input(argv[2],workspace_archive_cap),argv[3],argv[4],
                read_receipt_input(argv[5],256*1024),argv[6],read_receipt_input(argv[7],16*1024),argv[8],evidence);
            require(workspace_digest(argv[11])&&rebuilt.product.package_sha256==argv[11],"replay candidate SHA-256 mismatch");
            cout<<rebuilt.archive;return 0;
        }
        if(command=="package-profile"||command=="workspace-profile"){
            const bool work=command=="workspace-profile";const int basic=work?6:5;
            require(argc==basic||argc==basic+4,
                    "usage: cl package-profile PACKAGE PIN GOALS [ROUNDS FACTS PROBES INDEXED] | cl workspace-profile ARCHIVE PIN LOCK GOALS [ROUNDS FACTS PROBES INDEXED]");
            EvaluationCeilings limits{128,12000,2000000,2000000};
            if(argc==basic+4){
                size_t* values[]={&limits.rounds,&limits.facts,&limits.probes,&limits.indexed};
                for(int i=0;i<4;++i){
                    const auto n=integer(argv[basic+i]);
                    require(n>0&&n<=2000000,"invalid CL profile resource limit");
                    *values[i]=static_cast<size_t>(n);
                }
            }
            const auto raw=read_receipt_input(argv[2],work?workspace_archive_cap:package_limit);
            const auto goals=read_receipt_input(argv[work?5:4],32*1024);
            cout<<(work?profile_workspace_cost(raw,argv[3],argv[4],goals,limits):
                        profile_package_cost(raw,argv[3],goals,limits));
            return 0;
        }
        if(command=="workspace-prove"){
            require(argc==6||argc==10,"usage: cl workspace-prove ARCHIVE ARCHIVE_SHA256 LOCK_SHA256 GOALS [ROUNDS FACTS PROBES INDEXED]");
            EvaluationCeilings ceilings{128,12000,2000000,2000000};
            if(argc==10){
                size_t* bounds[]={&ceilings.rounds,&ceilings.facts,&ceilings.probes,&ceilings.indexed};
                for(size_t i=0;i<4;++i){
                    const auto arg=string_view(argv[i+6]);
                    const auto n=std::from_chars(arg.data(),arg.data()+arg.size(),*bounds[i]);
                    require(n.ec==std::errc{}&&n.ptr==arg.data()+arg.size()&&to_string(*bounds[i])==arg,
                            "noncanonical workspace proof ceiling");
                }
            }
            cout<<workspace_proof_bounded_bytes(read_receipt_input(argv[2],workspace_archive_cap),argv[3],argv[4],
                                                read_receipt_input(argv[5],32*1024),ceilings);
            return 0;
        }
        if(command=="workspace-branch-additive"){
            require(argc==9,"usage: cl workspace-branch-additive BASE BASE_SHA LOCK_SHA SOURCE SOURCE_SHA GOALS GOALS_SHA");
            cout<<fork_workspace_additive(read_receipt_input(argv[2],workspace_archive_cap),argv[3],argv[4],
                  read_receipt_input(argv[5],256*1024),argv[6],read_receipt_input(argv[7],32*1024),argv[8]);
            return 0;
        }
        if(command=="workspace-rebuild"){
            require(argc==7,"usage: cl workspace-rebuild BASE_ARCHIVE ARCHIVE_SHA256 LOCK_SHA256 NEW_SOURCE SOURCE_SHA256");
            const auto result=rebuild_workspace_source(read_receipt_input(argv[2],workspace_archive_cap),argv[3],argv[4],
                                                        read_receipt_input(argv[5],256*1024),argv[6]);
            cout<<result.archive;return 0;
        }
        if(command=="workspace-resolve"){
            require(argc==8||argc==10,"usage: cl workspace-resolve APP APP_SHA REQUIRES REQ_SHA CATALOG CAT_SHA [DATA DATA_SHA]");
            const fs::path path=fs::absolute(argv[6]);
            const auto parent=fs::canonical(path.parent_path());
            native_os::Descriptor directory(native_os::open_directory(parent));
            require(directory.fd>=0,"cannot open local CL catalog directory");
            const auto catalog=native_os::read_confined_component(directory.fd,path.filename().string(),65536,{
                "cannot open CL catalog directory","cannot open CL catalog","CL catalog is not regular","cannot read CL catalog","CL catalog limit"});
            optional<string> data;
            if(argc==10){
                data=read_receipt_input(argv[8],256*1024);
                require(workspace_digest(argv[9])&&sha256(*data)==argv[9],"CL resolution data digest mismatch");
            }
            const auto report=resolve_workspace_lock(read_receipt_input(argv[2],256*1024),argv[3],
                read_receipt_input(argv[4],64*1024),argv[5],catalog,argv[7],directory.fd,data);
            native_os::confirm_directory(directory.fd,parent,"CL catalog parent directory changed");
            cout<<report;return 0;
        }
        if(command=="workspace-pack"){
            require(argc==5||argc==6,"usage: cl workspace-pack APP WORKSPACE_LOCK LOCK_SHA256 [DATA]");
            auto input=read_workspace(argv[2],argv[3],argv[4],argc==6?fs::path(argv[5]):fs::path{});
            auto product=assemble_workspace_bytes(input,argv[4]);
            cout<<package_workspace(input,to_image(product.program,{}),sha256(product.receipt));
            return 0;
        }
        if(command=="workspace-bundle-verify"||command=="workspace-bundle-ir"||command=="workspace-bundle-report"){
            require(argc==5,"usage: cl workspace-bundle-verify|workspace-bundle-ir|workspace-bundle-report ARCHIVE ARCHIVE_SHA256 LOCK_SHA256");
            const auto input=read_receipt_input(argv[2],workspace_archive_cap);
            require(workspace_digest(argv[3])&&sha256(input)==argv[3],"workspace archive does not match supplied SHA-256");
            const auto archive=decode_workspace(input);
            const auto result=assemble_workspace_bytes(archive.input,argv[4]);
            require(archive.report==sha256(result.receipt),"workspace archive audit receipt differs from reconstruction");
            require(archive.ir==to_image(result.program,{}),"workspace archive IR differs from reconstruction");
            if(command=="workspace-bundle-ir")cout<<archive.ir;
            else if(command=="workspace-bundle-report")cout<<result.receipt<<'\n';
            else cout<<"workspace_bundle_ok sha256="<<argv[3]<<" lock_sha256="<<argv[4]
                     <<" ir_sha256="<<sha256(archive.ir)<<" audit_sha256="<<archive.report<<'\n';
            return 0;
        }
        if(command=="workspace-compile"||command=="workspace-report"){
            require(argc==5||argc==6,"usage: cl workspace-compile|workspace-report APP WORKSPACE_LOCK LOCK_SHA256 [DATA]");
            const auto product=assemble_workspace(argv[2],argv[3],argv[4],argc==6?fs::path(argv[5]):fs::path{});
            if(command=="workspace-report")cout<<product.receipt<<'\n';else cout<<to_image(product.program,{});
            return 0;
        }
        if(command=="project-scoped-pack"){
            require(argc==7||argc==8,"usage: cl project-scoped-pack ROOT LOCK API PROFILE PROFILE_SHA256 [DATA]");
            const auto stage=read_receipt_input(argv[5],2*1024*1024);
            require(sha256(stage)==argv[6],"CL module scope profile digest mismatch");
            auto package=pack_project(argv[2],argv[3],argv[4],argc==8?fs::path(argv[7]):fs::path{});
            require(!stage.empty(),"required nonempty scope policy");
            package.scope_policy=stage;
            const auto scoped=compile_packaged(package);
            const auto ir=to_image(scoped.first,{});
            require(ir==package.ir,"scope policy and native compiled program differ");
            package.scope_report=sha256(scoped.second);
            cout<<encode_package(package);
            return 0;
        }
        if(command=="package-verify-scope"){
            require(argc==5,"usage: cl package-verify-scope PACKAGE PACKAGE_SHA256 REQUIRED_SCOPE_SHA256");
            const auto raw=read_receipt_input(argv[2],package_limit);
            require(sha256(raw)==argv[3],"package does not match supplied SHA-256");
            const auto value=decode_package(raw);
            require(!value.scope_policy.empty(),"package has no authored scope profile");
            require(sha256(value.scope_policy)==argv[4],"package does not use the required authored scope profile");
            (void)verify_package(value);
            cout<<"scope_package_ok package_sha256="<<argv[3]<<" profile_sha256="<<argv[4]
                <<" scope_report_sha256="<<value.scope_report<<" ir_sha256="<<sha256(value.ir)<<'\n';
            return 0;
        }
        if(command=="package-verify"||command=="package-ir"||command=="package-run"||command=="package-api"){
            require(argc==3,"usage: cl package-CMD PACKAGE");
            const auto bytes=read_image(argv[2]);
            const auto bundle=decode_package(bytes);
            const auto program=verify_package(bundle);
            if(command=="package-ir")cout<<bundle.ir;
            else if(command=="package-api")cout<<bundle.api;
            else if(command=="package-run"){const auto table=run(program);for(const auto& goal:program.goals){cout<<show(goal)<<" ";query(table,goal);}}
            else cout<<"package_ok sha256="<<sha256(bytes)<<" ir_sha256="<<sha256(bundle.ir)
                <<" units="<<bundle.files.size()<<'\n';
            return 0;
        }
        if(command=="package-round-audit"){
            require(argc==7||argc==8,"usage: cl package-round-audit PACKAGE PIN GOALS CHECKPOINT CHECKPOINT_PIN [MAX_ROUNDS]");
            const auto rounds=argc==8?integer(argv[7]):128;
            require(rounds>=1&&rounds<=128,"invalid CL round ceiling");
            cout<<audit_package_checkpoint(read_receipt_input(argv[2],package_limit),argv[3],
                    read_receipt_input(argv[4],32*1024),read_receipt_input(argv[5],round_checkpoint_cap),argv[6],
                    {static_cast<uint32_t>(rounds),12000,2000000,2000000});
            return 0;
        }
        if(command=="package-round-session"||command=="package-round-checkpoint"||
           command=="package-round-reopen-verified"||
           command=="package-round-reopen"||command=="package-round-recheckpoint"){
            const bool both=command=="package-round-recheckpoint";
            const bool checked=command=="package-round-reopen-verified";
            const bool saves=command=="package-round-checkpoint"||both,reopens=command=="package-round-reopen"||both||checked;
            const int args=both?8:reopens?7:saves?6:5;
            require(argc==args||argc==args+1,"usage: cl package-round-session PACKAGE PIN GOALS [MAX_ROUNDS] | cl package-round-checkpoint PACKAGE PIN GOALS NEW_CHECKPOINT [MAX_ROUNDS] | cl package-round-reopen PACKAGE PIN GOALS CHECKPOINT CHECKPOINT_SHA256 [MAX_ROUNDS] | cl package-round-reopen-verified PACKAGE PIN GOALS CHECKPOINT CHECKPOINT_SHA256 [MAX_ROUNDS] | cl package-round-recheckpoint PACKAGE PIN GOALS CHECKPOINT CHECKPOINT_SHA256 NEW_CHECKPOINT [MAX_ROUNDS]");
            JoinLimit limits;
            if(argc>args){
                const auto requested=integer(argv[args]);
                require(requested>=1&&static_cast<size_t>(requested)<=limits.rounds,"invalid CL round ceiling");
                limits.rounds=static_cast<size_t>(requested);
            }
            round_session(read_receipt_input(argv[2],package_limit),argv[3],read_receipt_input(argv[4],32*1024),limits,
                          saves?fs::path(argv[both?7:5]):fs::path{},
                          reopens?read_receipt_input(argv[5],round_checkpoint_cap):string{},
                          reopens?optional<string>{argv[6]}:nullopt,checked);
            return 0;
        }
        if(command=="evidence-freeze"){
            require(argc==7,"usage: cl evidence-freeze PACKAGE PACKAGE_SHA256 GOALS JOURNAL JOURNAL_SHA256");
            cout<<seal_frozen_evidence(read_receipt_input(argv[2],package_limit),argv[3],read_receipt_input(argv[4],32*1024),
                                      read_receipt_input(argv[5],evidence_journal_limit),argv[6]);
            return 0;
        }
        if(command=="evidence-frozen-integrity"){
            require(argc==6,"usage: cl evidence-frozen-integrity ARTIFACT ARTIFACT_SHA256 PACKAGE_SHA256 JOURNAL_SHA256");
            cout<<verify_frozen_integrity(read_receipt_input(argv[2],frozen_evidence_limit),argv[3],argv[4],argv[5]);
            return 0;
        }
        if(command=="evidence-frozen-verify"){
            require(argc==6,"usage: cl evidence-frozen-verify ARTIFACT ARTIFACT_SHA256 PACKAGE_SHA256 JOURNAL_SHA256");
            cout<<verify_frozen_evidence(read_receipt_input(argv[2],frozen_evidence_limit),argv[3],argv[4],argv[5]);return 0;
        }
        if(command=="evidence-audit"){
            require(argc==6,"usage: cl evidence-audit PACKAGE PACKAGE_SHA256 GOALS JOURNAL");
            return run_evidence_audit(read_receipt_input(argv[2],package_limit),argv[3],read_receipt_input(argv[4],32*1024),argv[5]);
        }
        if(command=="evidence-init"||command=="evidence-resume"){
            require(argc==6,"usage: cl evidence-init|evidence-resume PACKAGE PACKAGE_SHA256 GOALS JOURNAL");
            return run_evidence_session(read_receipt_input(argv[2],package_limit),argv[3],read_receipt_input(argv[4],32*1024),
                                        argv[5],command=="evidence-init");
        }
        if(command=="package-plane-budget"){
            require(argc==10,"usage: cl package-plane-budget PACKAGE TRUSTED_SHA256 GOALS ROUNDS FACTS PROBES INDEXED MAX_WORKERS");
            const auto bytes=read_receipt_input(argv[2],package_limit);
            const auto pin=string(argv[3]);
            require(pin.size()==64 && pin.find_first_not_of("0123456789abcdef")==string::npos && sha256(bytes)==pin,
                    "package does not match supplied SHA-256");
            const auto queries=read_receipt_input(argv[4],32*1024);
            const auto bundle=decode_package(bytes);
            const auto program=verify_package(bundle);
            const auto goals=offline_goals(program,queries);
            auto cap=[&](int i,size_t max){
                const auto n=integer(argv[i]);
                require(n>0&&static_cast<size_t>(n)<=max,"invalid CL plane resource ceiling");
                return static_cast<size_t>(n);
            };
            const JoinLimit global;
            const JoinLimit total={cap(5,global.rounds),cap(6,global.facts),cap(7,global.probes),cap(8,global.indexed)};
            cout<<render_budgeted_planes(program,goals,total,cap(9,4),pin,sha256(bundle.ir),sha256(queries))<<'\n';
            return 0;
        }
        if(command=="package-compare"){
            require(argc==7,"usage: cl package-compare BASE BASE_SHA256 CANDIDATE CANDIDATE_SHA256 GOALS");
            cout<<compare_verified_packages(read_receipt_input(argv[2],package_limit),argv[3],
                   read_receipt_input(argv[4],package_limit),argv[5],read_receipt_input(argv[6],32*1024),
                   {128,12000,2000000,2000000});
            return 0;
        }
        if(command=="package-proof-integrity"){
            require(argc==5,"usage: cl package-proof-integrity PACKAGE TRUSTED_SHA256 GOALS");
            cout<<exact_package_integrity(read_receipt_input(argv[2],package_limit),argv[3],
                                         read_receipt_input(argv[4],32*1024));
            return 0;
        }
        if(command=="package-prove"||command=="package-proof-check"||command=="package-prove-budget"){
            const bool verify=command=="package-proof-check",budgeted=command=="package-prove-budget";
            require(argc==(verify?6:budgeted?9:5),"usage: cl package-prove PACKAGE TRUSTED_SHA256 GOALS | cl package-proof-check PACKAGE TRUSTED_SHA256 GOALS RECEIPT | cl package-prove-budget PACKAGE TRUSTED_SHA256 GOALS ROUNDS FACTS PROBES INDEXED");
            const auto bytes=read_receipt_input(argv[2],package_limit);
            const auto goals=read_receipt_input(argv[4],32*1024);
            JoinLimit budget;
            if(budgeted){
                auto ceiling=[&](const char* value,size_t upper,const char* field){
                    const auto n=integer(value);
                    require(n>=1&&static_cast<size_t>(n)<=upper,string("invalid CL resource ceiling: ")+field);
                    return static_cast<size_t>(n);
                };
                budget={ceiling(argv[5],budget.rounds,"rounds"),ceiling(argv[6],budget.facts,"facts"),
                        ceiling(argv[7],budget.probes,"probes"),ceiling(argv[8],budget.indexed,"indexed")};
            }
            const auto result=offline_receipt(bytes,argv[3],goals,budget);
            require(result.size()<=4*1024*1024,"CL receipt exceeds size limit");
            if(verify){
                require(result==read_receipt_input(argv[5],4*1024*1024),
                        "CL receipt does not match reconstructed proof");
                cout<<"proof_receipt_ok sha256="<<sha256(result)<<'\n';
            }else cout<<result;
            return 0;
        }
        if(command=="ir-slice"){
            require(argc>=4,"usage: cl ir-slice IMAGE GOAL [GOAL...]");
            const auto input=from_image(read_image(argv[2]));
            vector<Atom> goals;
            for(int i=3;i<argc;++i){
                Parser q{argv[i]};auto a=q.atom();q.end();
                require(!a.pred.starts_with('!')&&std::ranges::none_of(a.args,variable),"slice asks an unsigned ground goal");
                require(input.first.arity.contains(a.pred)&&input.first.arity.at(a.pred)==a.args.size(),"unknown or mismatched goal relation");
                map<string,Kind> vars;check_type(input.first,a,vars);
                goals.push_back(move(a));
            }
            SliceStats counts;
            const auto kept=query_slice(input.first,goals,counts);
            cout<<json_report(run(kept),goals,"cl","{\"projected\":true,\"relations\":"+
                to_string(counts.relations)+",\"rules\":"+to_string(counts.rules)+
                ",\"observations\":"+to_string(counts.observations)+"}")<<'\n';
            return 0;
        }
        if(command=="repl"){
            require(argc==3,"usage: cl repl SOURCE");
            return workspace_repl(input_file(argv[2]));
        }
        if(command=="symbols"||command=="ir-symbols"||command=="package-symbols"||command=="project-symbols"){
            string output;
            if(command=="project-symbols"){
                require(argc==4||argc==5,"usage: cl project-symbols ROOT LOCK [DATA]");
                LinkedProject project(argv[2]);
                require(project.lock_text()==input_file(argv[3]),"project lock does not match");
                const auto code=project.compile_project(argc==5?fs::path(argv[4]):fs::path{});
                output=describe_symbols(code,symbol_scope(project),"project");
            }else{
                require(argc==3,"usage: cl symbols SOURCE | cl ir-symbols IMAGE | cl package-symbols PACKAGE");
                if(command=="symbols"){
                    const auto code=compile(input_file(argv[2]));
                    output=describe_symbols(code,local_symbol_scope(code,fs::path(argv[2]).filename().string()),"source");
                }
                else if(command=="ir-symbols")output=describe_symbols(from_image(read_image(argv[2])).first,{},"ir");
                else{
                    const auto package=decode_package(read_image(argv[2]));
                    output=describe_symbols(verify_package(package),symbol_scope(packaged_tree(package)),"package");
                }
            }
            cout<<output<<'\n';return 0;
        }
        if(command=="ir-batch"){
            require(argc==4||argc==5,"usage: cl ir-batch IMAGE GOALS [WORKER_CEILING]");
            const auto input=from_image(read_image(argv[2]));
            const auto ceiling=argc==5?integer(argv[4]):0;
            require(ceiling>=0&&ceiling<=4,"worker ceiling must be 0 to 4");
            vector<Atom> goals;
            istringstream in(input_file(argv[3]));
            string line;
            while(getline(in,line)){
                Parser q{line};q.ws();
                if(q.i==line.size()||line[q.i]=='#')continue;
                auto a=q.atom();q.end();
                require(goals.size()<64,"compute batch goal count limit");
                require(!a.pred.starts_with('!')&&std::ranges::none_of(a.args,variable),"batch asks unsigned ground goals");
                require(input.first.arity.contains(a.pred)&&input.first.arity.at(a.pred)==a.args.size(),"unknown or mismatched goal relation");
                map<string,Kind> vars;check_type(input.first,a,vars);
                goals.push_back(move(a));
            }
            const auto batch=evaluate_planes(input.first,goals,{},static_cast<size_t>(ceiling),
                [](const Program& p,const set<string>& inactive){return run(p,inactive);});
            cout<<render_planes(batch,"{\"engine\":\"cl\"}")<<'\n';
            return 0;
        }
        if(command=="grammar-check"||command=="grammar-ast"){
            require(argc==4,"usage: cl grammar-check|grammar-ast GRAMMAR SOURCE");
            const auto source=input_file(argv[3]);
            const auto result=assess_grammar(input_file(argv[2]),source);
            if(command=="grammar-ast"){
                require(result.accepted,"source has no positive grammar acceptance");
                cout<<render_grammar_tree(source,result)<<'\n';
            }else cout<<json_report(result.table,{{"accept",{"unit"}}},"cl",result.context)<<'\n';
            return result.accepted?0:2;
        }
        if(command=="grammar-normalize"||command=="grammar-compile"){
            require(argc==4,"usage: cl grammar-normalize|grammar-compile GRAMMAR SOURCE");
            const auto source=input_file(argv[3]);
            const auto parsed=assess_grammar(input_file(argv[2]),source);
            require(parsed.accepted,"source has no positive grammar acceptance");
            const auto normalized=lower_grammar_source(source,parsed);
            const auto native=compile(normalized);
            if(command=="grammar-compile")cout<<to_image(native,{});
            else cout<<normalized;
            return 0;
        }
        if(command=="grammar-typecheck"){
            require(argc==5,"usage: cl grammar-typecheck GRAMMAR TYPE_RULES SOURCE");
            const auto source=input_file(argv[4]);
            const auto parsed=assess_grammar(input_file(argv[2]),source);
            require(parsed.accepted,"source has no positive grammar acceptance");
            auto [receipt,passed]=audit_types(input_file(argv[3]),lower_grammar_source(source,parsed));
            cout<<receipt<<'\n';return passed?0:2;
        }
        if(command=="grammar-numeric-check"||command=="grammar-checked-build"){
            require(argc==5,"usage: cl grammar-numeric-check|grammar-checked-build GRAMMAR TYPE_RULES SOURCE");
            const auto source=input_file(argv[4]);
            const auto parsed=assess_grammar(input_file(argv[2]),source);
            require(parsed.accepted,"source has no positive grammar acceptance");
            const auto normalized=lower_grammar_source(source,parsed);
            const auto [report,passed]=audit_types(input_file(argv[3]),normalized,true);
            if(command=="grammar-numeric-check"){cout<<report<<'\n';return passed?0:2;}
            if(!passed){cerr<<report<<'\n';return 2;}
            const auto checked=compile(normalized);
            cout<<to_image(checked,{});return 0;
        }
        if(command=="grammar-direct-ir"||command=="grammar-direct-ir-segmented"){
            require(argc==6,"usage: cl grammar-direct-ir GRAMMAR TYPE_RULES LOWERER SOURCE");
            const auto source=input_file(argv[5]);
            const auto grammar=read_image(argv[2]);
            string normalized;
            if(command=="grammar-direct-ir-segmented")normalized=normalize_line_local(grammar,source);
            else{
                const auto parsed=assess_grammar(grammar,source);
                require(parsed.accepted,"source has no positive grammar acceptance");
                normalized=lower_grammar_source(source,parsed);
            }
            const auto [typed,passed]=audit_types(read_image(argv[3]),normalized,true);
            if(!passed){cerr<<typed<<'\n';return 2;}
            const auto [verified,image]=direct_lower(normalized,read_image(argv[4]));
            cout<<image;return 0;
        }
        if(command=="compiler-profile"){
            require(argc==5,"usage: cl compiler-profile GRAMMAR_IR TYPE_IR LOWER_IR");
            cout<<encode_profile(compiler_profile(read_image(argv[2]),read_image(argv[3]),read_image(argv[4])));
            return 0;
        }
        if(command=="profile-build"){
            require(argc==5,"usage: cl profile-build PROFILE EXPECTED_PROFILE_SHA256 SOURCE");
            const auto profile=decode_profile(read_image(argv[2]));
            require(profile.digest==argv[3],"compiler profile SHA-256 not the expected value");
            cout<<profile_build(profile,input_file(argv[4]));return 0;
        }
        if(command=="compiler-session"){
            require(argc==6,"usage: cl compiler-session PROFILE DIRECTORY SMOKE EXPECTED_IR_SHA256");
            return run_compiler_session(decode_profile(read_image(argv[2])),argv[3],input_file(argv[4]),argv[5]);
        }
        if(command=="compiler-init"||command=="compiler-resume"){
            const bool init=command=="compiler-init";
            require(argc==(init?7:4),"usage: cl compiler-init JOURNAL PROFILE DIR SMOKE EXPECTED_IR_SHA256 | cl compiler-resume JOURNAL DIR");
            const auto directory=fs::canonical(argv[init?4:3]);
            require(fs::is_directory(directory),"compiler session needs a working directory");
            optional<CompilerSnapshot> initial;
            if(init){
                auto profile=decode_profile(read_image(argv[3]));
                const auto smoke=input_file(argv[5]);
                const string expected=argv[6];
                require(expected==sha256(profile_build(profile,smoke)),"initial compiler profile failed the pinned smoke build");
                initial=CompilerSnapshot{profile.digest,smoke,expected,0,{{profile.digest,profile}}};
            }
            CompilerJournal journal(argv[2]);
            if(initial)journal.save(*initial,true);
            auto snapshot=initial?std::move(*initial):journal.load();
            auto active=snapshot.retained.at(snapshot.active);
            const auto smoke=snapshot.smoke,expected=snapshot.expected;
            return run_compiler_session(std::move(active),directory,smoke,expected,std::move(snapshot),
                [&](const CompilerSnapshot& next){journal.save(next);});
        }
        Program p;
        string csv_source_info;
        fs::path cases;
        if(command.starts_with("ir-")){
            command=command.substr(3);
            require(argc==(command=="test"?4:3),"usage: cl ir-CMD IMAGE [CASES]");
            require(command=="run"||command=="explain"||command=="frontier"||command=="test"||command=="verify"||command=="json",
                    "unknown CL IR command");
            auto decoded=from_image(read_image(argv[2]));
            p=std::move(decoded.first);csv_source_info=std::move(decoded.second);
            if(command=="test")cases=argv[3];
            if(command=="verify"){cout<<"ir_ok rules="<<p.rules.size()<<" observations="<<p.observations.size()<<'\n';return 0;}
        }else if(command=="csv-lock"){
            require(argc==4,"usage: cl csv-lock ROOT MAP");
            LinkedProject project(argv[2]);
            project.compile_project({});
            const auto raw=input_file(argv[3]);
            parse_csv_mapping(raw);
            cout<<project.lock_text()<<"CSV-MAP-1 "<<sha256(raw)<<'\n';
            return 0;
        }else if(command.starts_with("csv-")){
            command=command.substr(4);
            require(argc==(command=="test"?7:command=="packet"?8:6),
                    "usage: cl csv-CMD ROOT LOCK MAP CSV [CASES or SOURCE SEQUENCE]");
            if(command=="test")cases=argv[6];
            require(command=="check"||command=="run"||command=="explain"||command=="frontier"||command=="test"||command=="packet"||command=="compile"||command=="json","unknown CSV command");
            LinkedProject project(argv[2]);
            const auto map=input_file(argv[4]), csv=input_file(argv[5]);
            require(input_file(argv[3])==project.lock_text()+"CSV-MAP-1 "+sha256(map)+"\n",
                    "CSV project or mapping lock mismatch");
            const auto facts=extract_csv(argv[5],csv,parse_csv_mapping(map));
            p=project.compile_project(argv[5],&facts.lines,&facts.rows);
            p.observation_labels=facts.origins;
            if(command=="packet"){export_packet(p,facts,argv[6],argv[7],sha256(csv));return 0;}
            csv_source_info="csv_source_sha256="+sha256(csv)+" mapping_sha256="+sha256(map);
        }else if(command.starts_with("project-")){
            command=command.substr(8);
            const int n=command=="test"?5:4;
            require(argc==n||argc==n+1,"usage: cl project-CMD ROOT.cl LOCK [CASES] [DATA.cl]");
            if(command=="test")cases=argv[4];
            require(command=="check"||command=="run"||command=="explain"||command=="frontier"||command=="test"||command=="compile"||command=="json","unknown project command");
            LinkedProject project(argv[2]);
            require(input_file(argv[3])==project.lock_text(),
                    "project lock mismatch; review the dependency changes before generating a new lock");
            p=project.compile_project(argc==n+1?fs::path(argv[n]):fs::path{});
        }else{
            const int n=command=="test"?4:3;
            require(argc==n||argc==n+1,"single-file command takes optional data file");
            if(command=="test")cases=argv[3];
            require(command=="check"||command=="run"||command=="explain"||command=="frontier"||command=="test"||command=="stats"||command=="compile"||command=="json","unknown command");
            auto rules=input_file(argv[2]);
            string data;
            if(argc==n+1){
                data=input_file(argv[n]);
                istringstream in(data);
                string line;size_t index=0;
                while(getline(in,line)){
                    ++index;
                    Parser q{line};q.ws();
                    require(q.i==line.size()||line[q.i]=='#'||line[q.i]=='&',
                            string(argv[n])+":"+to_string(index)+": data may only contain source-labelled observations");
                }
            }

            try { p=compile(rules+"\n"+data); }
            catch(const exception& e) {
                const string message=e.what();
                if(message.starts_with("line ")){
                    const auto colon=message.find(':');
                    if(colon!=string::npos){
                        const auto source_line=static_cast<size_t>(integer(message.substr(5,colon-5)));
                        const auto split=static_cast<size_t>(count(rules.begin(),rules.end(),'\n'))+1;
                        const auto is_data=source_line>split;
                        throw runtime_error(string(argv[is_data?n:2])+":"+to_string(is_data?source_line-split:source_line)+message.substr(colon));
                    }
                }
                throw;
            }
        }
        if(command=="compile"){
            const auto image=to_image(p,csv_source_info);
            cout.write(image.data(),static_cast<streamsize>(image.size()));
            require(bool(cout),"cannot write the CL IR image");
            return 0;
        }
        if(command!="test"&&command!="json"&&!csv_source_info.empty())cout<<csv_source_info<<'\n';
        if(command=="check"){cout<<"OK rules="<<p.rules.size()<<" observations="<<p.observations.size()<<" goals="<<p.goals.size()<<'\n';return 0;}
        if(command=="frontier"){
            require(p.arity.contains("feasible") && p.arity.at("feasible")==1 &&
                    p.arity.contains("dominates") && p.arity.at("dominates")==2,
                    "frontier requires feasible/1 and dominates/2");
        }
        JoinWork work;
        const auto t=run(p,{},command=="stats"?&work:nullptr);
        if(command=="json"){
            const auto context=csv_source_info.empty()?"{}":"{\"source\":"+quote_json(csv_source_info)+"}";
            cout<<json_report(t,vector<Atom>(p.goals.begin(),p.goals.end()),"cl",context)<<'\n';return 0;
        }
        if(command=="stats")cout<<"rounds="<<work.rounds<<" probes="<<work.probes
                                 <<" indexed="<<work.indexed<<" facts="<<t.facts.size()<<'\n';
        if(command=="test")return run_tests(p,t,cases);
        for(const auto& g:p.goals){
            if(command=="explain") explain(t,g);
            else{cout<<show(g)<<" ";query(t,g);}
        }
        if(command=="frontier")frontier(t);
        return 0;
    }catch(const exception& e){cerr<<e.what()<<'\n';return 1;}
}

#endif

} // namespace cl_native
#ifndef CL_NATIVE_LIBRARY
int main(int argc,char** argv){_setmode(0,_O_BINARY);_setmode(1,_O_BINARY);return cl_native::driver(argc,argv);}
#endif
