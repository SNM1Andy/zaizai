constexpr size_t compiler_journal_limit=5*1024*1024;
string profile_snapshot_bytes(const CompilerSnapshot& state){
    require(!state.retained.empty()&&state.retained.size()<=4&&state.retained.contains(state.active),"invalid compiler snapshot");
    IRWriter w;
    package_cell(w,state.active,64);package_cell(w,state.smoke,256*1024);package_cell(w,state.expected,64);
    w.number(state.epoch);w.number(state.retained.size());
    for(const auto& [digest,profile]:state.retained){
        const auto bytes=encode_profile(profile);
        require(sha256(bytes)==digest&&profile.digest==digest,"retained profile identity mismatch");
        package_cell(w,bytes,1024*1024);
    }
    const auto payload="CLCS-1\n"+sha256(w.bytes)+"\n"+w.bytes;
    require(payload.size()<=compiler_journal_limit,"compiler journal too large");
    return payload;
}
CompilerSnapshot reopen_compiler_snapshot(const string& raw){
    const string marker="CLCS-1\n";
    require(raw.starts_with(marker)&&raw.size()>=marker.size()+65&&raw.size()<=compiler_journal_limit,
            "unknown compiler journal format");
    const auto payload=raw.substr(marker.size()+65);
    require(raw[marker.size()+64]=='\n'&&sha256(payload)==raw.substr(marker.size(),64),"compiler journal digest mismatch");
    IRReader r{payload};
    CompilerSnapshot out;
    out.active=package_get(r,64);out.smoke=package_get(r,256*1024);out.expected=package_get(r,64);
    require(out.expected.size()==64&&out.expected.find_first_not_of("0123456789abcdef")==string::npos,"invalid compiler smoke contract");
    out.epoch=r.number(0xffffffffU);
    const auto count=r.number(4);
    for(size_t i=0;i<count;++i){
        auto profile=decode_profile(package_get(r,1024*1024));
        auto digest=profile.digest;
        require(out.retained.emplace(digest,move(profile)).second,"duplicate retained compiler profile");
    }
    require(r.offset==payload.size()&&out.retained.contains(out.active),"incomplete compiler journal");
    require(profile_snapshot_bytes(out)==raw,"noncanonical compiler journal");
    return out;
}
struct CompilerJournal {
    fs::path path;
    native_os::Descriptor dir,lease;
    string known;
    explicit CompilerJournal(const fs::path& target)
        :path(fs::canonical(fs::absolute(target).parent_path())/target.filename()),
         dir(native_os::open_directory(path.parent_path())),
         lease(native_os::open_lock(dir.fd,path.filename().string()+".lock")){
        require(dir.fd>=0,"cannot open compiler journal directory or lock");
        native_os::acquire_lock(lease.fd,"cannot open compiler journal directory or lock",
            "compiler journal lock is not a regular file","compiler journal already has a writer");
    }
    void check_directory()const{
        native_os::confirm_directory(dir.fd,path.parent_path(),"compiler journal directory moved; reopen using its intended path");
    }
    string bytes(){
        check_directory();
        return native_os::read_confined_component(dir.fd,path.filename().string(),compiler_journal_limit,{
            "cannot open compiler journal directory","cannot open compiler journal","compiler journal is not a regular file",
            "read compiler journal failed","compiler journal read limit"});
    }
    CompilerSnapshot load(){
        const auto raw=bytes();
        auto state=reopen_compiler_snapshot(raw);
        known=sha256(raw);
        return state;
    }
    void save(const CompilerSnapshot& snapshot,bool init=false){
        if(!init)require(!known.empty()&&known==sha256(bytes()),"compiler journal changed outside the active session");
        check_directory();
        const auto raw=profile_snapshot_bytes(snapshot);
        try{
            native_os::atomic_local_commit(path.filename().string(),dir.fd,raw,".compiler-pending-",init,{
                "cannot create temporary compiler journal","write compiler journal failed","cannot confirm compiler journal file",
                "compiler journal already exists","cannot replace compiler journal",
                "compiler journal commit outcome uncertain; resume to reconcile"});
        }catch(const native_os::UncertainCommit& e){throw CompilerCommitUnknown(e.what());}
        known=sha256(raw);
    }
};
