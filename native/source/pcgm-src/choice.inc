#include <tuple>
#include "decision-workers.inc"
struct EvaluatedCriterion {
    Atom target;
    optional<Atom> condition;
    bool hard, active;
    string wanted,before,after;
};
struct Option {
    string name,revision,error;
    size_t wishes=0,risk=0,changes=0;
    int remembered=0;
    vector<string> evidence;
    vector<EvaluatedCriterion> criteria;
    optional<Continuity> state;
    optional<Program> program;
    optional<Table> table;
    explicit Option(string n):name(std::move(n)){}
};

void score(Option& o,const Program& baseline,const Table& current,const Table& proposed){
    for(const auto& p:baseline.preferences){
        if(p.when&&!proof_without_conflict(current,*p.when)){
            o.criteria.push_back({p.proposition,p.when,p.hard,false,p.expected,
                                truth_state(current,p.proposition),truth_state(proposed,p.proposition)});
            o.evidence.push_back("inactive "+show(p.proposition)+" condition="+show(*p.when));
            continue;
        }
        const auto old=truth_state(current,p.proposition);
        const auto next=truth_state(proposed,p.proposition);
        o.criteria.push_back({p.proposition,p.when,p.hard,true,p.expected,old,next});
        o.evidence.push_back(show(p.proposition)+" "+old+" -> "+next+
                              (p.hard?" hard":" wish")+" expected="+p.expected);
        if(p.hard&&p.expected!=next)o.error="hard objective not met";
        if(!p.hard&&p.expected==next)++o.wishes;
        if(next=="CONFLICT"&&old!="CONFLICT"&&p.expected!="CONFLICT")++o.risk;
    }
    const auto effect=changes(baseline,current,proposed);
    o.changes=effect.added.size()+effect.removed.size();
}
vector<Option> compare_choices(const Continuity& original,const Program& current,const Table& table,
                               const string* source=nullptr,const Automatic* guarded=nullptr,
                               size_t workers=1,DecisionWork* measurements=nullptr){
    vector<Option> options;
    for(auto name:{"stay","rollback","rewrite"})options.emplace_back(name);
    score(options[0],current,table,table);
    evaluate_options(options.size()-1,workers,measurements,[&](size_t slot){
        auto& o=options[slot+1];
        try{
            auto next=original;
            if(o.name=="rollback"){
                require(!next.active_revisions.empty(),"no tracked revision to roll back");
                o.revision=next.active_revisions.back();
                if(source)require(std::ranges::any_of(next.automatic,[&](const auto& row){
                    return row.first.first==*source&&row.second.status==o.revision;
                }),"automatic rollback cannot touch another source's revision");
                auto& r=next.plans.at(o.revision);
                expect_patch(next,r);
                next.source.erase(r.offset,r.patch.size()+1);
                r.reverted=true;
                next.active_revisions.pop_back();
                next.events.push_back("revert "+o.revision);
                for(const auto& [key,receipt]:next.automatic)
                    if(receipt.status==o.revision&&next.autopause.insert(key.first).second)
                        next.events.push_back("autopause "+key.first);
            }else{
                if(source){
                    require(guarded&&guarded->next_table.has_value(),
                            guarded&&!guarded->reason.empty()?guarded->reason:"no eligible automatic rewrite");
                    score(o,current,table,*guarded->next_table);
                    return;
                }
                const auto patch=combined_patch(current,table,false);
                require(!patch.empty()&&patch.size()<=16384,"no bounded rewrite candidate");
                require(next.plans.size()<128,"revision plan limit");
                o.revision="p"+to_string(next.events.size()+1);
                const auto base=revision_snapshot(next);
                const auto pos=next.source.size();
                next.events.push_back("proposal "+base+" "+to_hex(patch));
                next.events.push_back("apply "+o.revision+" "+to_string(pos));
                next.plans.emplace(o.revision,RevisionPlan{base,patch,pos,true,false});
                next.active_revisions.push_back(o.revision);
                next.source+="\n"+patch;
            }
            ++next.epoch;
            auto prog=compile_active(next);
            auto expected=run(prog,next.inactive);
            score(o,current,table,expected);
            o.state=std::move(next);
            o.program=std::move(prog);
            o.table=std::move(expected);
        }catch(const runtime_error& e){o.error=e.what();}
    });
    if(!current.experience_contexts.empty()){
        const auto context=experience_context(current,table);
        const auto prior=read_experiences(original);
        for(auto& o:options)o.remembered=memory_value(original,current,table,o.name,context,prior);
    }
    return options;
}
optional<size_t> best_choice(const vector<Option>& options){
    optional<size_t> best;
    bool tie=false;
    auto value=[](const Option& e){
        return tuple{e.wishes,-static_cast<int>(e.risk),-static_cast<int>(e.changes),e.remembered};
    };
    for(size_t i=0;i<options.size();++i){
        if(!options[i].error.empty())continue;
        if(!best||value(options[i])>value(options.at(*best))){best=i;tie=false;}
        else if(value(options[i])==value(options.at(*best)))tie=true;
    }
    if(tie)return {};
    return best;
}
void print_choice(const Option& o){
    cout<<"option "<<o.name<<" wishes="<<o.wishes<<" risk="<<o.risk<<" changes="<<o.changes
        <<" "<<(o.error.empty()?"eligible":"blocked");
    if(!o.error.empty())cout<<" reason="<<o.error;
    if(o.remembered)cout<<" memory="<<o.remembered;
    cout<<'\n';
    for(const auto& ev:o.evidence)cout<<"  "<<ev<<'\n';
}
