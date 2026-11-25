#ifndef PCGM_BUILD_NAME
#define PCGM_BUILD_NAME "development"
#endif
const string build_name=PCGM_BUILD_NAME;
string local_binary_hash(){
    const auto bytes=native_os::running_executable(16*1024*1024,{
        "cannot open own executable for attestation","cannot open own executable for attestation",
        "own executable is not a regular file","cannot hash own executable","exe digest limit"});
    return sha256(bytes);
}
string state_hash(const Continuity& state){return sha256(encode(state));}
void verify_pending_state(const Continuity& state){
    if(!state.pending)return;
    auto previous=state;
    previous.events.pop_back();
    previous.pending.reset();
    require(state_hash(previous)==state.pending->base_state,"handoff base snapshot mismatch");
}
