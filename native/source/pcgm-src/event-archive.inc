fs::path archive_directory(const StateStore& store){return fs::path(store.dst.string()+".history");}
string archive_payload(const Continuity& state,const ArchiveSegment& part){
    require(part.first>0&&part.first<=part.last&&part.last<=state.events.size(),"archive bounds exceed the actual event history");
    string bytes="PCGM-HISTORY-1\n"+state.id+"\n"+to_string(part.first)+" "+to_string(part.last)+" "+
        part.previous+" "+part.snapshot+"\n";
    for(size_t i=part.first-1;i<part.last;++i)bytes+=state.events.at(i)+"\n";
    require(bytes.size()<=archive_segment_limit,"archive segment data limit");
    return bytes;
}
constexpr native_os::ReadMessages archive_words{
    "cannot open archive directory","cannot open archive segment","invalid archive segment file",
    "archive segment read failed","archive segment read limit"};
void verify_archive(const StateStore& store,const Continuity& state,const ArchiveSegment& item){
    auto bytes=store.asset_folder(".history").read(item.digest+".logseg",archive_segment_limit,archive_words);
    store.check_directory();
    require(sha256(bytes)==item.digest,"archive segment digest mismatch");
    require(bytes==archive_payload(state,item),"archive segment does not match the pinned journal range");
}
void publish_archive(const StateStore& store,const Continuity& state,const ArchiveSegment& item){
    auto bytes=archive_payload(state,item);
    require(sha256(bytes)==item.digest,"archive segment digest mismatch");
    store.keep_asset(".history",item.digest+".logseg",bytes,archive_segment_limit,archive_words);
}
string archive_report(const StateStore& store,const Continuity& state){
    ostringstream text;bool first=true;
    text<<"{\"schema\":\"pcgm-archives-v1\",\"individual\":"<<quote_json(state.id)
        <<",\"head\":"<<state.events.size()<<",\"sealed_through\":"<<(state.archives.empty()?0:state.archives.back().last)
        <<",\"segments\":[";
    for(const auto& segment:state.archives){
        verify_archive(store,state,segment);
        if(!first)text<<',';
        first=false;
        text<<"{\"start\":"<<segment.first<<",\"end\":"<<segment.last<<",\"digest\":"<<quote_json(segment.digest)
            <<",\"previous\":"<<quote_json(segment.previous)<<",\"snapshot_sha256\":"<<quote_json(segment.snapshot)<<'}';
    }
    text<<"]}";return text.str();
}
