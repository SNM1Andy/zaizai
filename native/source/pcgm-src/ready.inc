fs::path ready_dir(const StateStore& store){return fs::path(store.dst.string()+".ready");}
string ticket_body(const string& to,const string& bin,const string& snapshot){
    return "PCGM-READY-1\n"+to+" "+bin+" "+snapshot+"\n";
}
void ticket_ready(const StateStore& store,const string& candidate,const string& binary,const string& snapshot){
    const auto dir=ready_dir(store);
    fs::create_directory(dir);
    const auto body=ticket_body(candidate,binary,snapshot);
    const auto name=sha256(body)+".ready";
    if(!fs::exists(dir/name)){
        publish(dir/name,body);
    }
    require(read_transfer_file(dir,name,512)==body,"preparation receipt content mismatch");
    sync_directory(dir);sync_directory(dir.parent_path());
}
void require_ticket(const StateStore& store,const string& to,const string& bin,const string& snapshot){
    const auto want=ticket_body(to,bin,snapshot);
    try{
        require(read_transfer_file(ready_dir(store),sha256(want)+".ready",512)==want,"wrong preparation receipt");
    }catch(const runtime_error&){throw runtime_error("target has no verified preparation for this snapshot");}
}
