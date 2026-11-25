string revision_snapshot(const Continuity& c){
    // Plan transactions are conservative. Any evidence revision or CL version invalidates an uncommitted plan.
    return sha256(to_string(c.epoch)+"\n"+to_string(c.observation_version)+"\n"+c.source);
}
struct ChangeSet{
    vector<Atom> added,removed;
    vector<string> goals;
};
string truth_state(const Table& table,const Atom& goal){
    const bool plus=table.facts.contains(goal),minus=table.facts.contains(opposite_of(goal));
    return plus?(minus?"CONFLICT":"POSITIVE"):(minus?"NEGATIVE":"UNKNOWN");
}
ChangeSet changes(const Program& p,const Table& before,const Table& after,bool bounded=true){
    ChangeSet c;
    for(const auto& [a,_]:after.facts)if(!before.facts.contains(a))c.added.push_back(a);
    for(const auto& [a,_]:before.facts)if(!after.facts.contains(a))c.removed.push_back(a);
    for(const auto& g:p.goals){
        const auto old=truth_state(before,g), now=truth_state(after,g);
        if(old!=now)c.goals.push_back(show(g)+" "+old+" -> "+now);
    }
    require(!bounded||c.added.size()+c.removed.size()<=256,"revision too broad for a complete local review");
    return c;
}
void show_changes(const ChangeSet& c){
    cout<<"revision_delta added="<<c.added.size()<<" removed="<<c.removed.size()
        <<" changed_goals="<<c.goals.size()<<'\n';
    size_t printed=0;
    for(const auto& a:c.added){if(printed==256)break;cout<<"  add "<<show(a)<<'\n';++printed;}
    for(const auto& a:c.removed){if(printed==256)break;cout<<"  remove "<<show(a)<<'\n';++printed;}
    if(printed<c.added.size()+c.removed.size())cout<<"  fact_diff_truncated after="<<printed<<'\n';
    for(const auto& g:c.goals)cout<<"  goal "<<g<<'\n';
}
void expect_patch(const Continuity& state,const RevisionPlan& p){
    require(state.source.compare(p.offset,p.patch.size()+1,"\n"+p.patch)==0,"active revision patch mismatch");
}
