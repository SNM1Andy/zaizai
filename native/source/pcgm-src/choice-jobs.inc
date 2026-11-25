struct ChoiceJobResult {
    vector<Option> options;
    optional<size_t> selected;
    DecisionWork stats;
};
struct LiveChoiceJob {
    string id,revision;
    bool cancelled=false;
    string failure;
    Continuity basis;
    future<ChoiceJobResult> pending; // destroyed before immutable basis and before the owning StateStore
    optional<ChoiceJobResult> product;
    bool collect_if_finished(){
        if(product||!failure.empty())return true;
        if(pending.wait_for(chrono::seconds(0))!=future_status::ready)return false;
        try{product=pending.get();}catch(const exception& e){failure=string(e.what()).substr(0,240);if(failure.empty())failure="PCGM background decision failed";}
        catch(...){failure="unexpected PCGM background decision error";}
        return true;
    }
};
ChoiceJobResult run_frozen_choice(const Continuity& state,const Program& program,const Table& table,const StateStore& store){
    ChoiceJobResult completed;
    completed.options=compare_choices(state,program,table,nullptr,nullptr,4,&completed.stats);
    append_artifact_choices(completed.options,state,program,table,store,nullptr,4,&completed.stats);
    completed.selected=best_choice(completed.options);
    return completed;
}
string choice_job_json(LiveChoiceJob& job,const Continuity& live,bool wants_decision){
    const bool ready=job.collect_if_finished();
    string phase=ready?(job.failure.empty()?"ready":"failed"):"running";
    if(job.cancelled)phase=ready?"cancelled":"draining";
    const auto now=sha256(encode(live));
    string out="{\"schema\":\"pcgm-live-choice-job-v1\",\"id\":"+quote_json(job.id)+
          ",\"phase\":"+quote_json(phase)+",\"basis_sha256\":"+quote_json(job.revision)+
          ",\"head_sha256\":"+quote_json(now)+",\"stale\":"+(now==job.revision?"false":"true");
    if(!job.failure.empty())out+=",\"error\":"+quote_json(job.failure);
    if(job.product){
        const auto& product=*job.product;
        out+=",\"jobs\":"+to_string(product.stats.jobs)+",\"peak_active\":"+to_string(product.stats.peak);
        if(wants_decision&&!job.cancelled)out+=",\"decision\":"+render_decision(
            job.basis,product.options,product.selected,false,"live_job:"+job.id);
    }
    return out+"}";
}
