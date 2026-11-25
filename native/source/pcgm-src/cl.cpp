#include "../cl-text-symbol.hpp"
#include <algorithm>
#include <chrono>
#include <csignal>
#include <cerrno>
#include <fcntl.h>
#include <io.h>
#include <memory>
#include <atomic>
#include <thread>
#include <future>
#include "../cl-native.hpp"
#include "../anchored-assets.hpp"
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
#include <vector>


using namespace std;
namespace fs = std::filesystem;
struct Atom {
    string pred;
    vector<string> args;
    auto operator<=>(const Atom&) const = default;
};
struct Rule { Atom head; vector<Atom> body; auto operator<=>(const Rule&) const = default; };
struct Schema { string trigger, premise, result; };
using Kind=string;
struct Preference {
    bool hard;
    Atom proposition;
    string expected;
    optional<Atom> when;
    auto operator<=>(const Preference&) const = default;
};
struct NativeSynthesisPolicy {
    string alias,evidence,profile,base,generator,scope;
    auto operator<=>(const NativeSynthesisPolicy&) const = default;
};
struct WorkspaceRecipePolicy {
    string alias,evidence,base,recipe,scope;
    bool choose=false;
    bool operator==(const WorkspaceRecipePolicy&)const=default;
};
struct Program {
    vector<Rule> rules;
    vector<unsigned> rule_lines;
    vector<size_t> rule_numbers;
    vector<string> rule_labels;
    map<size_t,string> live_guards;
    set<Atom> goals;
    bool criteria_questions=false;
    vector<Preference> preferences;
    map<string,Atom> experience_contexts;
    map<string,Atom> observations;
    map<string,string> linked_origins;
    map<string,string> observation_labels;
    vector<Schema> schemas;
    map<string,size_t> arity;
    map<string,set<string>> sensor_policy,synth_policy,multi_policy,version_policy;
    map<string,map<string,string>> auto_policy;
    map<string,NativeSynthesisPolicy> native_synthesis;
    map<string,vector<WorkspaceRecipePolicy>> workspace_recipes;
    set<string> adaptation,feedback_sources,pinned_feedback_sources;
    map<string,string> measurement_sources;
    map<string,vector<Kind>> signatures;
};
struct Proof { string origin; vector<Atom> parents; vector<Atom> checks; string identity; };
string sha256(const string& input);
struct Table { map<Atom,Proof> facts; };
bool proof_without_conflict(const Table&,const Atom&,bool* limited=nullptr);
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
using cl_native::EvaluationLimit;
#include "../cl-src/closed-folds.inc"
#include "../cl-src/unit-conversion.inc"
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
bool permitted_origin(const string& s){
    const auto sep=s.find('@');
    if(s.size()>240||sep==string::npos||sep<5||s.size()-sep!=65||
       s.substr(sep+1).find_first_not_of("0123456789abcdef")!=string::npos)return false;
    const auto c1=s.find(':'),c2=c1==string::npos?string::npos:s.find(':',c1+1);
    if(c1==0||c2==string::npos||c2+1>=sep||
       s.substr(c1+1,c2-c1-1).empty()||
       s.substr(c1+1,c2-c1-1).find_first_not_of("0123456789")!=string::npos)return false;
    return std::ranges::all_of(s,[](char c){
        return (c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||
            c=='.'||c=='_'||c=='-'||c==':'||c=='%'||c=='@';
    });
}
Program compile(const string& src) {
    require(src.size()<=256*1024,"source size limit");
    Program p;
    istringstream in(src); string line; unsigned ln=0;
    set<string> adaptive_results;
    map<string,unsigned> observation_lines;
    string pending_origin;
    while (getline(in,line)) {
        ++ln;
        try {
            Parser q{line}; q.ws();
            if(q.take("# pcgm_artifact_rule ")){
                q.ws();const auto label=line.substr(q.i);
                require(pending_origin.empty()&&!label.empty()&&label.size()<=512,"invalid artifact rule origin");
                pending_origin=label;continue;
            }
            if(q.take("# pcgm_artifact_ref ")){
                const auto id=q.name();q.ws();const auto label=line.substr(q.i);
                require(id.starts_with("artifact_")&&!label.empty()&&label.size()<=512&&
                        p.observation_labels.emplace(id,label).second,"invalid artifact observation origin");
                continue;
            }
            if(q.take("# pcgm_sensor_ref ")){
                const auto id=q.name();q.ws();
                const auto path=line.substr(q.i);
                require(id.starts_with("sensor_")&&permitted_origin(path),"invalid bound observation origin");
                require(p.linked_origins.emplace(id,path).second,"duplicate bound observation origin");
                continue;
            }
            if(q.i==line.size() || line[q.i]=='#') continue;
            if(q.take(">")){
                const auto name=q.name();auto condition=q.atom();q.expect(".");q.end();
                require(std::ranges::none_of(condition.args,variable),"experience context must be ground");
                declare(p,condition);
                require(p.experience_contexts.size()<16&&p.experience_contexts.emplace(name,condition).second,
                        "duplicate or excessive experience context");
                continue;
            }
            if(q.take("%%")){
                WorkspaceRecipePolicy w;
                w.choose=q.take("+");
                istringstream in(line.substr(q.i));string channel,extra;
                require(bool(in>>channel>>w.alias>>w.evidence>>w.base>>w.recipe>>w.scope)&&!(in>>extra)&&w.scope.ends_with('.'),
                        "invalid pinned workspace recipe policy");
                w.scope.pop_back();
                for(const auto& name:{channel,w.alias,w.evidence}){Parser id{name};id.name();id.end();}
                for(const auto& key:{w.base,w.recipe,w.scope})
                    require(key.size()==64&&key.find_first_not_of("0123456789abcdef")==string::npos,"invalid workspace recipe digest");
                require(channel.size()<=16&&w.alias.size()<=12&&
                        (p.workspace_recipes.contains(channel)||p.workspace_recipes.size()<8),"oversized workspace recipe policy");
                auto& phases=p.workspace_recipes[channel];
                require(phases.size()<4&&std::ranges::none_of(phases,[&](const auto& other){return other.base==w.base;}),
                        "duplicate baseline or too many workspace phases");
                require(phases.empty()||(phases.front().alias==w.alias&&phases.front().evidence==w.evidence&&
                        phases.front().choose==w.choose),"workspace phases must share the same alias, typed evidence, and authority");
                phases.push_back(std::move(w));
                continue;
            }
            if(q.take("%")){
                istringstream args(line.substr(q.i));string channel,extra;
                NativeSynthesisPolicy policy;
                require(bool(args>>channel>>policy.alias>>policy.evidence>>policy.profile>>policy.base>>policy.generator>>policy.scope)&&
                        !(args>>extra)&&policy.scope.ends_with('.'),"invalid pinned native synthesis policy");
                policy.scope.pop_back();
                for(const auto& name:{channel,policy.alias,policy.evidence}){Parser id{name};(void)id.name();id.end();}
                for(const auto& hash:{policy.profile,policy.base,policy.generator,policy.scope})
                    require(hash.size()==64&&hash.find_first_not_of("0123456789abcdef")==string::npos,"invalid synthesis policy digest");
                require(channel.size()<=16&&policy.alias.size()<=12&&p.native_synthesis.size()<8&&
                        p.native_synthesis.emplace(channel,policy).second,"duplicate or oversized native synthesis policy");
                continue;
            }
            if(q.take("=")){
                const auto source=q.name();
                if(q.take("measurement")){
                    const auto relation=q.name();q.expect(".");q.end();
                    require(source.size()<=16&&p.measurement_sources.size()<8&&p.measurement_sources.emplace(source,relation).second,
                            "duplicate or excessive measurement source");
                    continue;
                }
                const bool pinned_feedback=q.take("feedback_pinned");
                if(pinned_feedback||q.take("feedback")){
                    q.expect(".");q.end();
                    require(source.size()<=16&&p.feedback_sources.size()<8&&p.feedback_sources.insert(source).second,
                            "duplicate or excessive feedback source");
                    if(pinned_feedback)p.pinned_feedback_sources.insert(source);
                    continue;
                }
                if(q.take("versions")){
                    auto& aliases=p.version_policy[source];
                    do{
                        const auto alias=q.name();
                        require(alias.size()<=12&&aliases.size()<8&&aliases.insert(alias).second,
                                "invalid or duplicate version policy alias");
                    }while(q.take(","));
                }
                q.expect(".");q.end();
                require(source.size()<=16&&p.adaptation.size()<16&&p.adaptation.insert(source).second,
                        "duplicate or excessive autonomous decision channel");
                continue;
            }
            if(q.take("|")){
                const auto mode=q.name(), truth=q.name();
                require(mode=="hard"||mode=="wish","decision target must be hard or wish");
                require(truth=="positive"||truth=="negative"||truth=="unknown"||truth=="conflict",
                        "unknown decision truth status");
                auto fact=q.atom();
                optional<Atom> when;
                if(q.take("when"))when=q.atom();
                q.expect(".");q.end();
                require(!fact.pred.starts_with("!")&&std::ranges::none_of(fact.args,variable),"decision target must be ground and unsigned");
                if(when){
                    require(std::ranges::none_of(when->args,variable),"condition must be ground");
                    declare(p,*when);
                }
                require(p.preferences.size()<64,"decision target count limit");
                for(const auto& old:p.preferences)
                    require(old.proposition!=fact||old.when!=when,"duplicate decision target with same condition");
                declare(p,fact);
                string expected;
                for(char ch:truth)expected+=static_cast<char>(ch-'a'+'A');
                p.preferences.push_back({mode=="hard",std::move(fact),std::move(expected),std::move(when)});
                continue;
            }
            if(q.take("+")){
                const auto channel=q.name(), output=q.name(), guard=q.name();
                q.expect(".");q.end();
                require(channel.size()<=16,"autonomous source name limit");
                require(p.auto_policy.size()<16||p.auto_policy.contains(channel),"autonomous channel limit");
                auto& chosen=p.auto_policy[channel];
                require(chosen.size()<16 && chosen.emplace(output,guard).second,"duplicate or excessive automatic rule policy");
                continue;
            }
            if(q.take("^")){
                const auto first=q.name();
                const bool multi=first=="multi";
                const auto output=multi?q.name():first;
                const auto input=q.name();
                q.expect("."); q.end();
                const auto reserved=[](const string& name){return name.starts_with("gen_")||name.starts_with("ir_");};
                require(output!=input && !reserved(output) && !reserved(input),
                        "synthesis policy cannot self-authorize or rewrite IR");
                auto& selected=multi?p.multi_policy:p.synth_policy;
                require(selected.size()<16||selected.contains(output),"synthesis output limit");
                auto& allowed=selected[output];
                require(allowed.size()<16 && allowed.insert(input).second,"duplicate or excessive synthesis policy");
                continue;
            }
            if(q.take("~")){
                const auto src=q.name();
                require(src.size()<=16,"sensor name limit");
                const bool negative=q.take("!");
                const auto name=q.name();q.expect(".");q.end();
                require(p.sensor_policy.size()<32 || p.sensor_policy.contains(src),"sensor count limit");
                auto& allowed=p.sensor_policy[src];
                require(allowed.size()<32 && allowed.insert((negative?"!":"")+name).second,
                        "duplicate or excessive sensor policy");
                continue;
            }
            if(q.take("? criteria.")){
                q.end();
                require(!p.criteria_questions,"duplicate PCGM criteria-question policy");
                p.criteria_questions=true;
                continue;
            }
            if (q.take("?")) {
                auto a=q.atom(); q.expect("."); q.end();
                require(!a.pred.starts_with("!"),"goal must use an unsigned predicate");
                for(const auto& x:a.args) require(!variable(x),"goal must be ground");
                declare(p,a);
                require(p.goals.size()<64,"goal count limit");
                require(p.goals.insert(std::move(a)).second,"duplicate goal");
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
            if (q.take("@")) {
                Schema a{q.name(),q.name(),q.name()}; q.expect("."); q.end();
                require(a.trigger!=a.result && a.premise!=a.result,"self-authorizing schema");
                require(adaptive_results.insert(a.result).second,"duplicate adaptive result");
                require(p.schemas.size()<32,"schema limit");
                for (const auto* name : {&a.trigger,&a.premise,&a.result}) declare(p,{*name,{"x"}});
                p.schemas.push_back(a);
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
            p.rule_labels.push_back(std::move(pending_origin));pending_origin.clear();
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
    for(const auto& a:p.goals){
        map<string,Kind> vars;
        check_type(p,a,vars);
    }
    for(const auto& schema:p.schemas){
        map<string,Kind> vars;
        for(const auto* predicate:{&schema.trigger,&schema.premise,&schema.result})
            check_type(p,{*predicate,{"$schema"}},vars);
    }
    require(pending_origin.empty(),"artifact rule origin has no rule");
    for(const auto& [id,_]:p.observation_labels)
        require(p.observations.contains(id),"artifact reference lacks observation");
    for(const auto& [id,_]:p.linked_origins)
        require(p.observations.contains(id),"bound origin missing its observation");
    if(!p.experience_contexts.empty()){
        for(const auto& [_,context]:p.experience_contexts){
            map<string,Kind> vars;
            check_type(p,context,vars);
        }
        require(p.signatures.contains("outcome")&&p.signatures.at("outcome")==vector<Kind>{"sym","sym","sym"},
                "experience requires outcome(sym,sym,sym)");
    }
    for(const auto& source:p.feedback_sources)
        require(!p.experience_contexts.empty()&&p.sensor_policy.contains(source)&&p.sensor_policy.at(source)==set<string>{"outcome"}&&
                !p.adaptation.contains(source)&&!p.auto_policy.contains(source)&&!p.version_policy.contains(source)&&
                !p.workspace_recipes.contains(source)&&!p.native_synthesis.contains(source),
                "feedback channel must be explicitly authorized for outcomes only, not program changes");
    for(const auto& [source,relation]:p.measurement_sources){
        require(!p.experience_contexts.empty()&&relation!="outcome"&&relation!="measured_outcome"&&
                p.sensor_policy.contains(source)&&p.sensor_policy.at(source)==set<string>{relation}&&
                p.signatures.contains(relation)&&p.signatures.at(relation).size()==3,
                "measurement source must supply a raw, explicitly declared typed relation");
        const auto& types=p.signatures.at(relation);
        require(types[0]=="sym"&&types[1]=="sym"&&(types[2]=="i64"||types[2].starts_with("qty:"))&&
                p.signatures.contains("measured_outcome")&&
                p.signatures.at("measured_outcome")==vector<Kind>{"sym","sym","sym"}&&
                !p.feedback_sources.contains(source)&&!p.adaptation.contains(source)&&!p.auto_policy.contains(source)&&
                !p.version_policy.contains(source)&&!p.workspace_recipes.contains(source)&&!p.native_synthesis.contains(source),
                "measurement source cannot label or alter decisions");
        for(const auto& rule:p.rules)require(base_name(rule.head)!=relation,"raw measurement input is not rule-derived");
    }
    for(const auto& pref:p.preferences){
        map<string,Kind> vars;
        check_type(p,pref.proposition,vars);
        if(pref.when)check_type(p,*pref.when,vars);
    }
    if(!p.multi_policy.empty()){
        const auto& sig=p.signatures;
        require(sig.contains("ir_atom")&&sig.at("ir_atom")==vector<Kind>{"sym","i64","sym"}&&
                sig.contains("ir_arg")&&sig.at("ir_arg")==vector<Kind>{"sym","i64","i64","sym"},
                "invalid or absent multivariable IR signatures");
        for(const auto& [out,inputs]:p.multi_policy){
            require(sig.contains(out)&&!p.synth_policy.contains(out),"multivariable output needs explicit exclusive signature");
            for(const auto& in:inputs)require(sig.contains(in),"multivariable premise requires explicit signature");
            for(const auto& schema:p.schemas)
                require(schema.result!=out,"legacy schema cannot target multivariable output");
        }
    }
    for(const auto& [out,inputs]:p.synth_policy){
        const auto& sig=p.signatures;
        require(sig.contains(out)&&sig.at(out).size()==1,"synthesis output needs explicit unary signature");
        for(const auto& in:inputs)
            require(sig.contains(in)&&sig.at(in)==sig.at(out),"synthesis premise requires matching unary signature");
        for(const auto& schema:p.schemas)
            require(schema.result!=out,"legacy schema cannot target a CL self-authoring output");
    }
    if(!p.synth_policy.empty()){
        using K=Kind;
        require(p.signatures.contains("gen_head")&&
                p.signatures.at("gen_head")==vector<K>{"sym","sym","sym"}&&
                p.signatures.contains("gen_body")&&
                p.signatures.at("gen_body")==vector<K>{"sym","i64","sym","sym"},
                "invalid or absent generator ABI");
    }
    for(const auto& src:p.adaptation){
        require(p.sensor_policy.contains(src)&&(p.auto_policy.contains(src)||p.version_policy.contains(src)),
                "adaptive channel requires automatic rule or artifact policy");
        require(std::ranges::any_of(p.preferences,[](const auto& o){return o.hard&&!o.when;})&&
                std::ranges::any_of(p.preferences,[](const auto& o){return !o.hard;}),
                "adaptive channel requires an unconditional hard target and at least one wish");
    }
    for(const auto& [channel,outputs]:p.auto_policy){
        require(p.sensor_policy.contains(channel),"automatic source has no sensor policy");
        for(const auto& [output,guard]:outputs)
            require(p.synth_policy.contains(output)&&p.synth_policy.at(output).contains(guard),
                    "automatic guard must be an allowed synthesis premise");
    }
    for(const auto& [_,allowed]:p.sensor_policy)
        for(const auto& predicate:allowed)
            require(p.signatures.contains(predicate.starts_with("!")?predicate.substr(1):predicate),
                    "sensor policy needs an explicitly typed relation: "+predicate);
    for(const auto& [channel,phases]:p.workspace_recipes){
        const auto& w=phases.front();
        require(p.sensor_policy.contains(channel)&&p.sensor_policy.at(channel).contains(w.evidence)&&
                p.signatures.contains(w.evidence)&&p.signatures.at(w.evidence).size()==1&&p.signatures.at(w.evidence)[0].starts_with("qty:"),
                "workspace recipe requires explicitly authorized typed sensor evidence");
        if(w.choose){
            require(p.adaptation.contains(channel)&&p.version_policy.contains(channel)&&
                    p.version_policy.at(channel)==set<string>{w.alias}&&!p.auto_policy.contains(channel)&&
                    !p.native_synthesis.contains(channel),
                    "workspace evolution requires one explicit version alias and exclusive channel");
        }
    }
    for(const auto& [channel,policy]:p.native_synthesis)
        require(p.sensor_policy.contains(channel)&&p.sensor_policy.at(channel).contains(policy.evidence)&&
                p.version_policy.contains(channel)&&p.version_policy.at(channel).contains(policy.alias),
                "native synthesis requires explicitly authorized sensor evidence and version alias");
    validate_calculation_cycles(p.rules);
    validate_closed_folds(p);
    return p;
}
string rule_origin_id(const Program& p,size_t i){
    const auto& rule=p.rules.at(i);
    string material="PCGM-ORIGIN-2\n"+p.rule_labels.at(i)+"\n"+show(rule.head)+"\n";
    for(const auto& term:rule.body)material+=show(term)+"\n";
    if(const auto guard=p.live_guards.find(i);guard!=p.live_guards.end())material+="guard="+guard->second+"\n";
    return sha256(material);
}
Table run(const Program& p,const set<string>& inactive = {},const Table* guard_base=nullptr,JoinWork* work=nullptr,const set<Atom>* excluded=nullptr) {
    if(!guard_base&&!p.live_guards.empty()){
        auto ordinary=p;
        ordinary.live_guards.clear();
        ordinary.rules.clear();ordinary.rule_labels.clear();ordinary.rule_numbers.clear();
        for(size_t i=0;i<p.rules.size();++i)if(!p.live_guards.contains(i)){
            ordinary.rules.push_back(p.rules[i]);ordinary.rule_labels.push_back(p.rule_labels.at(i));
            if(!p.rule_numbers.empty())ordinary.rule_numbers.push_back(p.rule_numbers.at(i));
        }
        const auto base=run(ordinary,inactive,nullptr,work);
        return run(p,inactive,&base,work,excluded);
    }
    Table out; size_t probes=0, indexed=0;
    map<Atom,bool> verified_guard_facts;
    auto clean=[&](const Atom& a){
        auto [it,added]=verified_guard_facts.try_emplace(a,false);
        if(added)it->second=proof_without_conflict(*guard_base,a);
        return it->second;
    };
    vector<string> stable_origins;
    stable_origins.reserve(p.rules.size());
    for(size_t i=0;i<p.rules.size();++i)stable_origins.push_back(rule_origin_id(p,i));
    for(const auto& [id,a]:p.observations)
        if(!inactive.contains(id)&&(!excluded||!excluded->contains(a))){
            const auto loc=p.linked_origins.find(id), art=p.observation_labels.find(id);
            const auto origin="obs:"+id+(loc!=p.linked_origins.end()?"@"+loc->second:
                art!=p.observation_labels.end()?"@"+art->second:"");
            out.facts.try_emplace(a,Proof{origin,{},{},sha256("PCGM-OBSERVATION-2\n"+origin+"\n"+show(a))});
        }
    JoinIndex select(indexed,work);
    vector<const Atom*> recent;
    for(const auto& [f,_]:out.facts){select.add(&f);recent.push_back(&f);}
    for(size_t step=0; step<128; ++step) {
        if(work)++work->rounds;
        JoinIndex fresh(indexed,work);
        set<const Atom*> newest;
        for(const auto* f:recent){fresh.add(f);newest.insert(f);}
        map<Atom,Proof> delta;
        map<Atom,size_t> rule_priority;
        for(size_t ri=0;ri<p.rules.size();++ri) {
            const auto& r=p.rules[ri];
            using Env=map<string,string>;
            vector<const Atom*> witness;
            vector<Atom> checks;
            size_t pivot=r.body.size();
            function<void(size_t,const Env&)> visit=[&](size_t level,const Env& bound) {
                if(level==r.body.size()){
                    Atom f=r.head;
                    for(auto& a:f.args) if(variable(a)) a=bound.at(a);
                    if(auto g=p.live_guards.find(ri);g!=p.live_guards.end()){
                        if(!clean({g->second,f.args})||
                           guard_base->facts.contains({"!"+f.pred,f.args}))return;
                        // An automatic rule cannot use another automatic conclusion to justify itself.
                        for(const auto* proof:witness)if(!clean(*proof))return;
                    }
                    if(out.facts.contains(f)||(excluded&&excluded->contains(f)))return;
                    const auto previous=delta.find(f);
                    if(previous!=delta.end()&&rule_priority.at(f)!=ri)return;
                    Proof proof{"r"+to_string(p.rule_numbers.empty()?ri+1:p.rule_numbers.at(ri))+(p.rule_labels.at(ri).empty()?"":"@"+p.rule_labels.at(ri)),{},checks,stable_origins[ri]};
                    for (const auto* w:witness) proof.parents.push_back(*w);
                    if(previous!=delta.end()){
                        if(proof.parents<previous->second.parents)previous->second=std::move(proof);
                        return;
                    }
                    require(out.facts.size()+delta.size()<12000,"fact limit");
                    rule_priority.emplace(f,ri);
                    delta.emplace(std::move(f),std::move(proof));return;
                }
                const auto& pattern=r.body[level];
                if(comparison(pattern.pred)){
                    require(++probes<=2000000,"join budget");
                    if(work)++work->probes;
                    auto check=pattern;
                    auto next=bound;
                    const auto witnesses=witness.size();
                    auto count=[&]{
                        if(++probes>2000000)throw EvaluationLimit("join budget");
                        if(work)++work->probes;
                    };
                    const bool applies=unit_conversion(check.pred)?
                        lookup_unit_conversion(select,check,next,witness,count):fold_calculation(check.pred)?
                        lookup_closed_fold(p,select,check,next,witness,count):eval_builtin(check,next);
                    if(applies){checks.push_back(std::move(check));visit(level+1,next);checks.pop_back();}
                    witness.resize(witnesses);
                    return;
                }
                const auto& rows=(level==pivot?fresh:select).lookup(pattern,bound);
                for(const auto* f:rows){
                    if(pivot<r.body.size()&&level<pivot&&newest.contains(f))continue;
                    require(++probes<=2000000,"join budget");
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
        if(delta.empty()) return out;
        recent.clear();recent.reserve(delta.size());
        for(const auto& [fact,_]:delta){select.add(&fact);recent.push_back(&fact);}
        // Map merge moves nodes without invalidating pointers to their keys.
        out.facts.merge(delta);
    }
    throw runtime_error("fixpoint budget");
}
// Positive and negative support are independent. Conflicting witnesses do not
// silently justify a revision and lack of support is not a denial.
bool supported(const Table& t,const string& p,const string& x) {
    return t.facts.contains({p,{x}}) && !t.facts.contains({"!"+p,{x}});
}
string propose(const Program& p,const Table& t) {
    string generated;
    for (const auto& a:p.schemas) {
        Rule learned{{a.result,{"$x"}},{{a.premise,{"$x"}}}};
        if (std::ranges::find(p.rules,learned)!=p.rules.end()) continue;
        Atom lo{a.trigger,{""}};
        for(auto it=t.facts.lower_bound(lo); it!=t.facts.end() && it->first.pred==a.trigger; ++it) {
            auto& x=it->first.args[0];
            if(!supported(t,a.trigger,x)||!supported(t,a.premise,x)) continue;
            generated+="# witness "+show(it->first)+" "+show({a.premise,{x}})+"\n";
            generated+=a.result+"($x) <- "+a.premise+"($x).\n"; break;
        }
    }
    return generated;
}
string read_src(const fs::path& path){
    ifstream in(path,ios::binary); require(!!in,"cannot open CL source");
    string buf(256*1024+1,'\0'); in.read(buf.data(),buf.size());
    require(!in.bad() && in.gcount()<static_cast<streamsize>(buf.size()),"source read/size limit");
    buf.resize(static_cast<size_t>(in.gcount())); return buf;
}
void publish(const fs::path& dst,const string& body) {
    native_os::Descriptor parent(native_os::open_directory(fs::absolute(dst).parent_path()));
    native_os::atomic_local_commit(dst.filename().string(),parent.fd,body,".pcgm-new-",true,
       {"temp creation failed","write failed","flush failed","source already exists","replace failed","directory sync failed"});
}
string describe(const Proof& p) {
    string out=p.origin;
    for(const auto& parent:p.parents) out+=" "+show(parent);
    for(const auto& check:p.checks) out+=" [verified "+show(check)+"]";
    return out;
}
void explain(const Table& t,Atom a,ostream& cout=std::cout){
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
#include "continuity.inc"
#include "needs.inc"
#include "field_runtime.inc"
Atom opposite_of(Atom a){
    a.pred=a.pred.starts_with("!")?a.pred.substr(1):"!"+a.pred;
    return a;
}
string agenda_ticket_context(const Continuity&,const Program&,const Table&,const LocalQuestion&);
string question_status(const LocalQuestion& q,const Table& t,const set<Why>& gaps,const Continuity& state,const Program* program){
    const bool yes=t.facts.contains(q.fact), no=t.facts.contains(opposite_of(q.fact));
    if(yes)return no?"conflicted":"answered";
    if(no)return "opposed";
    if(!gaps.contains({q.goal,q.fact}))return "superseded";
    if(q.agenda&&(!program||agenda_ticket_context(state,*program,t,q).empty()))return "superseded";
    return "open";
}
pair<bool,bool> criteria_question_origin(const Program& p,const Atom& goal){
    bool guard=false,objective=false;
    if(p.criteria_questions)for(const auto& c:p.preferences)if(c.expected=="POSITIVE"){
        guard=guard||(c.when&&*c.when==goal&&!goal.pred.starts_with("!"));
        objective=objective||c.proposition==goal;
    }
    return {guard,objective};
}
set<Atom> criteria_question_goals(const Program& p,const Table& t){
    set<Atom> agenda;
    if(!p.criteria_questions)return agenda;
    const auto unknown=[&](const Atom& goal){return !t.facts.contains(goal)&&!t.facts.contains(opposite_of(goal));};
    // Respect authored ordering under the bounded supplement without displacing the ordinary proof goals.
    for(const auto& criterion:p.preferences){
        if(agenda.size()>=16)break;
        if(criterion.expected!="POSITIVE")continue;
        if(criterion.when&&!proof_without_conflict(t,*criterion.when)){
            if(!criterion.when->pred.starts_with("!")&&unknown(*criterion.when)&&!p.goals.contains(*criterion.when))agenda.insert(*criterion.when);
            continue;
        }
        if(unknown(criterion.proposition)&&!p.goals.contains(criterion.proposition))agenda.insert(criterion.proposition);
    }
    return agenda;
}
set<Why> open_gaps(const Program& p,const Table& t){
    const auto result=missing_inputs(p,t);
    set<Why> merged{result.begin(),result.end()};
    auto agenda=criteria_question_goals(p,t);
    if(!agenda.empty()){
        auto extra=p;
        extra.goals=std::move(agenda);
        const auto clauses=missing_inputs(extra,t);
        merged.insert(clauses.begin(),clauses.end());
    }
    return merged;
}
bool matches_question(const LocalQuestion& q,const Atom& f){
    return q.fact==f||opposite_of(q.fact)==f;
}


#include "cycle.inc"
#include "revision.inc"
#include "synth.inc"
#include "artifact-revisions.inc"
#include "live-guard.inc"
#include "activation.inc"
#include "experience.inc"
#include "choice.inc"
#include "proof-integrity.inc"
#include "dialogue.inc"
#include "episodic.inc"
#include "transfer.inc"
#include "ready.inc"
#include "compiled-ir.inc"
#include "artifact.inc"
#include "proof-json.inc"
#include "decision-trace.inc"
#include "workspace-cycle-recipes.inc"
#include "subscriptions.inc"
#define PCGM_SLICE_GUARDS
#include "query-slice.inc"
#include "compute-planes.inc"
#undef PCGM_SLICE_GUARDS
#include "question-wire.inc"
#include "choice-jobs.inc"
#include "sensor-ingress.inc"
#include "observation-batch.inc"
#include "read-channel.inc"
#include "win-pipe.inc"
#include "handoff.inc"
#include "anchored-enrollment.inc"
#include "frozen-admission.inc"
#include "resident-obligation.inc"
#include "quantity-question.inc"
#include "choice-capsule.inc"
#include "bounded-repair.inc"

int main(int argc,char** argv) {
    _setmode(0,_O_TEXT);_setmode(1,_O_BINARY);
    try {
        if(argc>=2&&string(argv[1])=="--capabilities"){
            require(argc==2,"usage: pcgm --capabilities");
            cout<<"{\"schema\":\"pcgm-runtime-capabilities-v1\",\"release\":\"0.159\","
                <<"\"engine_role\":\"continuity_and_decisions\",\"evaluation_backend\":\"cpu\",\"projection_backend\":\"guarded_cuda_or_cpu\",\"gpu_policy\":{\"reserve_mib\":3072,\"stop_c\":87,\"load_target\":99},"
                <<"\"endpoint\":"<<quote_json(build_name)<<",\"binary_sha256\":"<<quote_json(local_binary_hash())
                <<",\"state_opened\":false,\"formats\":[\"PCGM-STATE-1\",\"PCGM-COMPACT-1\",\"CLIR-8\"],"
                <<"\"features\":[\"managed_ab_handoff\",\"observation_batch\","
                <<"\"observation_batch_audit\",\"choice_attribution\"]}\n";
            return 0;
        }

        if(argc>=2&&string(argv[1])=="--export-choice-capsule"){
            require(argc==5,"usage: pcgm --export-choice-capsule STATE CHOICE HEAD_SHA256");
            cout<<export_choice_capsule(argv[2],argv[3],argv[4]);return 0;
        }
        if(argc>=2&&string(argv[1])=="--verify-choice-capsule"){
            require(argc==6,"usage: pcgm --verify-choice-capsule CAPSULE CAPSULE_SHA256 BASIS_SHA256 RECEIPT_SHA256");
            cout<<check_choice_capsule(argv[2],argv[3],argv[4],argv[5])<<'\n';return 0;
        }
        if(argc>=2&&string(argv[1])=="--frozen-question-integrity"){
            require(argc==9,"usage: pcgm --frozen-question-integrity STATE TICKET REQUEST_SHA ARTIFACT ARTIFACT_SHA PACKAGE_SHA SNAPSHOT_SHA");
            cout<<review_frozen_question(argv[2],argv[3],argv[4],argv[5],argv[6],argv[7],argv[8],true)<<'\n';return 0;
        }
        if(argc==2&&string(argv[1])=="--field-selfcheck"){
            GeometricRuntime first,replay;
            cout<<"primordial_set={";
            bool comma=false;
            for(const auto& d:instinct::primordial_directions){if(comma)cout<<",";cout<<d;comma=true;}
            cout<<"} kind=unordered direction_only\n";
            cout<<"initial "<<first.status()<<'\n';
            first.begin(GeometricRuntime::index(GeometricRuntime::contexts,"quiet"));
            first.apply(GeometricRuntime::index(GeometricRuntime::actions,"wait"));
            replay.replay({GeometricRuntime::init_event,"field_tick quiet wait"});
            require(first.status()==replay.status(),"geometry replay differs");
            cout<<"replayed "<<replay.status()<<'\n';return 0;
        }
        if(argc==3&&string(argv[1])=="--desktop-snapshot"){
            StateStore store(fs::absolute(argv[2]),false);
            string head;auto s=store.load(&head);
            cout<<"{\"individual\":"<<quote_json(s.id)<<",\"owner\":"<<quote_json(s.owner)
                <<",\"head\":"<<quote_json(head)<<",\"source\":"<<quote_json(s.source)<<",\"inactive\":[";
            bool first=true;for(const auto& id:s.inactive){if(!first)cout<<',';cout<<quote_json(id);first=false;}
            cout<<"]}\n";return 0;
        }
        if(argc>=2&&string(argv[1])=="--frozen-question-review"){
            require(argc==9,"usage: pcgm --frozen-question-review STATE TICKET REQUEST_SHA ARTIFACT ARTIFACT_SHA PACKAGE_SHA SNAPSHOT_SHA");
            cout<<review_frozen_question(argv[2],argv[3],argv[4],argv[5],argv[6],argv[7],argv[8])<<'\n';return 0;
        }
        if(argc>=2&&string(argv[1])=="--workspace-question-review"){
            require(argc==8,"usage: pcgm --workspace-question-review STATE TICKET REQUEST_SHA ARCHIVE ARCHIVE_SHA LOCK_SHA");
            cout<<review_workspace_question(argv[2],argv[3],argv[4],argv[5],argv[6],argv[7])<<'\n';return 0;
        }
        if(argc>=2&&string(argv[1])=="--question-bundle-review"){
            require(argc==7||argc==11,
                    "usage: pcgm --question-bundle-review STATE TICKET REQUEST_SHA256 PACKAGE PACKAGE_SHA256 [ROUNDS FACTS PROBES INDEXED]");
            cl_native::EvaluationCeilings cap{128,12000,2000000,2000000};
            if(argc==11)cap={sequence_number(argv[7]),sequence_number(argv[8]),sequence_number(argv[9]),sequence_number(argv[10])};
            cout<<review_question_bundle(argv[2],argv[3],argv[4],argv[5],argv[6],cap)<<'\n';
            return 0;
        }

        if(argc==5&&string(argv[1])=="--fifo-query")
            return fifo_query(argv[2],sequence_number(argv[3]),argv[4]);
        if((argc==4||argc==5)&&string(argv[1])=="--serve-fifo")
            return serve_fifo_reader(argv[2],argv[3],argc==5?sequence_number(argv[4]):2);

        if(argc==2&&string(argv[1])=="--ask-basic-arithmetic")return quantity_question_channel();
        if(argc>=2&&(string(argv[1])=="--resume-obligation-local"||string(argv[1])=="--resume-agenda-local")){
            require(argc==4,"resident obligation expects STATE APPROVAL_FD");
            const auto fd=sequence_number(argv[3]);
            require(fd>2&&fd<=numeric_limits<uintptr_t>::max(),"resident approval handle out of range");
            const auto state_path=fs::absolute(argv[2]);
            StateStore writer(fs::canonical(state_path.parent_path())/state_path.filename(),true);
            return resident_obligation(writer,static_cast<uintptr_t>(fd),string(argv[1])=="--resume-agenda-local");
        }
        if(argc>=2&&string(argv[1])=="--enroll-anchored-obligation"){
            require(argc==5,"obligation enrollment expects STATE APPROVAL APPROVAL_SHA256");
            const auto state_path=fs::absolute(argv[2]);
            StateStore writer(fs::canonical(state_path.parent_path())/state_path.filename(),true);
            const auto approval=native_os::read_regular_input(fs::path(argv[3]),1024,{
                "cannot open approval directory","cannot open obligation approval","obligation approval is not regular",
                "cannot read obligation approval","obligation approval exceeds size limit"});
            cout<<enroll_anchored_review(writer,approval,argv[4]);return 0;
        }
        if(argc==3&&string(argv[1])=="--read-channel")return read_channel(argv[2]);
        if(argc==4&&(string(argv[1])=="--export"||string(argv[1])=="--export-compact"||string(argv[1])=="--export-complete"||string(argv[1])=="--export-portable-policies")){
            const auto kind=string(argv[1]);
            export_transfer(argv[2],argv[3],kind=="--export-compact",kind=="--export-complete"||kind=="--export-portable-policies",
                            kind=="--export-portable-policies");return 0;
        }
        if(argc==4&&string(argv[1])=="--restore-copy"){
            restore_transfer(argv[2],argv[3]);return 0;
        }
        const bool importing=argc==5 && string(argv[1])=="--import-managed";
        const bool managed=importing || (argc==4 && string(argv[1])=="--init-managed");
        const bool init=managed || (argc==4 && string(argv[1])=="--init");
        const bool sensor_feed=argc==3 && string(argv[1])=="--resume-sensor-feed";
        const bool resume=argc==3 && (string(argv[1])=="--resume"||sensor_feed);
        const bool active_prepare=argc==3&&string(argv[1])=="--prepare";
        const bool inspect=active_prepare||(argc==3 && string(argv[1])=="--inspect");
        const bool claim=argc==4 && string(argv[1])=="--claim";
        const bool cancel=argc==4 && string(argv[1])=="--cancel-handoff";
        const bool activate=argc==4&&string(argv[1])=="--activate-restored"&&string(argv[3])=="--source-stopped";
        const bool loading=resume||inspect||claim||cancel||activate;
        const bool legacy=argc==2 || (argc==4&&string(argv[2])=="--revise");
        require(init||loading||legacy,
                "usage: pcgm --init SOURCE STATE | --init-managed SOURCE STATE | --resume STATE | --inspect STATE | --claim STATE NONCE | --cancel-handoff STATE NONCE");
        cout << std::unitbuf;
        std::optional<StateStore> store;
        Continuity state;
        string own_hash;
        if(init||loading){
            auto path=fs::absolute(argv[loading?2:3]);
            store.emplace(fs::canonical(path.parent_path())/path.filename(),!inspect);
        }
        if(loading){
            state=store->load();
            verify_pending_state(state);
            if(inspect||claim||cancel||!state.owner.empty())own_hash=local_binary_hash();
            if(!inspect && !activate)
                require(state.staged_copy.empty(),"restored copy is read-only until explicit activation");
            if(activate)require(!state.staged_copy.empty(),"no staged restored copy");
            if(claim||cancel){
                require(state.pending.has_value(),"no handoff pending");
                const auto& h=*state.pending;
                require(h.nonce==argv[3],"handoff receipt does not match");
                require(build_name==(claim?h.to:h.from)&&own_hash==(claim?h.to_hash:h.from_hash),
                        "binary is not the prepared handoff endpoint");
            }else if(!inspect){
                require(!state.pending,"handoff pending; claim or cancel using its receipt");
                require(state.owner.empty()||(state.owner==build_name&&state.owner_hash==own_hash),
                        "managed state belongs to a different runtime build");
            }
        }else{
            state.source=read_src(argv[init?2:1]);
            if(init) state.id=importing?string(argv[4]):new_id();
            if(importing)require(valid_identity(state.id),"malformed imported identity");
            if(managed){
                own_hash=local_binary_hash();
                Parser bn{build_name};bn.name();bn.end();
                state.owner=build_name;state.owner_hash=own_hash;
                state.events.push_back("owner "+build_name+" "+own_hash);
            }
        }
        for(const auto& id:state.active_revisions)expect_patch(state,state.plans.at(id));
        auto epoch=compile_active(state);
        if(loading){
            for(const auto& e:state.events) if(e.starts_with("withdraw ") || e.starts_with("restore "))
                require(epoch.observations.contains(e.substr(e.starts_with("withdraw ")?9:8)),
                        "persistent evidence refers to an unknown observation");
        }
        for(const auto& id:state.recorded_observations)
            require(epoch.observations.contains(id),"recorded observation missing from CL source");
        for(const auto& [_,q]:state.questions){
            const auto [guard,objective]=criteria_question_origin(epoch,q.goal);
            require((epoch.goals.contains(q.goal)||guard||objective)&&epoch.arity.contains(q.fact.pred),
                    "question references undeclared goal or premise");
            map<string,Kind> vars;
            check_type(epoch,q.fact,vars);
        }
        for(const auto& [id,ticket]:state.receipt_question)
            require(matches_question(state.questions.at(ticket),epoch.observations.at(id)),
                    "recorded answer does not match question");
        for(const auto& [key,receipt]:state.cycles){
            const auto& [src,n]=key;
            require(epoch.sensor_policy.contains(src),"cycle has no associated sensor policy");
            for(unsigned i=1;i<=receipt.observations;++i)
                require(epoch.sensor_policy.at(src).contains(epoch.observations.at(cycle_obs_id(src,n,i)).pred),
                        "cycle contains an unauthorized predicate");
        }
        for(const auto& [_,versions]:state.workspace_proof_origins)
            for(const auto& [package_pin,origin]:versions)
                for(const auto& [id,fact]:origin.source_facts)
                    require(epoch.observations.contains(id)&&epoch.observations.at(id)==fact,
                            "native CL recipe proof differs from admitted source fact");
        for(const auto& [_,session]:state.dialogues)
            if(session.focus)require(epoch.goals.contains(*session.focus),"persisted dialogue target is undeclared");
        auto table=run(epoch,state.inactive);
        optional<GeometricRuntime> geometry;
        if(state.has_field){geometry.emplace();geometry->replay(state.events);}
        if(inspect||claim||activate){
            for(const auto& pin:transferable_pins(state))verify_episode(*store,state,pin);
            for(const auto& part:state.archives)verify_archive(*store,state,part);
        }
        if(inspect){
            if(active_prepare){
                require(!state.pending&&state.staged_copy.empty(),"cannot prepare against pending/offline state");
                ticket_ready(*store,build_name,own_hash,state_hash(state));
            }
            cout<<(active_prepare?"prepared":"inspection")<<" individual="<<state.id<<" event="<<state.events.size()
                <<" epoch="<<state.epoch<<" build="<<build_name<<" binary_sha256="<<own_hash
                <<" snapshot_sha256="<<state_hash(state)<<'\n';
            if(!state.staged_copy.empty())cout<<"restored_copy_staged true\n";
            if(state.pending)
                cout<<"pending_handoff to="<<state.pending->to<<" nonce="<<state.pending->nonce<<'\n';
            return 0;
        }
        if(activate){
            state.events.push_back("activated_copy "+state.staged_copy);
            state.staged_copy.clear();
            store->save(state);
        }
        if(claim||cancel){
            const auto h=*state.pending;
            if(claim){state.owner=h.to;state.owner_hash=h.to_hash;}
            state.pending.reset();
            state.events.push_back((claim?"claimed ":"handoff_cancelled ")+h.nonce);
            store->save(state);
        }
        if(init) store->save(state,true);
        if(sensor_feed){
            cout<<std::unitbuf<<"{\"schema\":\"pcgm-sensor-feed-v1\",\"individual\":"<<quote_json(state.id)
                <<",\"event\":"<<state.events.size()<<"}\n";
        }else{
        if(store) cout<<"individual="<<state.id<<" event="<<state.events.size()<<" ";
        cout<<"epoch="<<state.epoch<<" facts="<<table.facts.size();
        if(store) cout<<" observation_version="<<state.observation_version;
        if(!state.owner.empty())cout<<" owner="<<state.owner;
        cout<<'\n';
        }
        struct StagedProfileBuild {cl_native::ProfileProduct output;string snapshot;optional<SynthesisOrigin> synthesis;};
        map<string,StagedProfileBuild> staged_builds;
        optional<LiveChoiceJob> choice_job;
        bool revised=false;
        string line;
        bool oversized=false;
        while(sensor_feed?request_line(cin,line,oversized):bool(getline(cin,line))){
            string correlation;
            optional<FeedAddress> addressed;
            try {
                require(!oversized&&line.size()<=512,"query line limit");
                if(sensor_feed){
                    if(line.find(" reconcile ")!=string::npos){
                        istringstream in(line);string id,op,individual,source,seq,digest,extra;
                        require(bool(in>>id>>op>>individual>>source>>seq>>digest)&&!(in>>extra)&&op=="reconcile",
                                "expected ID reconcile INDIVIDUAL SOURCE SEQUENCE PACKET_SHA256");
                        Parser response{id};require(response.name()==id,"invalid sensor feed address");response.end();
                        correlation=id;
                        Parser sensor{source};require(sensor.name()==source,"invalid sensor source label");sensor.end();
                        require(individual==state.id,"sensor reconciliation is addressed to another individual");
                        require(line==id+" reconcile "+individual+" "+source+" "+seq+" "+digest,
                                "sensor reconciliation frame is not canonical");
                        const auto exact=reconcile_sensor(state,source,sequence_number(seq),digest);
                        cout<<"{\"schema\":\"pcgm-sensor-receipt-v1\",\"id\":"<<quote_json(id)
                            <<",\"ok\":true,\"reconciliation\":"<<exact<<"}\n";
                        continue;
                    }
                    addressed=sensor_ingress_frame(line,correlation);
                    require(addressed->individual==state.id,"sensor feed request is addressed to another individual");
                    line=":cycle "+addressed->packet;
                }
                if(line==":experiences"){
                    require(store.has_value(),"persistent state not enabled");
                    const auto memory=read_experiences(state);
                    const auto here=experience_context(epoch,table);
                    cout<<"experience_context "<<(here?*here:"unknown")<<'\n';
                    for(const auto& [event,row]:memory){
                        if(row.observation.empty())continue;
                        const auto evidence=feedback_value(state,epoch,table,event,row);
                        cout<<"experience "<<event<<" "<<row.kind<<" context="<<row.context<<" source="<<row.observation
                            <<" "<<(evidence?"valid":"inactive")<<'\n';
                    }
                    continue;
                }
                if(line.starts_with(":feedback ")){
                    require(store.has_value(),"persistent state not enabled");
                    Parser q{line.substr(10)};const auto event=q.name(), id=q.name();q.end();
                    const auto memory=read_experiences(state);
                    require(memory.contains(event)&&!memory.at(event).context.empty(),"decision lacks a verified historical context");
                    auto row=memory.at(event);
                    if(!row.observation.empty()){
                        require(row.observation==id,"experience already linked to another observation");
                        cout<<"feedback_unchanged "<<event<<'\n';continue;
                    }
                    require(count_if(memory.begin(),memory.end(),[](const auto& entry){
                        return !entry.second.observation.empty();
                    })<128,"experience record limit");
                    row.observation=id;
                    require(feedback_value(state,epoch,table,event,row).has_value(),"feedback lacks newer uncontested direct evidence");
                    auto next=state;
                    next.events.push_back("experience "+event+" "+id);
                    store->save(next);state=std::move(next);
                    cout<<"feedback_recorded "<<event<<" source="<<id<<'\n';
                    continue;
                }
                if(line.starts_with(":stage_from_evidence ")){
                    require(store.has_value(),"persistent state not enabled");
                    istringstream args(line.substr(21));
                    string alias,profile,base,generator,scope,snapshot,relation,extra;
                    require(bool(args>>alias>>profile>>base>>generator>>scope>>snapshot>>relation)&&!(args>>extra),
                            "expected ALIAS PROFILE BASE GENERATOR SCOPE SNAPSHOT EVIDENCE_RELATION");
                    for(const auto& digest:{profile,base,generator,scope,snapshot})require(digest.size()==64&&hex_chars(digest),"invalid synthesis digest");
                    Parser x{alias},y{relation};(void)x.name();x.end();(void)y.name();y.end();
                    require(alias.size()<=12&&(!state.artifacts.contains(alias)||state.generated_artifacts.contains(alias)),"incompatible synthesis alias");
                    require(snapshot==state_hash(state),"native compiler stage snapshot changed");
                    require(epoch.signatures.contains(relation),"synthesis requires an explicit evidence signature");
                    require(staged_builds.size()<4||staged_builds.contains(alias),"native compiler stage limit");
                    string evidence;size_t picked=0;
                    for(const auto& [atom,_]:table.facts)if(atom.pred==relation){
                        require(proof_without_conflict(table,atom),"contradicted or unreviewable synthesis evidence");
                        require(++picked<=16,"synthesis evidence count limit");
                        evidence+="& native_evidence_"+to_string(picked)+" "+show(atom)+".\n";
                    }
                    require(picked>0,"no clean synthesis evidence available");
                    const auto root=store->dst.parent_path()/"build_inputs";
                    auto product=cl_native::synthesize_profile_bytes(
                        read_transfer_file(root,alias+".clcp",1024*1024),profile,
                        read_transfer_file(root,alias+".cl",256*1024),base,
                        read_transfer_file(root,alias+".generator.cl",256*1024),generator,
                        read_transfer_file(root,alias+".scope",32768),scope,evidence);
                    const auto output=product.product.ir_sha256,evidence_hash=product.evidence_sha256;
                    staged_builds.insert_or_assign(alias,StagedProfileBuild{move(product.product),snapshot,
                        SynthesisOrigin{product.generator_sha256,product.scope_sha256,product.evidence_sha256}});
                    cout<<"cl_synth_staged "<<alias<<" ir_sha256="<<output<<" evidence_sha256="<<evidence_hash<<'\n';
                    continue;
                }
                if(line.starts_with(":stage_cl ")||line.starts_with(":commit_cl ")){
                    require(store.has_value(),"persistent state not enabled");
                    const bool stage=line.starts_with(":stage_cl ");
                    istringstream args(line.substr(stage?10:11));
                    string word,first,second,snapshot,extra;
                    require(bool(args>>word>>first>>second),"missing CL compiler stage arguments");
                    if(stage)require(bool(args>>snapshot),"expected PCGM snapshot SHA-256");
                    else snapshot=second;
                    require(!(args>>extra)&&first.size()==64&&second.size()==64&&snapshot.size()==64&&
                        hex_chars(first)&&hex_chars(second)&&hex_chars(snapshot),"invalid compiled image or snapshot digest");
                    Parser q{word};const auto alias=q.name();q.end();
                    require(alias.size()<=12&&(!state.artifacts.contains(alias)||state.generated_artifacts.contains(alias)),
                        "CL compiler alias belongs to a different artifact or is too long");
                    require(snapshot==state_hash(state),"native compiler stage snapshot changed");
                    if(stage){
                        require(staged_builds.size()<4||staged_builds.contains(alias),"native compiler stage limit");
                        const auto inputs=store->dst.parent_path()/"build_inputs";
                        auto compiled=cl_native::build_profile_bytes(
                            read_transfer_file(inputs,alias+".clcp",1024*1024),first,
                            read_transfer_file(inputs,alias+".cl",256*1024),second);
                        const auto digest=compiled.ir_sha256;
                        staged_builds.insert_or_assign(alias,StagedProfileBuild{move(compiled),snapshot,nullopt});
                        cout<<"cl_staged "<<alias<<" ir_sha256="<<digest<<" snapshot_sha256="<<snapshot<<'\n';
                        continue;
                    }
                    const auto staged=staged_builds.find(alias);
                    require(staged!=staged_builds.end()&&staged->second.snapshot==snapshot&&
                            staged->second.output.ir_sha256==first,"unverified or stale native compiler candidate");
                    const auto& compiled=staged->second.output;
                    auto next=state;
                    const bool updating=state.generated_artifacts.contains(alias);
                    bool retain_new_origin=true;
                    if(updating){
                        const auto prior=state.artifacts.at(alias);
                        require(prior!=first,"compiled CL candidate already active");
                        if(state.generated_artifacts.at(alias).contains(first)){
                            const auto& origin=state.generated_artifacts.at(alias).at(first);
                            require(origin.profile==compiled.profile_sha256&&origin.source==compiled.source_sha256,
                                    "compiled output already retained under different source provenance");
                            retain_new_origin=false;
                        }
                        next=prepare_artifact_switch(state,epoch,*store,alias,prior,first,&compiled.ir);
                    }else{
                        const auto decoded=from_image(compiled.ir);
                        next.source+="\n"+normalize_artifact(epoch,decoded.first,alias,first)+artifact_marker("end",alias,first);
                        next.artifacts.emplace(alias,first);
                        next.events.push_back("artifact "+alias+" "+first);
                        ++next.epoch;
                    }
                    if(retain_new_origin){
                        auto& history=next.generated_artifacts[alias];
                        require(history.size()<artifact_version_limit&&history.emplace(first,
                            CompilerOrigin{compiled.profile_sha256,compiled.source_sha256,first}).second,"generated artifact provenance limit");
                        next.events.push_back(string(updating?"artifact_generated_revision ":"artifact_generated ")+alias+" "+
                            compiled.profile_sha256+" "+compiled.source_sha256+" "+first);
                    }
                    if(retain_new_origin&&staged->second.synthesis){
                        const auto& proof=*staged->second.synthesis;
                        next.synthesized_artifacts[alias].emplace(first,proof);
                        next.events.push_back("artifact_synthesized "+alias+" "+first+" "+proof.generator+" "+proof.scope+" "+proof.evidence);
                    }
                    auto applied=compile_active(next);
                    if(updating)check_artifact_interface(epoch,applied,"artifact_"+alias+"__");
                    auto table_now=run(applied,next.inactive);
                    Option assessment("generated");
                    score(assessment,epoch,table,table_now);
                    require(assessment.error.empty(),assessment.error);
                    add_notices(next,table,table_now);
                    store->save(next);
                    state=move(next);epoch=move(applied);table=move(table_now);
                    staged_builds.erase(staged);
                    cout<<"cl_committed "<<alias<<" ir_sha256="<<first<<" epoch="<<state.epoch<<'\n';
                    continue;
                }
                if(line==":packages"){
                    require(store.has_value(),"persistent state not enabled");
                    size_t count=0;
                    for(const auto& [alias,versions]:state.package_versions)for(const auto& record:versions){
                        ++count;
                        cout<<"package "<<alias<<" package_sha256="<<record.first<<" ir_sha256="<<record.second
                            <<" active="<<(state.artifacts.at(alias)==record.second?"yes":"no")<<'\n';
                    }
                    cout<<"packages_end count="<<count<<'\n';continue;
                }
                if(line.starts_with(":install_ir ")||line.starts_with(":install_pkg ")||line.starts_with(":install_scoped_pkg ")||
                   line.starts_with(":install_workspace ")){
                    require(store.has_value(),"persistent state not enabled");
                    const bool scoped=line.starts_with(":install_scoped_pkg ");
                    const bool workspace=line.starts_with(":install_workspace ");
                    const bool package=scoped||workspace||line.starts_with(":install_pkg ");
                    istringstream args(line.substr(workspace?19:scoped?20:package?13:12));string word,digest,profile,extra;
                    require(bool(args>>word>>digest)&&((!scoped&&!workspace)||bool(args>>profile))&&!(args>>extra),
                            "expected ARTIFACT PACKAGE_SHA256 [REQUIRED_SCOPE_SHA256]");
                    require((!scoped&&!workspace)||(profile.size()==64&&hex_chars(profile)),"invalid required CL policy or workspace digest");
                    Parser name{word};const auto alias=name.name();name.end();
                    require(alias.size()<=12&&digest.size()==64&&hex_chars(digest),"invalid artifact identity");
                    if(const auto old=state.artifacts.find(alias);old!=state.artifacts.end()){
                        if(workspace)require(state.workspace_locks.contains(alias)&&workspace_active_lock(state,alias)==profile,
                                             "already installed workspace has a different dependency lock");
                        if(scoped)require(state.scope_policies.contains(alias)&&state.scope_policies.at(alias)==profile,
                                          "already installed alias has a different scope policy");
                        if(package){
                            const auto record=state.package_versions.find(alias);
                            require(record!=state.package_versions.end()&&record->second.contains(digest)&&record->second.at(digest)==old->second,
                              "package alias already bound to another package or rule version");
                            cout<<"package_unchanged "<<alias<<" sha256="<<digest<<'\n';
                        }else{
                            require(old->second==digest,"artifact alias is already bound to another digest");
                            cout<<"artifact_unchanged "<<alias<<" sha256="<<digest<<'\n';
                        }
                        continue;
                    }
                    auto image=read_transfer_file(store->dst.parent_path()/"imports",alias+(workspace?".clw":package?".clpkg":".clir"),workspace?16*1024*1024:ir_size_limit);
                    require(sha256(image)==digest,package?"package transfer digest mismatch":"artifact byte digest mismatch");
                    string inner=digest,api,scope_report,workspace_archive;
                    if(package){
                        auto validated=workspace?cl_native::verify_workspace_bytes(image,profile):cl_native::verify_package_bytes(image);
                        require(validated.package_sha256==digest,"independent CL package digest mismatch");
                        require(scoped?validated.scope_policy_sha256==profile:validated.scope_policy_sha256.empty(),
                                scoped?"package does not satisfy the required CL module policy":"use explicit scoped installation for this package");
                        scope_report=workspace?std::move(validated.workspace_audit_sha256):std::move(validated.scope_report_sha256);
                        inner=std::move(validated.ir_sha256);
                        api=std::move(validated.api_sha256);
                        if(workspace)workspace_archive=std::move(image);
                        image=std::move(validated.ir);
                    }
                    const auto artifact=from_image(image);
                    const auto frozen=normalize_artifact(epoch,artifact.first,alias,inner)+artifact_marker("end",alias,inner);
                    auto next_state=state;
                    next_state.source+="\n"+frozen;
                    ++next_state.epoch;
                    next_state.events.push_back("artifact "+alias+" "+inner);
                    next_state.artifacts.emplace(alias,inner);
                    if(package){
                        next_state.events.push_back("artifact_package "+alias+" "+digest+" "+inner);
                        next_state.installed_packages.emplace(alias,make_pair(digest,inner));
                        next_state.package_versions[alias].emplace(digest,inner);
                        next_state.events.push_back("artifact_package_contract "+alias+" "+api);
                        next_state.package_contracts.emplace(alias,api);
                        if(scoped){
                            next_state.scope_policies.emplace(alias,profile);
                            next_state.scope_origins[alias].emplace(digest,ScopeOrigin{profile,scope_report});
                            next_state.events.push_back("artifact_scope "+alias+" "+digest+" "+profile+" "+scope_report);
                        }else if(workspace){
                            next_state.workspace_locks.emplace(alias,profile);
                            next_state.workspace_authorized[alias].insert(profile);
                            next_state.workspace_origins[alias].emplace(digest,ScopeOrigin{profile,scope_report});
                            next_state.events.push_back("artifact_workspace "+alias+" "+digest+" "+profile+" "+scope_report);
                        }
                    }
                    auto next=compile_active(next_state);auto next_table=run(next,next_state.inactive);
                    add_notices(next_state,table,next_table);
                    if(workspace)keep_workspace_archive(*store,digest,workspace_archive);
                    store->save(next_state);
                    state=std::move(next_state);epoch=std::move(next);table=std::move(next_table);
                    if(package)cout<<"package_installed "<<alias<<" package_sha256="<<digest<<" ir_sha256="<<inner<<'\n';
                    else cout<<"artifact_installed "<<alias<<" epoch="<<state.epoch<<" sha256="<<digest<<'\n';
                    continue;
                }
                if(line.starts_with(":retain_workspace_dependencies ")||line.starts_with(":retain_workspace_source ")||
                   line.starts_with(":retain_workspace_recipe ")||line.starts_with(":retain_workspace_additive ")){
                    const bool from_additive=line.starts_with(":retain_workspace_additive ");
                    const bool from_recipe=line.starts_with(":retain_workspace_recipe ");
                    const bool from_source=from_recipe||from_additive||line.starts_with(":retain_workspace_source ");
                    require(store.has_value(),"persistent PCGM state required");
                    istringstream in(line.substr(line.find(' ')+1));
                    string alias,prior,old_lock,first,second,boundary,base,evidence,extra;
                    const auto hash=[](const string& h){return h.size()==64&&hex_chars(h);};
                    require(bool(in>>alias>>prior>>old_lock>>first>>second)&&(!(from_recipe||from_additive)||bool(in>>boundary))&&
                            bool(in>>base)&&(!from_recipe||bool(in>>evidence))&&!(in>>extra)&&hash(prior)&&
                            hash(old_lock)&&hash(first)&&hash(second)&&hash(base)&&
                            (!(from_recipe||from_additive)||hash(boundary))&&(from_source||old_lock!=first),
                            "expected ALIAS ACTIVE_IR ACTIVE_LOCK then candidate lock/archive or baseline archive/source, and expected state SHA-256");
                    Parser a{alias};require(a.name()==alias&&alias.size()<=12,"invalid workspace alias");a.end();
                    require(state.workspace_locks.contains(alias)&&state.artifacts.at(alias)==prior&&
                            workspace_active_lock(state,alias)==old_lock&&state_hash(state)==base,
                            "workspace dependency candidate baseline changed");
                    const auto& history=state.package_versions.at(alias);
                    if(from_source)require(history.contains(first)&&history.at(first)==prior,"workspace source baseline archive is not active");
                    auto file=from_source?read_retained_workspace(*store,alias,first):
                                         read_transfer_file(store->dst.parent_path()/"imports",alias+".clw",16*1024*1024);
                    string candidate_archive;
                    const auto new_lock=from_source?old_lock:first;
                    cl_native::VerifiedPackage verified;
                    string source_digest;
                    string evidence_digest;
                    if(from_additive){
                        const auto root=store->dst.parent_path()/"build_inputs";
                        const auto text=read_transfer_file(root,alias+".cl",256*1024);
                        const auto goals=read_transfer_file(root,alias+".goals",32*1024);
                        candidate_archive=cl_native::fork_workspace_additive(file,first,old_lock,text,second,goals,boundary);
                        source_digest=second;
                        verified=cl_native::verify_workspace_bytes(candidate_archive,old_lock);
                    }else if(from_source){
                        const auto root=store->dst.parent_path()/"build_inputs";
                        auto rebuilt=[&](){
                            if(!from_recipe){
                                const auto text=read_transfer_file(root,alias+".cl",256*1024);
                                return cl_native::rebuild_workspace_source(file,first,old_lock,text,second);
                            }
                            Parser parser{evidence};const auto fact=parser.atom();parser.end();
                            require(fact.args.size()==1&&!fact.pred.starts_with('!')&&show(fact)==evidence&&
                                    std::ranges::none_of(fact.args,variable)&&proof_without_conflict(table,fact),
                                    "workspace recipe requires a clean grounded fact in the live PCGM revision");
                            evidence_digest=sha256(evidence);
                            return cl_native::synthesize_workspace_quantity(file,first,old_lock,
                                pinned_recipe_member(*store,alias+".recipe.clir",second,256*1024),second,
                                pinned_recipe_member(*store,alias+".recipe.scope",boundary,16*1024),boundary,evidence);
                        }();
                        source_digest=std::move(rebuilt.source_sha256);
                        candidate_archive=std::move(rebuilt.archive);
                        verified=std::move(rebuilt.product);
                    }else{
                        require(sha256(file)==second,"workspace candidate archive digest mismatch");
                        verified=cl_native::verify_workspace_bytes(file,new_lock);
                        candidate_archive=std::move(file);
                    }
                    const auto outer=verified.package_sha256;
                    require(from_additive||verified.api_sha256==workspace_contract_by_image(state,alias,prior),"workspace dependency candidate public contract changed");
                    const auto image=verified.ir_sha256;
                    require(history.size()<artifact_version_limit&&!history.contains(outer)&&
                            std::ranges::none_of(history,[&](const auto& row){return row.second==image;}),
                            "workspace dependency candidate already exists or family is full");
                    auto trial=prepare_artifact_switch(state,epoch,*store,alias,prior,image,&verified.ir,true);
                    auto alternate=compile_active(trial);
                    check_artifact_interface(epoch,alternate,"artifact_"+alias+"__",from_additive?1:0);
                    (void)run(alternate,trial.inactive);
                    // Preserve the compiled counterfactual bytes but not its active switch.
                    auto next=state;
                    next.source=std::move(trial.source);
                    next.artifact_versions[alias].insert(prior);
                    next.artifact_versions[alias].insert(image);
                    next.package_versions.at(alias).emplace(outer,image);
                    next.workspace_origins.at(alias).emplace(outer,ScopeOrigin{new_lock,verified.workspace_audit_sha256});
                    next.workspace_authorized[alias].insert(new_lock);
                    if(from_source)next.workspace_source_origins[alias].emplace(outer,source_digest);
                    next.events.push_back(string(from_source?"artifact_workspace_source ":"artifact_workspace_candidate ")+
                        alias+" "+prior+" "+old_lock+" "+new_lock+" "+outer+" "+image+" "+
                        verified.workspace_audit_sha256+(from_source?" "+source_digest:""));
                    retain_workspace_contract(next,alias,outer,verified.api_sha256);
                    if(from_additive){
                        next.workspace_additive_edges[alias].emplace(make_pair(prior,image),boundary);
                        next.events.push_back("workspace_additive_edge "+alias+" "+prior+" "+image+" "+outer+" "+boundary);
                    }
                    if(from_recipe){
                        next.workspace_recipe_origins[alias].emplace(outer,RecipeOrigin{second,boundary,evidence_digest});
                        next.events.push_back("workspace_recipe_origin "+alias+" "+outer+" "+second+" "+boundary+" "+evidence_digest);
                    }
                    require(encode(next).size()<=state_limit,"workspace dependency candidate storage bound");
                    const auto current=compile_active(next);
                    check_artifact_interface(epoch,current,"artifact_"+alias+"__");
                    const auto reevaluated=run(current,next.inactive);
                    const auto difference=changes(epoch,table,reevaluated);
                    require(difference.added.empty()&&difference.removed.empty(),"retaining dependency candidate changed active conclusions");
                    keep_workspace_archive(*store,outer,candidate_archive);
                    store->save(next);
                    state=std::move(next);
                    epoch=std::move(current);table=std::move(reevaluated);
                    cout<<"workspace_candidate_retained "<<alias<<" active="<<prior<<" candidate="<<image<<" lock="<<new_lock<<'\n';
                    continue;
                }
                if(line.starts_with(":preview_ir ")||line.starts_with(":replace_ir ")||
                   line.starts_with(":preview_pkg ")||line.starts_with(":replace_pkg ")||
                   line.starts_with(":preview_workspace ")||line.starts_with(":replace_workspace ")){
                    require(store.has_value(),"persistent state not enabled");
                    const bool workspace=line.starts_with(":preview_workspace ")||line.starts_with(":replace_workspace ");
                    const bool package=workspace||line.starts_with(":preview_pkg ")||line.starts_with(":replace_pkg ");
                    const bool preview=line.starts_with(":preview");
                    istringstream in(line.substr(workspace?19:package?13:12));
                    string word,prior,target,snapshot,extra;
                    require(bool(in>>word>>prior>>target>>snapshot)&&!(in>>extra),
                            "expected ARTIFACT CURRENT_SHA256 CANDIDATE_SHA256 SNAPSHOT_SHA256");
                    Parser parser{word};const auto alias=parser.name();parser.end();
                    require(alias.size()<=12&&prior.size()==64&&target.size()==64&&snapshot.size()==64&&
                         hex_chars(prior)&&hex_chars(target)&&hex_chars(snapshot),"invalid artifact or snapshot digest");
                    require(snapshot==state_hash(state),"artifact revision snapshot changed");
                    string inner=target,workspace_archive;
                    optional<cl_native::VerifiedPackage> verified;
                    if(package){
                        require(state.package_versions.contains(alias)&&state.package_contracts.contains(alias),
                            "package needs an existing verified public contract");
                        require(workspace==state.workspace_locks.contains(alias),
                                "use the existing CL package or workspace format for this alias");
                        const auto& history=state.package_versions.at(alias);
                        if(history.contains(target))inner=history.at(target);
                        else{
                            auto raw=read_transfer_file(store->dst.parent_path()/"imports",alias+(workspace?".clw":".clpkg"),
                                                              workspace?16*1024*1024:ir_size_limit);
                            require(sha256(raw)==target,"package transfer digest mismatch");
                            verified=workspace?cl_native::verify_workspace_bytes(raw,workspace_active_lock(state,alias)):
                                               cl_native::verify_package_bytes(raw);
                            require(verified->api_sha256==(workspace?workspace_contract_by_image(state,alias,prior):state.package_contracts.at(alias)),
                                    "package public contract changed");
                            if(state.scope_policies.contains(alias))
                                require(verified->scope_policy_sha256==state.scope_policies.at(alias),
                                        "replacement package does not satisfy the required CL module policy");
                            else require(verified->scope_policy_sha256.empty(),"install a new scoped alias for an authored policy");
                            inner=verified->ir_sha256;
                            if(workspace)workspace_archive=std::move(raw);
                        }
                    }else{
                        require(!state.package_versions.contains(alias),"use the full-package revision route for this alias");
                        require(!state.generated_artifacts.contains(alias),"use the native-CL revision route for this alias");
                    }
                    if(workspace)require(!workspace_growth_direction(state,alias,prior,inner),
                            "additive workspace edges require an explicit PCGM comparison");
                    if(workspace&&!verified)require(workspace_contract_by_image(state,alias,prior)==
                            workspace_contract_by_image(state,alias,inner),"workspace candidate belongs to a different API generation");
                    require(prior!=inner,"artifact candidate is already current");
                    const bool attested=verified.has_value()&&(workspace||state.scope_policies.contains(alias));
                    auto next_state=prepare_artifact_switch(state,epoch,*store,alias,prior,inner,verified?&verified->ir:nullptr,attested);
                    if(package&&verified){
                        auto& history=next_state.package_versions.at(alias);
                        require(history.size()<artifact_version_limit&&std::ranges::none_of(history,[&](const auto& x){return x.second==inner;}),
                            "excessive or ambiguous package history");
                        history.emplace(target,inner);
                        next_state.events.push_back("artifact_package_retained "+alias+" "+target+" "+inner);
                        if(attested&&workspace){
                            const auto pin=workspace_active_lock(state,alias);
                            next_state.workspace_origins[alias].emplace(target,ScopeOrigin{pin,verified->workspace_audit_sha256});
                            next_state.events.push_back("artifact_workspace "+alias+" "+target+" "+pin+" "+verified->workspace_audit_sha256);
                            retain_workspace_contract(next_state,alias,target,verified->api_sha256);
                        }else if(attested){
                            const auto& pin=state.scope_policies.at(alias);
                            next_state.scope_origins[alias].emplace(target,ScopeOrigin{pin,verified->scope_report_sha256});
                            next_state.events.push_back("artifact_scope "+alias+" "+target+" "+pin+" "+verified->scope_report_sha256);
                        }
                    }
                    auto candidate=compile_active(next_state);
                    check_artifact_interface(epoch,candidate,"artifact_"+alias+"__");
                    auto result=run(candidate,next_state.inactive);
                    Option option("artifact");score(option,epoch,table,result);
                    require(option.error.empty(),option.error);
                    if(preview){
                        cout<<(package?"package_preview ":"artifact_preview ")<<alias<<" from="<<prior<<" to="<<target
                            <<" snapshot_sha256="<<snapshot<<" changes="<<option.changes<<" risk="<<option.risk<<'\n';
                        continue;
                    }
                    add_notices(next_state,table,result);
                    if(workspace&&verified)keep_workspace_archive(*store,target,workspace_archive);
                    store->save(next_state);
                    state=std::move(next_state);epoch=std::move(candidate);table=std::move(result);
                    cout<<(package?"package_switched ":"artifact_switched ")<<alias<<" from="<<prior<<" to="<<target<<" epoch="<<state.epoch<<'\n';
                    continue;
                }
                if(line.starts_with(":watch ")){
                    require(store.has_value(),"persistent state not enabled");
                    Parser q{line.substr(7)};const auto name=q.name();const auto fact=q.atom();q.end();
                    validate_time_query(epoch,fact);
                    if(const auto old=state.watches.find(name);old!=state.watches.end()){
                        require(old->second==fact,"watch name already bound to another query");
                        cout<<"watch_unchanged "<<name<<'\n';continue;
                    }
                    auto next=state;require(next.watches.size()<32,"evidence watch limit");
                    next.watches.emplace(name,fact);
                    next.events.push_back("watch "+name+" "+show(fact));
                    store->save(next);state=std::move(next);
                    cout<<"watch_registered "<<name<<" event="<<state.events.size()<<'\n';
                    continue;
                }
                if(line.starts_with(":unwatch ")){
                    require(store.has_value(),"persistent state not enabled");
                    Parser q{line.substr(9)};const auto name=q.name();q.end();
                    auto next=state;
                    if(!next.watches.erase(name)){cout<<"watch_unchanged "<<name<<'\n';continue;}
                    next.events.push_back("unwatch "+name);
                    store->save(next);state=std::move(next);
                    cout<<"watch_removed "<<name<<'\n';continue;
                }
                if(line.starts_with(":notices ")){
                    require(store.has_value(),"persistent state not enabled");
                    istringstream in(line.substr(9));string cursor,watch,extra;
                    require(bool(in>>cursor),"notice cursor required");
                    if(in>>watch){
                        Parser q{watch};q.name();q.end();
                        require(!(in>>extra),"unexpected notice parameters");
                    }
                    const auto from=sequence_number(cursor);
                    require(from<=state.events.size(),"notice cursor beyond head");
                    cout<<notice_report(state,from,watch)<<'\n';continue;
                }
                if(line.starts_with(":json ")){
                    Parser q{line.substr(6)};const auto atom=q.atom();q.end();
                    require(!atom.pred.starts_with("!")&&std::ranges::none_of(atom.args,variable),
                            "JSON proof requires an unsigned ground goal");
                    require(epoch.arity.contains(atom.pred)&&epoch.arity.at(atom.pred)==atom.args.size(),
                            "JSON proof goal signature not found");
                    map<string,Kind> vars;check_type(epoch,atom,vars);
                    const auto context="{\"individual\":"+(state.id.empty()?string("null"):quote_json(state.id))+
                        ",\"event\":"+to_string(state.events.size())+",\"epoch\":"+to_string(state.epoch)+
                        ",\"observation_version\":"+to_string(state.observation_version)+"}";
                    cout<<json_report(table,{atom},"pcgm",context)<<'\n';
                    continue;
                }
                if(line==":reason_cost"){
                    JoinWork work;
                    const auto measured=run(epoch,state.inactive,nullptr,&work);
                    cout<<"rounds="<<work.rounds<<" probes="<<work.probes
                        <<" indexed="<<work.indexed<<" facts="<<measured.facts.size()<<'\n';
                    continue;
                }
                if(line==":pins"){
                    require(store.has_value(),"persistent state not enabled");
                    for(const auto& [label,pin]:state.pins)
                        cout<<"evidence_pin "<<label<<" event="<<pin.events<<" sha256="<<pin.digest<<'\n';
                    cout<<"pins_end count="<<state.pins.size()<<'\n';
                    continue;
                }
                if(line.starts_with(":pin ")){
                    require(store.has_value(),"persistent state not enabled");
                    Parser q{line.substr(5)};const auto label=q.name();q.end();
                    if(const auto old=state.pins.find(label);old!=state.pins.end()){
                        verify_episode(*store,state,old->second);
                        cout<<"pin_existing "<<label<<" sha256="<<old->second.digest<<'\n';
                        continue;
                    }
                    require(state.pins.size()<32,"evidence pin limit");
                    auto next=state;
                    const auto saved=encode(state), digest=sha256(saved);
                    const auto n=static_cast<unsigned>(state.events.size());
                    publish_episode(*store,digest,saved);
                    next.pins.emplace(label,Pin{digest,n});
                    next.events.push_back("pin "+label+" "+digest+" "+to_string(n));
                    store->save(next);state=std::move(next);
                    cout<<"pin_committed "<<label<<" event="<<n<<" sha256="<<digest<<'\n';
                    continue;
                }
                if(line.starts_with(":then ")||line.starts_with(":then_why ")||line.starts_with(":time_diff ")){
                    require(store.has_value(),"persistent state not enabled");
                    const bool detailed=line.starts_with(":then_why "), diff=line.starts_with(":time_diff ");
                    Parser q{line.substr(detailed?10:diff?11:6)};
                    const auto label=q.name();auto fact=q.atom();q.end();
                    require(state.pins.contains(label),"unknown evidence pin");
                    const auto& pin=state.pins.at(label);
                    const auto saved=verify_episode(*store,state,pin);
                    const auto prior=compile_active(saved);
                    if(diff)validate_time_query(epoch,fact);
                    validate_time_query(prior,fact);
                    const auto before=run(prior,saved.inactive);
                    cout<<"historical "<<label<<" event="<<pin.events<<" "<<show(fact)
                        <<" "<<truth_state(before,fact)<<'\n';
                    if(detailed)explain(before,fact);
                    if(diff)cout<<"current event="<<state.events.size()<<" "<<show(fact)<<" "
                                <<truth_state(table,fact)<<'\n';
                    continue;
                }
                if(line.starts_with(":chat ")){
                    require(store.has_value(),"persistent state not enabled");
                    const auto turn=interpret_turn(line.substr(6),epoch);
                    if(auto ses=state.dialogues.find(turn.sid);ses!=state.dialogues.end()){
                        if(auto old=ses->second.turns.find(turn.tid);old!=ses->second.turns.end()){
                            require(old->second.request==turn.canonical,"turn already committed with different request");
                            cout<<"chat_replayed "<<turn.sid<<" "<<turn.tid<<'\n'<<old->second.reply;
                            continue;
                        }
                    }
                    auto next=state;
                    require(next.dialogues.size()<native_dialogue_session_limit||next.dialogues.contains(turn.sid),"dialogue session limit");
                    auto& session=next.dialogues[turn.sid];
                    require(session.turns.size()<native_dialogue_turn_limit,"dialogue turn limit");
                    const auto reply=turn.action=="outcome"&&session.focus?
                        reasoned_outcome(*store,state,sha256(encode(state)),turn.sid,*session.focus,turn.basis_pin,epoch,table)+"\n":
                        make_reply(turn,session,epoch,table,state.observation_version);
                    require(reply.size()<=16384,"outcome exceeds dialogue receipt limit; use the reasoned_outcome read operation");
                    session.turns.emplace(turn.tid,LocalTurn{turn.canonical,reply});
                    session.order.push_back(turn.tid);
                    next.events.push_back("dialogue "+turn.sid+" "+turn.tid+" "+to_hex(turn.canonical)+" "+
                        (session.focus?to_hex(show(*session.focus)):"-")+" "+to_hex(reply));
                    store->save(next);state=std::move(next);
                    cout<<"chat_committed "<<turn.sid<<" "<<turn.tid<<'\n'<<reply;
                    continue;
                }
                if(line.starts_with(":transcript ")){
                    require(store.has_value(),"persistent state not enabled");
                    Parser q{line.substr(12)};const auto sid=q.name();q.end();
                    require(state.dialogues.contains(sid),"no such conversation");
                    const auto& session=state.dialogues.at(sid);
                    for(const auto& tid:session.order){
                        const auto& note=session.turns.at(tid);
                        cout<<"turn "<<tid<<" request="<<note.request<<'\n'<<note.reply;
                    }
                    cout<<"transcript_end turns="<<session.order.size()<<'\n';
                    continue;
                }
                if(line.starts_with(":handoff ")){
                    require(store && !state.owner.empty(),"managed state required");
                    istringstream in(line.substr(9));string target,digest,snapshot,extra;
                    require(bool(in>>target>>digest>>snapshot)&&!(in>>extra),"expected BUILD BINARY_SHA256 SNAPSHOT_SHA256");
                    Parser bn{target};bn.name();bn.end();
                    require(digest.size()==64&&hex_chars(digest)&&digest!=state.owner_hash,
                            "handoff requires a different target executable");
                    require(snapshot==state_hash(state),"prepared snapshot is stale");
                    require_ticket(*store,target,digest,snapshot);
                    auto candidate=state;
                    const auto nonce=new_id();
                    candidate.pending=NativeHandoff{state.owner,state.owner_hash,target,digest,snapshot,nonce};
                    candidate.events.push_back("handoff "+state.owner+" "+state.owner_hash+" "+
                                               target+" "+digest+" "+snapshot+" "+nonce);
                    store->save(candidate);
                    cout<<"handoff_prepared to="<<target<<" nonce="<<nonce
                        <<" event="<<candidate.events.size()<<" snapshot_sha256="<<state_hash(candidate)<<'\n';
                    return 0;
                }
                if(line.starts_with(":auto_pause ")||line.starts_with(":auto_resume ")){
                    require(store.has_value(),"persistent state not enabled");
                    const bool pausing=line.starts_with(":auto_pause ");
                    Parser q{line.substr(pausing?12:13)};const auto channel=q.name();q.end();
                    require(epoch.auto_policy.contains(channel)||epoch.version_policy.contains(channel)||epoch.workspace_recipes.contains(channel),"no automatic policy for this source");
                    auto next=state;
                    const auto changed=pausing?next.autopause.insert(channel).second:next.autopause.erase(channel)!=0;
                    if(changed){
                        next.events.push_back((pausing?"autopause ":"autoresume ")+channel);
                        store->save(next);state=std::move(next);
                    }
                    cout<<(changed?"automatic_mode ":"automatic_mode_unchanged ")
                        <<channel<<" "<<(pausing?"paused":"enabled")<<'\n';
                    continue;
                }
                if(line==":automatic"){
                    require(store.has_value(),"persistent state not enabled");
                    for(const auto& [key,item]:state.automatic)
                        cout<<"auto "<<key.first<<" "<<key.second<<" "<<item.status
                            <<(item.reason.empty()?"":" reason="+item.reason)<<'\n';
                    cout<<"auto_end count="<<state.automatic.size()<<'\n';
                    continue;
                }
                if(line==":cycles"){
                    require(store.has_value(),"persistent state not enabled");
                    for(const auto& [key,receipt]:state.cycles)
                        cout<<"cycle "<<key.first<<" "<<key.second<<" observations="<<receipt.observations
                            <<" questions="<<receipt.questions<<" sha256="<<receipt.digest<<'\n';
                    cout<<"cycles_end count="<<state.cycles.size()<<'\n';
                    continue;
                }
                if(line.starts_with(":cycle ")){
                    require(store.has_value(),"persistent state not enabled");
                    Parser arg{line.substr(7)};const auto file=arg.name();arg.end();
                    const auto raw=read_packet(store->dst.parent_path(),file);
                    if(addressed)require(sha256(raw)==addressed->digest,"sensor feed packet SHA-256 mismatch");
                    const auto packet=decode_packet(raw);
                    require(epoch.sensor_policy.contains(packet.source),"sensor source is not authorized");
                    const auto digest=sha256(raw);
                    const CycleKey key{packet.source,packet.sequence};
                    if(auto saved=state.cycles.find(key);saved!=state.cycles.end()){
                        require(saved->second.digest==digest,"sensor sequence already committed with different bytes");
                        if(addressed){
                            const auto previous=state.automatic.find(key);
                            Automatic outcome;
                            if(previous!=state.automatic.end()){outcome.status=previous->second.status;outcome.reason=previous->second.reason;}
                            const auto exact=state.sensor_responses.find(key);
                            cout<<sensor_feed_json(*addressed,state,packet.source,packet.sequence,saved->second,true,
                                exact==state.sensor_responses.end()?string{}:exact->second.workspace,outcome)<<'\n';
                        }else cout<<"cycle_unchanged "<<packet.source<<" "<<packet.sequence<<'\n';
                        continue;
                    }
                    const auto last=state.last_cycle.contains(packet.source)?state.last_cycle.at(packet.source):0;
                    require(packet.sequence==last+1,"sensor sequence out of order");
                    if(epoch.pinned_feedback_sources.contains(packet.source))
                        require_pinned_outcome_packet(state,epoch,packet);
                    if(epoch.measurement_sources.contains(packet.source))
                        require_measurement_packet(state,epoch,packet);
                    const auto& allowed=epoch.sensor_policy.at(packet.source);
                    auto candidate=state;
                    const auto mark=candidate.events.size();
                    candidate.events.push_back("");
                    unsigned index=0;
                    for(const auto& fact:packet.facts){
                        require(allowed.contains(fact.pred),"sensor predicate not authorized: "+fact.pred);
                        const auto id=cycle_obs_id(packet.source,packet.sequence,++index);
                        require(!epoch.observations.contains(id),"sensor observation reserved ID already used");
                        candidate.source+="\n& "+id+" "+show(fact)+".\n";
                        if(!packet.origins.at(index-1).empty())
                            candidate.source+="# pcgm_sensor_ref "+id+" "+packet.origins.at(index-1)+"\n";
                        candidate.events.push_back("observe "+id);
                        candidate.recorded_observations.insert(id);
                        ++candidate.observation_version;
                    }
                    auto next_epoch=compile_active(candidate);
                    auto next_table=run(next_epoch,candidate.inactive);
                    Automatic activation;
                    const auto explicit_workspace=next_epoch.workspace_recipes.find(packet.source);
                    const bool workspace_chooses=explicit_workspace!=next_epoch.workspace_recipes.end()&&explicit_workspace->second.front().choose;
                    if(candidate.autopause.contains(packet.source))activation.status="paused";
                    else if(!workspace_chooses)activation=vet_auto(next_epoch,next_table,packet.source,candidate);
                    optional<Option> rollback, rewrite_choice, artifact_choice;
                    string alternatives,decision_receipt;
                    if(candidate.autopause.contains(packet.source)){
                        // Paused sources can still contribute observations, but cannot change rules.
                    }else if(!workspace_chooses&&next_epoch.adaptation.contains(packet.source)){
                        auto options=compare_choices(candidate,next_epoch,next_table,&packet.source,&activation);
                        if(const auto policy=next_epoch.version_policy.find(packet.source);policy!=next_epoch.version_policy.end()){
                            try{append_artifact_choices(options,candidate,next_epoch,next_table,*store,&policy->second);}
                            catch(const runtime_error& error){options.clear();alternatives="version decision unavailable: "+string(error.what());}
                        }
                        if(!options.empty()){
                            if(const auto linked=next_epoch.native_synthesis.find(packet.source);linked!=next_epoch.native_synthesis.end()){
                                try{
                                    auto made=fresh_synthesis_choice(linked->second,candidate,next_epoch,next_table,*store,packet.facts);
                                    if(made){
                                        require(options.size()<15,"native synthesis candidate budget");
                                        options.push_back(std::move(*made));
                                    }
                                }catch(const runtime_error& error){
                                    alternatives+=(alternatives.empty()?"":"; ")+string("native synthesis blocked: ")+string(error.what()).substr(0,280);
                                }
                            }
                        }
                        const auto chosen=best_choice(options);
                        if(chosen&&options.at(*chosen).name!="stay")
                            decision_receipt=render_decision(candidate,options,chosen,true,
                                "observation:"+packet.source+":"+to_string(packet.sequence));
                        for(const auto& option:options){
                            alternatives+=(alternatives.empty()?"":"; ")+option.name+
                                "(wishes="+to_string(option.wishes)+",risk="+to_string(option.risk)+
                                ",changes="+to_string(option.changes)+")"+
                                (option.error.empty()?"":" blocked");
                        }
                        if(!chosen||options.at(*chosen).name=="stay"){
                            activation=Automatic{};
                            activation.status=chosen?"stay":"undecided";
                        }else if(options.at(*chosen).name=="rollback"){
                            rollback=std::move(options.at(*chosen));
                            activation=Automatic{};
                            activation.status="rolled_back";
                            activation.reason=rollback->revision;
                        }else if(options.at(*chosen).name=="artifact"){
                            artifact_choice=std::move(options.at(*chosen));
                            activation=Automatic{};
                            activation.status="version_switched";
                            activation.reason=artifact_choice->revision;
                        }else rewrite_choice=std::move(options.at(*chosen));
                        if(!alternatives.empty())
                            activation.reason+=(activation.reason.empty()?"":"; ")+alternatives;
                    }
                    const auto raised=stage_questions(candidate,open_gaps(
                        artifact_choice?*artifact_choice->program:rollback?*rollback->program:activation.next_epoch?*activation.next_epoch:next_epoch,
                        artifact_choice?*artifact_choice->table:rollback?*rollback->table:activation.next_table?*activation.next_table:next_table));
                    candidate.events[mark]="cycle "+packet.source+" "+to_string(packet.sequence)+" "+digest+
                              " "+to_string(index)+" "+to_string(raised);
                    candidate.cycles.emplace(key,CycleReceipt{digest,index,static_cast<unsigned>(raised)});
                    candidate.last_cycle[packet.source]=packet.sequence;
                    if(!activation.status.empty()){
                        string outcome=activation.status;
                        if(rollback){
                            const auto snapshot=revision_snapshot(candidate);
                            const auto old_size=mark+1+index;
                            auto& chosen=*rollback->state;
                            candidate.events.insert(candidate.events.end(),
                                chosen.events.begin()+static_cast<ptrdiff_t>(old_size),chosen.events.end());
                            candidate.events.push_back("decision rollback "+rollback->revision+" "+snapshot+" "+
                                to_string(rollback->wishes)+" "+to_string(rollback->risk)+" "+to_string(rollback->changes));
                            const auto receipt_id="e"+to_string(candidate.events.size());
                            record_experience_context(candidate,next_epoch,next_table);
                            retain_decision(candidate,receipt_id,decision_receipt);
                            candidate.source=std::move(chosen.source);
                            candidate.active_revisions=std::move(chosen.active_revisions);
                            candidate.plans=std::move(chosen.plans);
                            candidate.autopause=std::move(chosen.autopause);
                            candidate.epoch=chosen.epoch;
                            next_epoch=std::move(*rollback->program);next_table=std::move(*rollback->table);
                        }else if(artifact_choice){
                            const auto prior_digest=revision_snapshot(candidate);
                            const auto old_size=mark+1+index;
                            auto& chosen=*artifact_choice->state;
                            candidate.events.insert(candidate.events.end(),chosen.events.begin()+static_cast<ptrdiff_t>(old_size),chosen.events.end());
                            candidate.events.push_back("decision artifact "+artifact_choice->revision+" "+prior_digest+" "+
                                    to_string(artifact_choice->wishes)+" "+to_string(artifact_choice->risk)+" "+to_string(artifact_choice->changes));
                            const auto receipt_id="e"+to_string(candidate.events.size());
                            record_experience_context(candidate,next_epoch,next_table);
                            retain_decision(candidate,receipt_id,decision_receipt);
                            candidate.source=std::move(chosen.source);
                            candidate.artifacts=std::move(chosen.artifacts);
                            candidate.artifact_versions=std::move(chosen.artifact_versions);
                            candidate.generated_artifacts=std::move(chosen.generated_artifacts);
                            candidate.synthesized_artifacts=std::move(chosen.synthesized_artifacts);
                            candidate.epoch=chosen.epoch;
                            next_epoch=std::move(*artifact_choice->program);next_table=std::move(*artifact_choice->table);
                        }else if(activation.next_epoch){
                            require(candidate.plans.size()<128,"revision plan limit");
                            const auto base=revision_snapshot(candidate);
                            const auto id="p"+to_string(candidate.events.size()+1);
                            RevisionPlan plan{base,activation.patch,candidate.source.size(),true,false};
                            candidate.events.push_back("proposal "+base+" "+to_hex(activation.patch));
                            candidate.events.push_back("apply "+id+" "+to_string(plan.offset));
                            if(rewrite_choice){
                                candidate.events.push_back("decision rewrite "+id+" "+base+" "+
                                    to_string(rewrite_choice->wishes)+" "+to_string(rewrite_choice->risk)+" "+
                                    to_string(rewrite_choice->changes));
                                const auto receipt_id="e"+to_string(candidate.events.size());
                            record_experience_context(candidate,next_epoch,next_table);
                            retain_decision(candidate,receipt_id,decision_receipt);
                            }
                            candidate.plans.emplace(id,plan);
                            candidate.active_revisions.push_back(id);
                            candidate.source+="\n"+activation.patch;
                            ++candidate.epoch;
                            next_epoch=std::move(*activation.next_epoch);
                            next_table=std::move(*activation.next_table);
                            outcome=id;
                        }
                        candidate.events.push_back("automatic "+packet.source+" "+to_string(packet.sequence)+" "+
                                                   outcome+" "+to_hex(activation.reason.empty()?"-":activation.reason));
                        candidate.automatic.emplace(key,AutoReceipt{outcome,activation.reason});
                        activation.status=outcome;
                    }
                    string workspace_result;
                    if(const auto recipe=next_epoch.workspace_recipes.find(packet.source);recipe!=next_epoch.workspace_recipes.end()){
                        if(candidate.autopause.contains(packet.source))workspace_result="workspace_recipe_paused";
                        else try{
                            workspace_result=route_workspace_cycle(recipe->second,candidate,next_epoch,next_table,*store,packet.source,packet.facts);
                        }catch(const runtime_error& e){
                            workspace_result="workspace_recipe_blocked reason="+string(e.what()).substr(0,240);
                        }
                    }
                    if(workspace_chooses&&!candidate.autopause.contains(packet.source)){
                        const auto policy=next_epoch.workspace_recipes.at(packet.source).front();
                        if(workspace_result.starts_with("workspace_recipe_blocked")){
                            activation.status="blocked";
                            activation.reason=workspace_result;
                        }else{
                            const auto decision=choose_workspace_cycle_variant(policy,candidate,next_epoch,next_table,*store,packet.source,packet.sequence);
                            activation.status=decision.first;
                            activation.reason=decision.second;
                        }
                        candidate.events.push_back("automatic "+packet.source+" "+to_string(packet.sequence)+" "+
                            activation.status+" "+to_hex(activation.reason.empty()?"-":activation.reason));
                        candidate.automatic.emplace(key,AutoReceipt{activation.status,activation.reason});
                    }
                    if(next_epoch.feedback_sources.contains(packet.source))
                        bind_observed_feedback(candidate,next_epoch,next_table,packet.source,packet.sequence,packet.facts);
                    if(next_epoch.measurement_sources.contains(packet.source))
                        bind_measured_feedback(candidate,next_epoch,next_table,packet,*store);
                    if(addressed){
                        candidate.events.push_back("cycle_response "+packet.source+" "+to_string(packet.sequence)+" "+digest+
                            " "+(workspace_result.empty()?"-":to_hex(workspace_result)));
                        const auto pos=static_cast<unsigned>(candidate.events.size());
                        candidate.sensor_responses.emplace(key,SensorResponse{workspace_result,pos});
                    }
                    add_notices(candidate,table,next_table);
                    store->save(candidate);
                    state=std::move(candidate);epoch=std::move(next_epoch);table=std::move(next_table);
                    if(addressed){
                        cout<<sensor_feed_json(*addressed,state,packet.source,packet.sequence,state.cycles.at(key),false,
                                               workspace_result,activation)<<'\n';
                        continue;
                    }
                    cout<<"cycle_committed "<<packet.source<<" "<<packet.sequence<<" observations="<<index
                        <<" questions="<<raised<<" sha256="<<digest<<'\n';
                    if(!workspace_result.empty())cout<<workspace_result<<'\n';
                    if(!activation.status.empty())
                        cout<<"auto_revision "<<activation.status
                            <<(activation.reason.empty()?"":" reason="+activation.reason)<<'\n';
                    continue;
                }
                if(line.starts_with(":admit_workspace ")){
                    require(store.has_value(),"persistent state not enabled");
                    istringstream in(line.substr(17));string ticket,request,member,archive,lock,proof,extra;
                    require(bool(in>>ticket>>request>>member>>archive>>lock>>proof)&&!(in>>extra),
                            "expected ticket, request, local archive member, archive, lock and proof pins");
                    for(const auto& digest:{request,archive,lock,proof})
                        require(digest.size()==64&&hex_chars(digest),"workspace evidence needs exact SHA-256 pins");
                    Parser name{member};require(name.name()==member&&member.size()<=48,"invalid workspace evidence inbox name");name.end();
                    const auto q=state.questions.find(ticket);
                    require(q!=state.questions.end(),"unknown question");
                    const auto id="bundle_"+sha256("PCGM-WORKSPACE-ANSWER-1\n"+state.id+"\n"+ticket+"\n"+request+
                                                   "\n"+archive+"\n"+lock+"\n"+proof+"\n").substr(0,24);
                    if(state.workspace_answer_locks.contains(id)){
                        const auto& match=state.bundle_receipts.at(id);
                        require(state.workspace_answer_locks.at(id)==lock&&match.ticket==ticket&&match.request==request&&
                                match.package==archive&&match.proof==proof,"workspace evidence receipt identity differs");
                        cout<<"workspace_evidence_unchanged "<<ticket<<" "<<id<<" sha256="<<proof<<'\n';continue;
                    }
                    require(!epoch.observations.contains(id),"workspace evidence observation ID already exists");
                    const auto status=question_status(q->second,table,open_gaps(epoch,table),state,&epoch);
                    require(status=="open"&&question_pin(state,ticket,q->second,status,&epoch,&table)==request,
                            "workspace proof question has a stale request address");
                    const auto raw=native_os::read_confined_component(store->dst.parent_path()/"incoming",member+".clw",16*1024*1024,{
                        "cannot open workspace evidence inbox","cannot open local workspace evidence","workspace evidence is not regular",
                        "cannot read local workspace evidence","workspace evidence exceeds size limit"});
                    const auto result=cl_native::workspace_single_goal_bounded(raw,archive,lock,show(q->second.fact)+"\n",
                                                                            {128,12000,2000000,2000000});
                    require(result.receipt.size()<=512*1024&&sha256(result.receipt)==proof,
                            "workspace answer does not match reviewed proof");
                    require(result.sign==cl_native::EvidenceSign::Positive||result.sign==cl_native::EvidenceSign::Negative,
                            "PCGM cannot admit unknown or conflicted workspace evidence");
                    const auto fact=result.sign==cl_native::EvidenceSign::Positive?q->second.fact:opposite_of(q->second.fact);
                    auto staged=state;
                    staged.source+="\n& "+id+" "+show(fact)+".\n";
                    auto next_epoch=compile_active(staged);auto next_table=run(next_epoch,staged.inactive);
                    staged.events.push_back("answer "+ticket+" "+id);
                    staged.events.push_back("answer_bundle "+ticket+" "+id+" "+request+" "+archive+" "+proof);
                    staged.events.push_back("answer_workspace "+id+" "+lock);
                    staged.recorded_observations.insert(id);
                    staged.receipt_question.emplace(id,ticket);
                    staged.bundle_receipts.emplace(id,BundleReceipt{ticket,request,archive,proof});
                    staged.workspace_answer_locks.emplace(id,lock);
                    ++staged.observation_version;
                    add_notices(staged,table,next_table);
                    store->save(staged);state=std::move(staged);epoch=std::move(next_epoch);table=std::move(next_table);
                    cout<<"workspace_evidence_committed "<<ticket<<" "<<id<<" sha256="<<proof<<'\n';continue;
                }
                if(line.starts_with(":admit_frozen ")){
                    require(store.has_value(),"persistent state not enabled");
                    istringstream in(line.substr(14));string ticket,request,member,artifact,package,snapshot,proof,extra;
                    require(bool(in>>ticket>>request>>member>>artifact>>package>>snapshot>>proof)&&!(in>>extra),
                            "expected ticket, request, member, artifact, package, snapshot and proof pins");
                    const auto receipt=admit_frozen_exact(*store,state,epoch,table,ticket,request,member,artifact,package,snapshot,proof);
                    cout<<(receipt.committed?"frozen_evidence_committed ":"frozen_evidence_unchanged ")
                        <<ticket<<" "<<receipt.id<<" sha256="<<proof<<'\n';
                    continue;
                }
                if(line.starts_with(":admit_cl ")||line.starts_with(":admit_cl_decide ")){
                    const bool decide=line.starts_with(":admit_cl_decide ");
                    require(store.has_value(),"persistent state not enabled");
                    istringstream args(line.substr(decide?17:10));string ticket,request,member,pin,proof,extra;
                    require(bool(args>>ticket>>request>>member>>pin>>proof)&&!(args>>extra),
                            "expected question, request pin, local CL bundle name, package pin and proof pin");
                    const auto hash=[](const string& h){return h.size()==64&&hex_chars(h);};
                    require(hash(request)&&hash(pin)&&hash(proof),"three exact SHA-256 pins are required");
                    Parser leaf_name{member};require(leaf_name.name()==member&&member.size()<=48,"invalid CL evidence member");leaf_name.end();
                    const auto q=state.questions.find(ticket);
                    require(q!=state.questions.end(),"unknown question");
                    const auto id="bundle_"+sha256("PCGM-ADMIT-CL-1\n"+state.id+"\n"+ticket+"\n"+request+
                                                  "\n"+pin+"\n"+proof+"\n").substr(0,24);
                    if(const auto previous=state.bundle_receipts.find(id);previous!=state.bundle_receipts.end()){
                        const auto& saved=previous->second;
                        require(saved.ticket==ticket&&saved.request==request&&saved.package==pin&&saved.proof==proof,
                                "previous CL evidence receipt differs");
                        require(!decide||state.bundle_assessments.contains(id),
                                "evidence already admitted without a decision; review current state separately");
                        cout<<"cl_evidence_unchanged "<<ticket<<" "<<id<<" sha256="<<proof<<'\n';
                        continue;
                    }
                    require(!epoch.observations.contains(id),"CL evidence observation ID already exists");
                    const auto status=question_status(q->second,table,open_gaps(epoch,table),state,&epoch);
                    require(status=="open"&&question_pin(state,ticket,q->second,status,&epoch,&table)==request,
                            "question is no longer open at supplied request pin");
                    const auto bytes=native_os::read_confined_component(store->dst.parent_path()/"incoming",member+".clpkg",2*1024*1024,{
                        "cannot open local CL evidence inbox","cannot open local CL evidence package","CL evidence package is not a regular file",
                        "cannot read CL evidence package","CL evidence package size limit"});
                    const auto candidate=cl_native::offline_single_goal_bounded(bytes,pin,show(q->second.fact)+"\n",{128,12000,2000000,2000000});
                    require(candidate.receipt.size()<=512*1024&&sha256(candidate.receipt)==proof,
                            "CL evidence does not match reviewed proof SHA-256");
                    require(candidate.sign==cl_native::EvidenceSign::Positive||candidate.sign==cl_native::EvidenceSign::Negative,
                            "PCGM cannot admit conflicted or unknown CL evidence");
                    const auto observed=candidate.sign==cl_native::EvidenceSign::Positive?q->second.fact:opposite_of(q->second.fact);
                    auto next=state;
                    next.source+="\n& "+id+" "+show(observed)+".\n";
                    auto compiled=compile_active(next);auto checked=run(compiled,next.inactive);
                    next.events.push_back("answer "+ticket+" "+id);
                    next.events.push_back("answer_bundle "+ticket+" "+id+" "+request+" "+pin+" "+proof);
                    next.recorded_observations.insert(id);
                    next.receipt_question.emplace(id,ticket);
                    next.bundle_receipts.emplace(id,BundleReceipt{ticket,request,pin,proof});
                    ++next.observation_version;
                    if(decide){
                        require(std::ranges::any_of(compiled.preferences,[](const auto& opt){return opt.hard;})&&
                                std::ranges::any_of(compiled.preferences,[](const auto& opt){return !opt.hard;}),
                                "evidence adoption decision requires an explicit hard rule and wish");
                        auto options=compare_choices(next,compiled,checked);
                        append_artifact_choices(options,next,compiled,checked,*store);
                        const auto choice=best_choice(options);
                        const bool changes_rules=choice&&options.at(*choice).name!="stay";
                        const auto receipt=render_decision(next,options,choice,changes_rules,"cl_evidence:"+id);
                        if(changes_rules){
                            auto& selected=options.at(*choice);
                            auto adopted=std::move(*selected.state);
                            adopted.events.push_back("decision "+selected.name+" "+selected.revision+" "+
                                revision_snapshot(next)+" "+to_string(selected.wishes)+" "+
                                to_string(selected.risk)+" "+to_string(selected.changes));
                            const auto decision_id="e"+to_string(adopted.events.size());
                            record_experience_context(adopted,compiled,checked);
                            retain_decision(adopted,decision_id,receipt);
                            next=std::move(adopted);
                            compiled=std::move(*selected.program);checked=std::move(*selected.table);
                        }
                        next.events.push_back("answer_assessment "+id+" "+to_hex(receipt));
                        next.bundle_assessments.emplace(id,receipt);
                    }
                    add_notices(next,table,checked);
                    store->save(next);state=std::move(next);epoch=std::move(compiled);table=std::move(checked);
                    cout<<"cl_evidence_committed "<<ticket<<" "<<id<<" sha256="<<proof<<'\n';
                    continue;
                }
                if(line.starts_with(":answer_packet ")){
                    require(store.has_value(),"persistent state not enabled");
                    Parser arg{line.substr(15)};const auto file=arg.name();arg.end();
                    const auto raw=native_os::read_confined_component(store->dst.parent_path()/"incoming",file+".answer",2048,{
                        "cannot open answer inbox","cannot open local answer file","local answer must be a regular file",
                        "cannot read local answer packet","local answer packet size limit"});
                    const auto packet=decode_answer_packet(raw);
                    require(packet.individual==state.id,"answer packet belongs to a different individual");
                    const auto q=state.questions.find(packet.ticket);
                    require(q!=state.questions.end(),"unknown question");
                    require(matches_question(q->second,packet.evidence),"answer packet evidence does not match question");
                    const auto exact=sha256(raw);
                    const auto id="wire_"+sha256("PCGM-ANSWER-ID-1\n"+state.id+"\n"+packet.ticket+"\n"+
                                                packet.source+"\n"+show(packet.evidence)).substr(0,24);
                    if(const auto old=state.wire_receipts.find(id);old!=state.wire_receipts.end()){
                        require(old->second.packet==exact&&old->second.ticket==packet.ticket,"answer packet replay differs");
                        cout<<"answer_packet_unchanged "<<packet.ticket<<" "<<id<<" sha256="<<exact<<'\n';
                        continue;
                    }
                    require(!epoch.observations.contains(id),"answer observation ID already exists");
                    const auto current=question_status(q->second,table,open_gaps(epoch,table),state,&epoch);
                    const bool counter=(current=="answered" && packet.evidence==opposite_of(q->second.fact)) ||
                                       (current=="opposed" && packet.evidence==q->second.fact);
                    const bool independent=std::ranges::none_of(state.wire_receipts,[&](const auto& item){
                        return item.second.ticket==packet.ticket && item.second.source==packet.source;
                    });
                    require((current=="open" || (counter&&independent)) &&
                            question_pin(state,packet.ticket,q->second,current,&epoch,&table)==packet.pin,
                            "question is no longer open at the supplied request pin");
                    auto next=state;
                    next.source+="\n& "+id+" "+show(packet.evidence)+".\n";
                    auto compiled=compile_active(next);auto checked=run(compiled,next.inactive);
                    next.events.push_back("answer "+packet.ticket+" "+id);
                    next.events.push_back("answer_wire "+packet.ticket+" "+id+" "+packet.source+" "+packet.pin+" "+exact);
                    next.recorded_observations.insert(id);
                    next.receipt_question.emplace(id,packet.ticket);
                    next.wire_receipts.emplace(id,WireReceipt{packet.ticket,packet.source,packet.pin,exact});
                    ++next.observation_version;
                    add_notices(next,table,checked);
                    store->save(next);state=std::move(next);epoch=std::move(compiled);table=std::move(checked);
                    cout<<"answer_packet_committed "<<packet.ticket<<" "<<id<<" sha256="<<exact<<'\n';
                    continue;
                }
                if(line.starts_with(":observation_batch ")||line.starts_with(":observation_batch_audited ")){
                    require(store.has_value(),"persistent state not enabled");
                    const auto batch=parse_observation_batch(line);
                    const auto digest=sha256(line);
                    const bool repeated=state.observation_batches.contains(batch.id);
                    if(!repeated){
                        auto staged=stage_observation_batch(state,epoch,batch,line);
                        add_notices(staged.state,table,staged.proofs);
                        if(batch.audited)publish_episode(*store,batch.basis,encode(state));
                        store->save(staged.state);
                        state=std::move(staged.state);epoch=std::move(staged.program);table=std::move(staged.proofs);
                    }
                    cout<<observation_batch_receipt(state,batch.id,digest,repeated)<<'\n';
                    continue;
                }
                if(line.starts_with(":observe ")||line.starts_with(":answer ")){
                    require(store.has_value(),"persistent state not enabled");
                    const bool answering=line.starts_with(":answer ");
                    Parser q{line.substr(answering?8:9)};
                    const auto ticket=answering?q.name():string{};
                    if(answering)require(state.questions.contains(ticket),"unknown question");
                    const auto id=q.name();
                    require(!id.starts_with("geom_sensor_")&&!id.starts_with("sensor_")&&!id.starts_with("wire_")&&!id.starts_with("bundle_"),"runtime sensor ID is reserved");
                    const auto fact=q.atom(); q.end();
                    require(epoch.arity.contains(base_name(fact)),"observation predicate not declared");
                    require(std::ranges::none_of(fact.args,variable),"observation must be ground");
                    if(answering)require(matches_question(state.questions.at(ticket),fact),
                                          "answer does not match the question");
                    const auto old=epoch.observations.find(id);
                    if(old!=epoch.observations.end()){
                        require(old->second==fact,"observation ID has different content");
                        if(answering)
                            require(state.receipt_question.contains(id) && state.receipt_question.at(id)==ticket,
                                    "observation ID already belongs to another source or question");
                        cout<<"observation_unchanged "<<id<<'\n';
                        continue;
                    }
                    if(answering){
                        const auto status=question_status(state.questions.at(ticket),table,open_gaps(epoch,table),state,&epoch);
                        require(status=="open"||status=="opposed"||status=="conflicted",
                                "question no longer awaiting evidence");
                    }
                    auto next_state=state;
                    next_state.source+="\n& "+id+" "+show(fact)+".\n";
                    auto next=compile_active(next_state);
                    auto checked=run(next,next_state.inactive);
                    if(answering){
                        next_state.events.push_back("answer "+ticket+" "+id);
                        next_state.receipt_question.emplace(id,ticket);
                    }else next_state.events.push_back("observe "+id);
                    next_state.recorded_observations.insert(id);
                    ++next_state.observation_version;
                    add_notices(next_state,table,checked);
                    store->save(next_state);
                    state=std::move(next_state);
                    epoch=std::move(next);
                    table=std::move(checked);
                    cout<<"observation_version="<<state.observation_version<<" observed "<<id<<'\n';
                    if(answering)cout<<"answer "<<ticket<<" "<<question_status(state.questions.at(ticket),table,open_gaps(epoch,table),state,&epoch)<<'\n';
                    continue;
                }
                if(line.starts_with(":withdraw ") || line.starts_with(":restore ")){
                    const bool withdraw=line.starts_with(":withdraw ");
                    Parser q{line.substr(withdraw?10:9)};
                    const auto id=q.name(); q.end();
                    require(epoch.observations.contains(id),"unknown observation ID");
                    auto next=state;
                    const bool changed=withdraw ? next.inactive.insert(id).second
                                                : next.inactive.erase(id)!=0;
                    if(!changed){cout<<"observation_unchanged "<<id<<'\n'; continue;}
                    require(state.observation_version<10000,"observation revision limit");
                    auto candidate=run(epoch,next.inactive);
                    ++next.observation_version;
                    if(store){
                        next.events.push_back((withdraw?"withdraw ":"restore ")+id);
                        add_notices(next,table,candidate);
                        store->save(next);
                    }
                    state=std::move(next);
                    table=std::move(candidate);
                    cout<<"observation_version="<<state.observation_version<<" "
                        <<(withdraw?"withdrawn ":"restored ")<<id<<'\n';
                    continue;
                }
                if(line==":field_start"){
                    require(store && state.modules.contains("geometry"),"install the geometry module first");
                    require(!geometry,"geometry already initialized");
                    auto next=state; next.has_field=true;
                    next.events.push_back(GeometricRuntime::init_event);
                    GeometricRuntime candidate;
                    store->save(next);
                    state=std::move(next); geometry=std::move(candidate);
                    cout<<geometry->status()<<'\n';
                    continue;
                }
                if(line==":field_status"){
                    require(geometry.has_value(),"geometry is not initialized");
                    cout<<geometry->status()<<'\n';
                    continue;
                }
                if(line==":primordial"){
                    require(geometry.has_value(),"geometry is not initialized");
                    cout<<"primordial_set={";
                    bool first=true;
                    for(const auto& symbol:instinct::primordial_directions){
                        if(!first)cout<<',';
                        first=false;
                        cout<<symbol;
                    }
                    cout<<"} kind=unordered direction_only\n";
                    continue;
                }
                if(line.starts_with(":field_tick ")){
                    require(store && geometry,"geometry is not initialized");
                    Parser q{line.substr(12)};const auto ctx=q.name();q.end();
                    auto copy=*geometry;
                    const auto [action,reason]=copy.select(epoch,state.inactive,GeometricRuntime::index(GeometricRuntime::contexts,ctx));
                    copy.apply(action);
                    auto next=state;
                    next.events.push_back("field_tick "+ctx+" "+GeometricRuntime::actions[action]);
                    store->save(next);
                    state=std::move(next); geometry=std::move(copy);
                    cout<<reason<<'\n'<<geometry->status()<<'\n';
                    continue;
                }
                if(line==":needs"){ missing_inputs(epoch,table,&cout); continue; }
                if(line==":ask"||line==":questions"){
                    require(store.has_value(),"persistent state not enabled");
                    const auto gaps=open_gaps(epoch,table);
                    if(line==":ask"){
                        auto next=state;
                        const auto created=stage_questions(next,gaps);
                        if(created){store->save(next);state=std::move(next);}
                        cout<<"questions_created "<<created<<'\n';
                    }
                    for(const auto& [id,q]:state.questions){
                        cout<<"question "<<id<<" "<<question_status(q,table,gaps,state,&epoch)<<" "
                            <<show(q.goal)<<" needs "<<show(q.fact)<<'\n';
                    }
                    cout<<"questions_end count="<<state.questions.size()<<'\n';
                    continue;
                }
                if(line.starts_with(":compact_state ")||line.starts_with(":materialize_state ")){
                    require(store.has_value(),"persistent state not enabled");
                    const bool compact=line.starts_with(":compact_state ");
                    const auto stamp=line.substr(line.find(' ')+1);
                    require(stamp.size()==64&&hex_chars(stamp)&&stamp==state_hash(state),"state representation snapshot changed");
                    if(store->compacted==compact){cout<<"state_representation_unchanged\n";continue;}
                    if(compact)for(const auto& segment:state.archives)verify_archive(*store,state,segment);
                    store->save(state,false,compact);
                    cout<<"state_representation "<<(compact?"compact":"materialized")<<" logical_sha256="<<stamp
                        <<" physical_sha256="<<store->physical_sha256<<'\n';
                    continue;
                }
                if(line.starts_with(":seal_history ")){
                    require(store.has_value(),"persistent state not enabled");
                    const string stamp=line.substr(14);
                    require(stamp.size()==64&&hex_chars(stamp)&&stamp==state_hash(state),"history snapshot changed");
                    const auto from=state.archives.empty()?1U:state.archives.back().last+1;
                    if(from>state.events.size()||std::none_of(state.events.begin()+static_cast<ptrdiff_t>(from-1),state.events.end(),
                        [](const string& e){return !e.starts_with("archive_seal ");})){cout<<"archive_unchanged\n";continue;}
                    require(state.archives.size()<archive_count_limit,"archive segment limit");
                    const auto end=static_cast<unsigned>(min<size_t>(state.events.size(),from+127));
                    const auto previous=state.archives.empty()?string(64,'0'):state.archives.back().digest;
                    if(!state.archives.empty())verify_archive(*store,state,state.archives.back());
                    ArchiveSegment segment{from,end,previous,{},stamp};
                    segment.digest=sha256(archive_payload(state,segment));
                    publish_archive(*store,state,segment);
                    auto next=state;next.archives.push_back(segment);
                    next.events.push_back("archive_seal "+to_string(from)+" "+to_string(end)+" "+previous+" "+segment.digest+" "+stamp);
                    store->save(next);state=std::move(next);
                    cout<<"archive_sealed start="<<from<<" end="<<end<<" sha256="<<segment.digest<<'\n';continue;
                }
                if(line==":history"){
                    require(store.has_value(),"persistent state not enabled");
                    for(size_t i=0;i<state.events.size();++i){
                        const auto& event=state.events[i];
                        if(event.starts_with("decision_trace ")){
                            const auto space=event.find(' ',15);
                            const auto id=event.substr(15,space-15);
                            cout<<"event="<<i+1<<" decision_trace "<<id<<" sha256="<<sha256(stored_decision(state,id))<<'\n';
                        }else cout<<"event="<<i+1<<" "<<event<<'\n';
                    }
                    cout<<"history_end event="<<state.events.size()<<'\n';
                    continue;
                }
                if(line.starts_with(":install ")){
                    require(store.has_value(),"persistent state not enabled");
                    Parser q{line.substr(9)};
                    const auto name=q.name(); q.end();
                    require(!state.modules.contains(name),"module already installed");
                    const auto module=read_src(store->dst.parent_path()/"modules"/(name+".cl"));
                    const bool desktop_migration=name=="desktop_criteria" && sha256(module)=="9af03bcebdd9c37a00cf7bf4d3fab57ee903e94dc389ff56c456b2235e1e5b1e";
                    auto next_state=state;
                    next_state.source+="\n# module "+name+"\n"+module;
                    auto next=compile_active(next_state); auto next_table=run(next,next_state.inactive);
                    require(next.sensor_policy==epoch.sensor_policy,"module cannot change sensor policy");
                    require(next.linked_origins==epoch.linked_origins&&next.observation_labels==epoch.observation_labels,
                            "module cannot rewrite bound observation origins");
                    for(size_t i=epoch.rules.size();i<next.rules.size();++i)
                        require(!base_name(next.rules[i].head).starts_with("artifact_"),"module cannot redefine artifact rules");
                    require(desktop_migration||(next.synth_policy==epoch.synth_policy&&next.multi_policy==epoch.multi_policy),"module cannot change synthesis policy");
                    require(next.auto_policy==epoch.auto_policy,"module cannot change automatic policy");
                    require(next.criteria_questions==epoch.criteria_questions&&
                            (desktop_migration||next.preferences==epoch.preferences)&&next.adaptation==epoch.adaptation&&
                            next.experience_contexts==epoch.experience_contexts&&next.version_policy==epoch.version_policy&&
                            next.feedback_sources==epoch.feedback_sources&&next.pinned_feedback_sources==epoch.pinned_feedback_sources&&
                            next.measurement_sources==epoch.measurement_sources&&
                            next.native_synthesis==epoch.native_synthesis&&next.workspace_recipes==epoch.workspace_recipes,
                            "module cannot change decision objectives or adaptive channel");
                    for(const auto& [id,_]:next.observations)
                        require(!id.starts_with("sensor_")||epoch.observations.contains(id),"module cannot inject sensor receipt IDs");
                    require(next.rules.size()>epoch.rules.size() ||
                            next.observations.size()>epoch.observations.size() ||
                            next.schemas.size()>epoch.schemas.size() ||
                            next.signatures.size()>epoch.signatures.size() ||
                            next.goals.size()>epoch.goals.size(),"module contains no CL definitions");
                    next_state.modules.insert(name);
                    next_state.events.push_back("install "+name);
                    ++next_state.epoch;
                    add_notices(next_state,table,next_table);
                    store->save(next_state);
                    state=std::move(next_state);
                    epoch=std::move(next); table=std::move(next_table);
                    cout<<"epoch="<<state.epoch<<" facts="<<table.facts.size()
                        <<" module_installed "<<name<<'\n';
                    continue;
                }
                if(line.starts_with(":rebind_queued_choice ")){
                    require(store.has_value()&&!state.owner.empty()&&!state.pending&&state.staged_copy.empty(),
                            "managed persistent PCGM owner required");
                    istringstream input(line.substr(22));string id,old,head,extra;
                    require(bool(input>>id>>old>>head)&&!(input>>extra)&&capsule_id(id)&&capsule_pin(old)&&capsule_pin(head),
                            "expected intent ID, initial basis and current managed head pins");
                    const auto made=state.choice_intents.find(id);
                    require(made!=state.choice_intents.end()&&made->second.digest==old&&
                            !state.cancelled_intents.contains(id)&&!state.choice_outcomes.contains(id),
                            "pending choice and initial basis do not match");
                    const auto exact=encode(state);
                    require(sha256(exact)==head,"choice ownership rebind head changed");
                    require(!state.choice_rebound_intents.contains(id)&&!choice_job&&state.pins.size()+2<=32&&
                            choice_owner_only_tail(state.events,made->second.events+1),
                            "choice ownership rebind requires only completed native handoffs");
                    const auto prior=verify_episode(*store,state,made->second);
                    require(prior.source==state.source&&prior.inactive==state.inactive&&prior.epoch==state.epoch&&
                            prior.observation_version==state.observation_version,
                            "choice ownership rebind content differs from original basis");
                    auto next=state;
                    const auto basis=Pin{head,static_cast<unsigned>(state.events.size())};
                    publish_episode(*store,basis.digest,exact);
                    next.events.push_back("choice_intent_rebound "+id+" "+old+" "+basis.digest+" "+to_string(basis.events));
                    next.choice_rebound_intents.emplace(id,basis);
                    next.pins.emplace("rebound_"+id,basis);
                    store->save(next);state=std::move(next);
                    cout<<"choice_intent_rebound "<<id<<" basis_sha256="<<basis.digest<<'\n';
                    continue;
                }
                if(line.starts_with(":queue_choice ")||line.starts_with(":run_queued_choice ")||
                   line.starts_with(":cancel_queued_choice ")){
                    require(store.has_value()&&!state.pending&&state.staged_copy.empty(),"active persistent PCGM writer required");
                    Parser ask{line.substr(1)};
                    const auto verb=ask.name(),id=ask.name();ask.end();
                    require(capsule_id(id),"invalid durable choice intent address");
                    const auto saved=state.choice_intents.find(id);
                    const auto done=state.choice_outcomes.find(id);
                    if(verb=="queue_choice"){
                        if(saved!=state.choice_intents.end()){
                            cout<<"choice_intent_unchanged "<<id<<" status="<<
                                (done!=state.choice_outcomes.end()?"completed":state.cancelled_intents.contains(id)?"cancelled":"pending")<<'\n';
                            continue;
                        }
                        require(!choice_job&&!state.choice_outcomes.contains(id)&&state.choice_intents.size()<12&&
                                state.pins.size()+2<=32&&std::ranges::none_of(state.choice_intents,[&](const auto& x){
                                    return !state.cancelled_intents.contains(x.first)&&!state.choice_outcomes.contains(x.first);
                                }),"choice intent capacity or another choice is active");
                        require(std::ranges::any_of(epoch.preferences,[](const auto& p){return p.hard;})&&
                                std::ranges::any_of(epoch.preferences,[](const auto& p){return !p.hard;}),
                                "decision requires an explicit hard rule and wish");
                        auto next=state;
                        const auto exact=encode(state);
                        const Pin basis{sha256(exact),static_cast<unsigned>(state.events.size())};
                        publish_episode(*store,basis.digest,exact);
                        next.events.push_back("choice_intent "+id+" "+basis.digest+" "+to_string(basis.events));
                        next.choice_intents.emplace(id,basis);
                        next.pins.emplace("intent_"+id,basis);
                        store->save(next);state=std::move(next);
                        cout<<"choice_intent_queued "<<id<<" basis_sha256="<<basis.digest<<'\n';
                        continue;
                    }
                    require(saved!=state.choice_intents.end(),"unknown durable choice intent");
                    if(verb=="cancel_queued_choice"){
                        require(done==state.choice_outcomes.end(),"completed choice intent cannot be cancelled");
                        if(state.cancelled_intents.contains(id)){cout<<"choice_intent_cancelled "<<id<<'\n';continue;}
                        auto next=state;
                        next.events.push_back("cancel_choice_intent "+id);
                        next.cancelled_intents.insert(id);
                        store->save(next);state=std::move(next);
                        cout<<"choice_intent_cancelled "<<id<<'\n';continue;
                    }
                    if(done!=state.choice_outcomes.end()){
                        cout<<done->second.receipt<<'\n';continue;
                    }
                    require(!state.cancelled_intents.contains(id),"choice intent has been cancelled");
                    require(!choice_job&&state.pins.size()<32&&state.choice_outcomes.size()<128,"choice intent outcome capacity or another job active");
                    const auto& old=saved->second;
                    const auto rebinding=state.choice_rebound_intents.find(id);
                    const auto* rebound=rebinding==state.choice_rebound_intents.end()?nullptr:&rebinding->second;
                    require(coherent_choice_basis(state,id,old,rebound),
                            "choice intent is stale; cancel and queue with a new ID");
                    const auto earlier=verify_episode(*store,state,old);
                    if(rebound){
                        const auto now=verify_episode(*store,state,*rebound);
                        require(earlier.source==now.source&&now.source==state.source&&now.inactive==state.inactive&&
                                earlier.inactive==now.inactive&&now.epoch==state.epoch&&now.observation_version==state.observation_version,
                                "rebound choice content differs from a retained basis");
                    }
                    const auto exact=encode(state);
                    const Pin comparison{sha256(exact),static_cast<unsigned>(state.events.size())};
                    auto evaluated=run_frozen_choice(state,epoch,table,*store);
                    const auto selected=evaluated.selected;
                    const bool execute=selected&&evaluated.options.at(*selected).name!="stay";
                    const auto receipt=render_decision(state,evaluated.options,selected,execute,"live_job:"+id);
                    auto next=execute?*evaluated.options.at(*selected).state:state;
                    if(execute){
                        auto& winner=evaluated.options.at(*selected);
                        next.events.push_back("decision "+winner.name+" "+winner.revision+" "+
                            revision_snapshot(state)+" "+to_string(winner.wishes)+" "+to_string(winner.risk)+" "+
                            to_string(winner.changes));
                        const auto event="e"+to_string(next.events.size());
                        record_experience_context(next,epoch,table);
                        retain_decision(next,event,receipt);
                        add_notices(next,table,*winner.table);
                    }
                    const string kind=execute?"committed":"unchanged";
                    next.events.push_back("choice_outcome "+id+" "+comparison.digest+" "+kind+" "+to_hex(receipt));
                    next.choice_outcomes.emplace(id,ChoiceOutcome{comparison.digest,kind,receipt});
                    publish_episode(*store,comparison.digest,exact);
                    next.choice_bases.insert(id);
                    next.pins.emplace("basis_"+id,comparison);
                    next.events.push_back("choice_basis "+id+" "+comparison.digest+" "+to_string(comparison.events));
                    store->save(next);state=std::move(next);
                    if(execute){
                        auto& winner=evaluated.options.at(*selected);
                        epoch=std::move(*winner.program);table=std::move(*winner.table);
                    }
                    cout<<receipt<<'\n';continue;
                }
                if(line==":choice_job_start"){
                    require(store.has_value()&&!state.pending&&state.staged_copy.empty(),"active persistent PCGM writer required");
                    require(std::ranges::none_of(state.choice_intents,[&](const auto& x){
                        return !state.cancelled_intents.contains(x.first)&&!state.choice_outcomes.contains(x.first);
                    }),"a durable choice intent is already active");
                    if(choice_job){
                        require(choice_job->cancelled&&choice_job->collect_if_finished(),
                                "an existing choice job must be committed or cancelled and finished");
                        choice_job.reset();
                    }
                    require(std::ranges::any_of(epoch.preferences,[](const auto& opt){return opt.hard;})&&
                            std::ranges::any_of(epoch.preferences,[](const auto& opt){return !opt.hard;}),
                            "decision requires an explicit hard rule and wish");
                    choice_job.emplace();
                    auto& job=*choice_job;
                    job.id="d"+new_id();job.revision=state_hash(state);job.basis=state;
                    try{
                        job.pending=async(launch::async,[basis=job.basis,prog=epoch,evidence=table,owner=&*store]{
                            return run_frozen_choice(basis,prog,evidence,*owner);
                        });
                    }catch(...){choice_job.reset();throw;}
                    cout<<choice_job_json(job,state,false)<<'\n';
                    continue;
                }
                if(line.starts_with(":choice_job_")){
                    Parser request{line.substr(1)};
                    const auto operation=request.name(), id=request.name();request.end();
                    const bool explained=operation=="choice_job_commit_explained";
                    const bool durable=operation=="choice_job_commit_recorded"||explained;
                    if(durable){
                        if(const auto committed=state.choice_outcomes.find(id);committed!=state.choice_outcomes.end()){
                            require(!explained||state.choice_bases.contains(id),
                                    "choice already recorded without an archived basis");
                            cout<<committed->second.receipt<<'\n';
                            continue;
                        }
                        require(state.choice_outcomes.size()<128,"durable PCGM choice receipt limit");
                    }
                    require(choice_job&&choice_job->id==id,"unknown active PCGM choice job");
                    auto& job=*choice_job;
                    if(operation=="choice_job_status"||operation=="choice_job_collect"||operation=="choice_job_cancel"){
                        if(operation=="choice_job_cancel")job.cancelled=true;
                        cout<<choice_job_json(job,state,operation=="choice_job_collect")<<'\n';
                        continue;
                    }
                    require(operation=="choice_job_commit"||durable,"invalid PCGM choice job command");
                    require(!job.cancelled,"PCGM choice job was cancelled");
                    require(state_hash(state)==job.revision,"PCGM choice job is stale; start a new evaluation");
                    require(job.collect_if_finished(),"PCGM choice job is still evaluating");
                    require(job.failure.empty(),job.failure);
                    auto& product=*job.product;
                    const auto selected=product.selected;
                    const bool execute=selected&&product.options.at(*selected).name!="stay";
                    const auto receipt=render_decision(state,product.options,selected,execute,"live_job:"+job.id);
                    if(execute||durable){
                        auto next=execute?*product.options.at(*selected).state:state;
                        if(execute){
                            auto& winner=product.options.at(*selected);
                            next.events.push_back("decision "+winner.name+" "+winner.revision+" "+
                                revision_snapshot(state)+" "+to_string(winner.wishes)+" "+to_string(winner.risk)+" "+
                                to_string(winner.changes));
                            const auto e="e"+to_string(next.events.size());
                            record_experience_context(next,epoch,table);
                            retain_decision(next,e,receipt);
                            add_notices(next,table,*winner.table);
                        }
                        if(durable){
                            const string kind=execute?"committed":"unchanged";
                            next.events.push_back("choice_outcome "+id+" "+job.revision+" "+kind+" "+to_hex(receipt));
                            next.choice_outcomes.emplace(id,ChoiceOutcome{job.revision,kind,receipt});
                        }
                        if(explained){
                            require(next.pins.size()<32&&!next.pins.contains("basis_"+id),"choice basis pin capacity exhausted");
                            const auto exact=encode(job.basis);
                            require(sha256(exact)==job.revision&&job.basis.id==state.id,"frozen choice basis changed");
                            const auto events=static_cast<unsigned>(job.basis.events.size());
                            publish_episode(*store,job.revision,exact);
                            next.choice_bases.insert(id);
                            next.pins.emplace("basis_"+id,Pin{job.revision,events});
                            next.events.push_back("choice_basis "+id+" "+job.revision+" "+to_string(events));
                        }
                        store->save(next);
                        state=std::move(next);
                        if(execute){
                            auto& winner=product.options.at(*selected);
                            epoch=std::move(*winner.program);table=std::move(*winner.table);
                        }
                    }
                    cout<<receipt<<'\n';
                    choice_job.reset();continue;
                }
                if(line.starts_with(":decision_receipt ")){
                    require(store.has_value(),"persistent state not enabled");
                    Parser q{line.substr(18)};const auto id=q.name();q.end();
                    cout<<stored_decision(state,id)<<'\n';continue;
                }
                if(line==":compare"||line==":decide"||line==":compare_versions"||line==":decide_versions"||
                   line==":compare_json"||line==":decide_json"||line==":compare_versions_json"||line==":decide_versions_json"||
                   line==":compare_parallel_json"||line==":decide_parallel_json"||
                   line==":compare_versions_parallel_json"||line==":decide_versions_parallel_json"){
                    require(store.has_value(),"persistent state not enabled");
                    require(std::ranges::any_of(epoch.preferences,[](const auto& o){return o.hard;})&&
                            std::ranges::any_of(epoch.preferences,[](const auto& o){return !o.hard;}),
                            "decision requires at least one explicit hard rule and one wish");
                    const bool parallel=line.find("_parallel")!=string::npos;
                    const size_t workers=parallel?4:1;
                    DecisionWork stats;
                    auto candidates=compare_choices(state,epoch,table,nullptr,nullptr,workers,&stats);
                    if(line.find("_versions")!=string::npos)
                        append_artifact_choices(candidates,state,epoch,table,*store,nullptr,workers,&stats);
                    const auto selected=best_choice(candidates);
                    const bool execute=line.starts_with(":decide")&&selected.has_value()&&candidates.at(*selected).name!="stay";
                    const bool structured=line.ends_with("_json");
                    const string receipt=(structured||execute)?render_decision(state,candidates,selected,execute,"local"):"";
                    if(execute){
                        auto& best=candidates.at(*selected);
                        auto& next=*best.state;
                        next.events.push_back("decision "+best.name+" "+best.revision+" "+
                                              revision_snapshot(state)+" "+to_string(best.wishes)+" "+
                                              to_string(best.risk)+" "+to_string(best.changes));
                        const auto id="e"+to_string(next.events.size());
                        record_experience_context(next,epoch,table);
                        retain_decision(next,id,receipt);
                        add_notices(next,table,*best.table);
                        store->save(next);
                        state=std::move(next);epoch=std::move(*best.program);table=std::move(*best.table);
                    }
                    if(parallel){
                        cout<<"{\"schema\":\"pcgm-parallel-decision-v1\",\"backend\":\"cpu\",\"jobs\":"<<stats.jobs
                            <<",\"workers\":"<<stats.lanes<<",\"peak_active\":"<<stats.peak<<",\"decision\":"<<receipt<<"}\n";
                        continue;
                    }
                    if(structured){cout<<receipt<<'\n';continue;}
                    for(const auto& option:candidates)print_choice(option);
                    if(!selected)cout<<"decision none; maintain current state\n";
                    else cout<<"decision "<<candidates.at(*selected).name
                             <<(candidates.at(*selected).name=="artifact"?" "+candidates.at(*selected).revision:"")
                             <<(execute?" committed":line.starts_with(":compare")?" preview":" unchanged")<<'\n';
                    continue;
                }
                if(line==":repair_compare"||line==":repair_step"){
                    require(store&&state.owner==build_name&&!state.pending&&state.staged_copy.empty(),
                            "bounded repair requires the active managed writer");
                    cout<<bounded_repair(*store,state,epoch,table,line==":repair_step")<<'\n';
                    continue;
                }
                if(line==":plans"){
                    require(store.has_value(),"persistent state not enabled");
                    const auto base=revision_snapshot(state);
                    for(const auto& [id,plan]:state.plans)
                        cout<<"plan "<<id<<" "<<(plan.reverted?"reverted":plan.applied?"applied":
                            plan.snapshot==base?"ready":"stale")<<" snapshot="<<plan.snapshot<<'\n';
                    cout<<"plans_end count="<<state.plans.size()<<'\n';
                    continue;
                }
                if(line==":plan"){
                    require(store.has_value(),"persistent state not enabled");
                    const auto patch=combined_patch(epoch,table);
                    if(patch.empty()){cout<<"no_eligible_revision\n";continue;}
                    require(patch.size()<=16384,"revision patch size limit");
                    const auto base=revision_snapshot(state);
                    auto view=state;
                    view.source+="\n"+patch;
                    const auto candidate=compile_active(view);
                    const auto impact=changes(epoch,table,run(candidate,state.inactive));
                    string id;
                    for(const auto& [old,plan]:state.plans)
                        if(!plan.applied&&plan.snapshot==base&&plan.patch==patch){id=old;break;}
                    if(id.empty()){
                        auto next=state;
                        require(next.plans.size()<128,"revision plan limit");
                        id="p"+to_string(next.events.size()+1);
                        next.events.push_back("proposal "+base+" "+to_hex(patch));
                        next.plans.emplace(id,RevisionPlan{base,patch});
                        store->save(next);state=std::move(next);
                        cout<<"plan_ready "<<id<<'\n';
                    }else cout<<"plan_unchanged "<<id<<'\n';
                    cout<<patch;
                    show_changes(impact);
                    continue;
                }
                if(line.starts_with(":apply ")||line.starts_with(":rollback ")){
                    require(store.has_value(),"persistent state not enabled");
                    const bool applying=line.starts_with(":apply ");
                    Parser arg{line.substr(applying?7:10)};const auto id=arg.name();arg.end();
                    require(state.plans.contains(id),"unknown revision plan");
                    auto next_state=state;
                    auto& plan=next_state.plans.at(id);
                    if(applying){
                        require(!plan.reverted,"this proposal was reverted; create a new one");
                        if(plan.applied){cout<<"revision_unchanged "<<id<<'\n';continue;}
                        require(plan.snapshot==revision_snapshot(state),"stale proposal; replan against current evidence");
                        require(plan.patch==combined_patch(epoch,table),"proposal no longer matches evidence");
                        plan.offset=next_state.source.size();
                        next_state.source+="\n"+plan.patch;
                        plan.applied=true;
                        next_state.active_revisions.push_back(id);
                        next_state.events.push_back("apply "+id+" "+to_string(plan.offset));
                    }else{
                        if(plan.reverted){cout<<"revision_unchanged "<<id<<'\n';continue;}
                        require(!next_state.active_revisions.empty()&&next_state.active_revisions.back()==id,
                                "only the latest active revision can be rolled back");
                        expect_patch(next_state,plan);
                        next_state.source.erase(plan.offset,plan.patch.size()+1);
                        plan.reverted=true;
                        next_state.active_revisions.pop_back();
                        next_state.events.push_back("revert "+id);
                        for(const auto& [key,receipt]:next_state.automatic)
                            if(receipt.status==id&&next_state.autopause.insert(key.first).second)
                                next_state.events.push_back("autopause "+key.first);
                    }
                    ++next_state.epoch;
                    auto next=compile_active(next_state);
                    auto next_table=run(next,next_state.inactive);
                    const auto impact=changes(epoch,table,next_table,applying);
                    add_notices(next_state,table,next_table);
                    store->save(next_state);
                    state=std::move(next_state);epoch=std::move(next);table=std::move(next_table);
                    cout<<(applying?"revision_applied ":"revision_reverted ")<<id<<" epoch="<<state.epoch<<'\n';
                    show_changes(impact);
                    continue;
                }
                if(line==":step"){
                    require(!store,"persistent revision requires :plan then :apply");
                    require(argc==4 && !revised,"revision destination not available");
                    auto delta=propose(epoch,table);
                    if(delta.empty()){ cout<<"no_eligible_revision\n"; continue; }
                    auto next_state=state;
                    next_state.source+="\n"+delta;
                    ++next_state.epoch;
                    auto next=compile_active(next_state); auto next_table=run(next,next_state.inactive);
                    if(store){
                        next_state.events.push_back("revision");
                        store->save(next_state);
                    } else publish(fs::path(argv[3]),next_state.source);
                    state=std::move(next_state);
                    epoch=std::move(next); table=std::move(next_table);
                    revised=true;
                    cout<<"epoch="<<state.epoch<<" facts="<<table.facts.size()<<" source_committed\n";
                    continue;
                }
                if(line.starts_with(":proof_integrity ")){
                    Parser q{line.substr(17)}; auto a=q.atom();q.end();
                    IntegrityView clean(epoch,state.inactive,table);
                    proof_integrity(table,clean,a);continue;
                }
                const bool explain_mode=line.starts_with(":explain ");
                Parser q{explain_mode?line.substr(9):line}; auto a=q.atom(); q.end();
                require(!comparison(base_name(a)),"comparison can only occur in a rule body");
                auto it=epoch.arity.find(a.pred);
                require(it==epoch.arity.end() || it->second==a.args.size(),"query arity mismatch");
                map<string,Kind> vars; check_type(epoch,a,vars);
                if(explain_mode) explain(table,std::move(a));
                else query(table,std::move(a));
            } catch (const CommitIndeterminate&) { throw; }
            catch (const exception& e) {
                if(sensor_feed)cout<<"{\"schema\":\"pcgm-sensor-receipt-v1\",\"id\":"
                    <<(correlation.empty()?"null":quote_json(correlation))<<",\"ok\":false,\"error\":"
                    <<quote_json(e.what())<<"}\n";
                else cout<<"QUERY_ERROR "<<e.what()<<'\n';
            }
        }
        return 0;
    } catch (const exception& e) { cerr<<e.what()<<'\n'; return 1; }
}
