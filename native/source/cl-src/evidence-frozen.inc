constexpr size_t frozen_proof_limit=2*1024*1024;
constexpr size_t frozen_evidence_limit=5*1024*1024;
struct FrozenEvidence {
    string package,goals,journal,proof;
};
string encode_frozen_evidence(const FrozenEvidence& exact){
    IRWriter w;
    package_cell(w,exact.package,package_limit);package_cell(w,exact.goals,32*1024);
    package_cell(w,exact.journal,evidence_journal_limit);package_cell(w,exact.proof,frozen_proof_limit);
    const auto archive="CLEF-1\n"+sha256(w.bytes)+"\n"+w.bytes;
    require(archive.size()<=frozen_evidence_limit,"CL frozen evidence artifact is too large");
    return archive;
}
FrozenEvidence decode_frozen_evidence(const string& archive){
    constexpr string_view version="CLEF-1\n";
    require(archive.starts_with(version)&&archive.size()>=version.size()+65&&archive.size()<=frozen_evidence_limit&&
            archive[version.size()+64]=='\n',"invalid CL frozen evidence artifact");
    const auto payload=archive.substr(version.size()+65);
    require(sha256(payload)==archive.substr(version.size(),64),"CL frozen evidence artifact digest mismatch");
    IRReader r{payload};
    FrozenEvidence exact{package_get(r,package_limit),package_get(r,32*1024),
                         package_get(r,evidence_journal_limit),package_get(r,frozen_proof_limit)};
    require(r.offset==payload.size()&&encode_frozen_evidence(exact)==archive,"noncanonical CL frozen evidence artifact");
    return exact;
}
struct FrozenIntegrityInput { Program program; vector<Atom> goals; Table table; };
enum class FrozenProofPurpose { Admission, IntegrityReport };
string frozen_proof(const FrozenEvidence& exact,const string& trusted_package,const string& trusted_snapshot,EvidenceSign* sign=nullptr,const string& goal_address={},FrozenIntegrityInput* integrity=nullptr,FrozenProofPurpose purpose=FrozenProofPurpose::Admission){
    require(workspace_digest(trusted_package)&&sha256(exact.package)==trusted_package,"CL frozen evidence package pin mismatch");
    require(workspace_digest(trusted_snapshot)&&sha256(exact.journal)==trusted_snapshot,"CL frozen evidence snapshot pin mismatch");
    auto program=verify_package(decode_package(exact.package));
    auto requested=offline_goals(program,exact.goals);
    if(sign)require(requested.size()==1&&show(requested.front())+"\n"==goal_address,
                    "frozen CL artifact does not prove exactly the requested goal");
    const auto goal_pin=sha256(exact.goals);
    const auto state=read_evidence_snapshot(exact.journal,program,trusted_package,goal_pin);
    EvidencePlanes validator(program,requested);validator.verify_rows(state);
    for(const auto& [id,row]:state.rows)if(row.active)
        require(program.observations.emplace("live_"+id,row.atom).second,"frozen CL evidence collides with base data");
    auto table=run(program,{},nullptr,sign?JoinLimit{128,12000,2000000,2000000}:JoinLimit{});
    if(sign){
        const auto& ask=requested.front();
        const bool yes=table.facts.contains(ask),no=table.facts.contains({"!"+ask.pred,ask.args});
        set<Atom> disputes;
        for(const auto& [atom,_]:table.facts){
            Atom other=atom;
            if(other.pred.starts_with('!'))other.pred.erase(0,1);else other.pred="!"+other.pred;
            if(table.facts.contains(other))disputes.insert(atom);
        }
        if(purpose==FrozenProofPurpose::Admission && !disputes.empty() && yes!=no){
            const auto clean=run(program,{},nullptr,{128,12000,2000000,2000000},&disputes);
            const Atom supported=yes?ask:Atom{"!"+ask.pred,ask.args};
            require(clean.facts.contains(supported),"frozen proof depends on disputed premises");
        }
        *sign=yes?(no?EvidenceSign::Conflict:EvidenceSign::Positive):(no?EvidenceSign::Negative:EvidenceSign::Unknown);
    }
    const auto context="{\"mode\":\"frozen_evidence\",\"package_sha256\":"+quote_json(trusted_package)+
                       ",\"snapshot_sha256\":"+quote_json(trusted_snapshot)+",\"revision\":"+to_string(state.revision)+
                       ",\"goals_sha256\":"+quote_json(goal_pin)+"}";
    const auto proof=json_report(table,requested,"cl",context);
    require(proof.size()<=frozen_proof_limit,"CL frozen evidence proof exceeds receipt bound");
    if(integrity)*integrity={std::move(program),std::move(requested),std::move(table)};
    return proof;
}


SingleGoalProof offline_frozen_single_goal(const std::string& artifact,const std::string& expected_artifact,
        const std::string& expected_package,const std::string& expected_snapshot,const std::string& exact_goal){
    require(workspace_digest(expected_artifact)&&sha256(artifact)==expected_artifact,"CL frozen evidence artifact pin mismatch");
    const auto frozen=decode_frozen_evidence(artifact);
    EvidenceSign sign=EvidenceSign::Unknown;
    auto fresh=frozen_proof(frozen,expected_package,expected_snapshot,&sign,exact_goal);
    require(fresh==frozen.proof,"CL frozen evidence proof differs from independent recomputation");
    return {sign,std::move(fresh)};
}


std::string seal_frozen_evidence(const std::string& package,const std::string& trusted_package,const std::string& goals,
                                 const std::string& journal,const std::string& trusted_snapshot){
    FrozenEvidence held{package,goals,journal,{}};
    held.proof=frozen_proof(held,trusted_package,trusted_snapshot);
    return encode_frozen_evidence(held);
}
std::string verify_frozen_evidence(const std::string& raw,const std::string& trusted_artifact,
                                   const std::string& trusted_package,const std::string& trusted_snapshot){
    require(workspace_digest(trusted_artifact)&&sha256(raw)==trusted_artifact,"CL frozen evidence artifact pin mismatch");
    const auto item=decode_frozen_evidence(raw);
    const auto proof=frozen_proof(item,trusted_package,trusted_snapshot);
    require(item.proof==proof,"CL frozen evidence proof differs from independent recomputation");
    return proof+"\n";
}

std::string frozen_integrity_report(const FrozenEvidence& item,const FrozenIntegrityInput& input,const string& proof,
                                    const string& artifact,const string& package,const string& snapshot,bool* clean=nullptr){
    require_integrity_scope(input.program);
    return integrity_report(input.program,input.goals,input.table,
        "{\"schema\":\"cl-frozen-proof-integrity-v1\",\"artifact_sha256\":"+quote_json(artifact)+
        ",\"package_sha256\":"+quote_json(package)+",\"snapshot_sha256\":"+quote_json(snapshot)+
        ",\"goals_sha256\":"+quote_json(sha256(item.goals))+",\"signed_proof_sha256\":"+quote_json(sha256(proof)),clean);
}
std::string verify_frozen_integrity(const std::string& raw,const std::string& trusted_artifact,
                                    const std::string& trusted_package,const std::string& trusted_snapshot){
    require(workspace_digest(trusted_artifact)&&sha256(raw)==trusted_artifact,"CL frozen evidence artifact pin mismatch");
    const auto item=decode_frozen_evidence(raw);
    FrozenIntegrityInput input;
    const auto proof=frozen_proof(item,trusted_package,trusted_snapshot,nullptr,{},&input);
    require(item.proof==proof,"CL frozen evidence proof differs from independent recomputation");
    return frozen_integrity_report(item,input,proof,trusted_artifact,trusted_package,trusted_snapshot);
}
CheckedFrozenIntegrity offline_frozen_integrity_single_goal(const string& raw,const string& artifact,
                        const string& package,const string& snapshot,const string& goal){
    require(workspace_digest(artifact)&&sha256(raw)==artifact,"CL frozen evidence artifact pin mismatch");
    const auto item=decode_frozen_evidence(raw);
    FrozenIntegrityInput input;
    EvidenceSign sign=EvidenceSign::Unknown;
    auto proof=frozen_proof(item,package,snapshot,&sign,goal,&input,FrozenProofPurpose::IntegrityReport);
    require(item.proof==proof,"CL frozen evidence proof differs from independent recomputation");
    bool clean=false;
    auto report=frozen_integrity_report(item,input,proof,artifact,package,snapshot,&clean);
    return {sign,clean,std::move(proof),std::move(report)};
}
