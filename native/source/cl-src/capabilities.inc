string cl_feature_manifest(){
    static const vector<pair<string,string>> commands{
        {"init","NEW_DIRECTORY"},{"compile","RULES.cl [DATA.cl]"},{"ir-run","IMAGE"},
        {"profile-build","PROFILE EXPECTED_PROFILE_SHA256 SOURCE"},
        {"compiler-init","JOURNAL PROFILE DIR SMOKE EXPECTED_IR_SHA256"},
        {"compiler-resume","JOURNAL DIR"},
        {"lock","ROOT.cl"},{"project-api","ROOT.cl LOCK [DATA.cl]"},
        {"project-pack","ROOT.cl LOCK API [DATA.cl]"},
        {"package-compare","BASE BASE_SHA256 CANDIDATE CANDIDATE_SHA256 GOALS"},
        {"package-profile","PACKAGE PIN GOALS [ROUNDS FACTS PROBES INDEXED]"},
        {"workspace-profile","ARCHIVE PIN LOCK GOALS [ROUNDS FACTS PROBES INDEXED]"},
        {"package-prove","PACKAGE PACKAGE_SHA256 GOALS"},
        {"package-proof-integrity","PACKAGE PACKAGE_SHA256 GOALS"},
        {"workspace-branch-additive","BASE BASE_SHA LOCK_SHA SOURCE SOURCE_SHA GOALS GOALS_SHA"},
        {"workspace-resolve","APP APP_SHA REQUIRES REQ_SHA CATALOG CAT_SHA [DATA DATA_SHA]"},
        {"workspace-pack","APP LOCK LOCK_SHA256 [DATA]"},
        {"workspace-prove","ARCHIVE ARCHIVE_SHA256 LOCK_SHA256 GOALS [ROUNDS FACTS PROBES INDEXED]"},
        {"workspace-bundle-verify","ARCHIVE ARCHIVE_SHA256 LOCK_SHA256"},
        {"workspace-replay-synthesis","BASE BASE_SHA LOCK_SHA RECIPE RECIPE_SHA SCOPE SCOPE_SHA EVIDENCE EVIDENCE_SHA CANDIDATE_SHA"},
        {"evidence-init","PACKAGE PACKAGE_SHA256 GOALS JOURNAL"},
        {"evidence-resume","PACKAGE PACKAGE_SHA256 GOALS JOURNAL"},
        {"evidence-audit","PACKAGE PACKAGE_SHA256 GOALS JOURNAL"},
        {"evidence-freeze","PACKAGE PACKAGE_SHA256 GOALS JOURNAL JOURNAL_SHA256"},
        {"evidence-frozen-verify","ARTIFACT ARTIFACT_SHA256 PACKAGE_SHA256 JOURNAL_SHA256"},
        {"evidence-frozen-integrity","ARTIFACT ARTIFACT_SHA256 PACKAGE_SHA256 JOURNAL_SHA256"},
        {"package-round-checkpoint","PACKAGE PIN GOALS NEW_CHECKPOINT [MAX_ROUNDS]"},
        {"package-round-audit","PACKAGE PIN GOALS CHECKPOINT CHECKPOINT_PIN [MAX_ROUNDS]"},
        {"package-round-reopen-verified","PACKAGE PIN GOALS CHECKPOINT CHECKPOINT_PIN [MAX_ROUNDS]"},
        {"package-plane-budget","PACKAGE PIN GOALS ROUNDS FACTS PROBES INDEXED MAX_WORKERS"}
    };
    ostringstream out;
    out<<"{\"schema\":\"cl-toolchain-capabilities-v1\",\"release\":\"0.157\",\"engine_role\":\"independent_compiler_and_prover\","
       <<"\"evaluation_backend\":\"cpu\",\"projection_backend\":\"guarded_cuda_or_cpu\",\"gpu_policy\":{\"reserve_mib\":3072,\"stop_c\":87,\"load_target\":99},\"pcgm_required\":false,\"formats\":[\"CLIR-8\",\"CLIR-7\",\"CLIR-6\",\"CLPKG-2\",\"CLWPACK-2\",\"CLES-1\",\"CLES-2\",\"CLEF-1\"],"
       <<"\"c_abi\":1,\"c_workspace_build\":true,\"c_profile_rebuild\":true,\"c_prepared_workspace\":true,\"commands\":[";
    size_t i=0;
    for(const auto& [name,args]:commands){
        if(i++)out<<',';
        out<<"{\"command\":"<<quote_json(name)<<",\"arguments\":"<<quote_json(args)<<'}';
    }
    out<<"]}";
    return out.str();
}
