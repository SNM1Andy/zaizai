// Read-only. Disputes are assessed in the ordinary signed closure, never in the
// filtered view; otherwise removing one proof can make its opposite appear clean.
Atom opposite(Atom a) {
    if(a.pred.starts_with('!')) a.pred.erase(0,1);
    else a.pred.insert(0,1,'!');
    return a;
}
struct IntegrityView {
    set<Atom> disputed;
    Table clean;
    IntegrityView(const Program& p,const set<string>& inactive,const Table& raw) {
        for(const auto& [a,_]:raw.facts)
            if(raw.facts.contains(opposite(a))) disputed.insert(a);
        clean=disputed.empty()?raw:run(p,inactive,nullptr,nullptr,&disputed);
    }
};
void proof_integrity(const Table& raw,const IntegrityView& view,const Atom& goal) {
    require(!goal.pred.starts_with('!'),"audit the unsigned predicate");
    for(const auto& x:goal.args) require(!variable(x),"audit must be ground");
    const auto negative=opposite(goal);
    auto report=[&](const Atom& a){
        return !raw.facts.contains(a)?"NO_SUPPORT":
               view.disputed.contains(a)?"DIRECT_DISPUTE":
               view.clean.facts.contains(a)?"CLEAN_WITNESS":"DISPUTED_ANCESTRY";
    };
    const auto p=report(goal),n=report(negative);
    cout<<"proof_integrity "<<show(goal)<<" positive="<<p<<" negative="<<n<<'\n';
    // Only the witness drawn from the filtered closure can certify the clean route.
    if(view.clean.facts.contains(goal)||view.clean.facts.contains(negative))
        explain(view.clean,goal);
}
